"""Project, file upload and UIR snapshot endpoints."""

import re
import uuid
from typing import Annotated, Any

import anyio
import structlog
from fastapi import APIRouter, HTTPException, Query, Response, UploadFile, status
from fastapi import File as FileParam
from sqlmodel import col, select

from app.api.deps import CurrentUserDep, SessionDep, StorageDep
from app.models import AuditLog, File, FileParseStatus, Project, ProjectStatus, User
from app.models.base import utcnow
from app.schemas.project import (
    FileRead,
    FileUploadResponse,
    ProjectCreate,
    ProjectRead,
    UIRDiffResponse,
    UIRSnapshotRead,
    UIRSnapshotSummary,
)
from app.schemas.uir import UIRProject
from app.services.auditor import AuditReport, audit
from app.services.compilers import CompileError, compile_rockwell_l5x
from app.services.diff_engine import diff_uir
from app.services.parsers import ParseError, ParseResult, parse_file, requires_ai_ingestion
from app.services.snapshots import add_snapshot, get_snapshot, list_snapshots
from app.services.storage import FileTooLargeError, StorageError

router = APIRouter(prefix="/projects", tags=["projects"])
logger = structlog.get_logger(__name__)


async def _get_owned_project(
    session: SessionDep, user: User, project_id: uuid.UUID, *, for_update: bool = False
) -> Project:
    stmt = select(Project).where(Project.id == project_id, Project.owner_id == user.id)
    if for_update:
        stmt = stmt.with_for_update()
    project = (await session.exec(stmt)).first()
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return project


def _audit(
    user: User, project_id: uuid.UUID | None, action: str, metadata: dict[str, Any]
) -> AuditLog:
    return AuditLog(user_id=user.id, project_id=project_id, action=action, metadata_=metadata)


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: ProjectCreate, session: SessionDep, user: CurrentUserDep
) -> Project:
    project = Project(name=payload.name, original_vendor=payload.original_vendor, owner_id=user.id)
    session.add(project)
    await session.flush()
    session.add(_audit(user, project.id, "project.created", {"name": project.name}))
    await session.commit()
    await session.refresh(project)
    return project


@router.get("", response_model=list[ProjectRead])
async def list_projects(session: SessionDep, user: CurrentUserDep) -> list[Project]:
    stmt = (
        select(Project).where(Project.owner_id == user.id).order_by(col(Project.updated_at).desc())
    )
    return list((await session.exec(stmt)).all())


@router.get("/{project_id}", response_model=ProjectRead)
async def get_project(project_id: uuid.UUID, session: SessionDep, user: CurrentUserDep) -> Project:
    return await _get_owned_project(session, user, project_id)


@router.get("/{project_id}/files", response_model=list[FileRead])
async def list_project_files(
    project_id: uuid.UUID, session: SessionDep, user: CurrentUserDep
) -> list[File]:
    await _get_owned_project(session, user, project_id)
    stmt = select(File).where(File.project_id == project_id).order_by(col(File.created_at).desc())
    return list((await session.exec(stmt)).all())


@router.post(
    "/{project_id}/files",
    response_model=FileUploadResponse,
    status_code=status.HTTP_201_CREATED,
    responses={422: {"description": "Unsupported, invalid or unsafe file"}},
)
async def upload_project_file(
    project_id: uuid.UUID,
    upload: Annotated[UploadFile, FileParam(alias="file")],
    session: SessionDep,
    user: CurrentUserDep,
    storage: StorageDep,
) -> FileUploadResponse:
    """Store the file and deterministically parse it into a new UIR snapshot.

    L5X/XML and UIR JSON are parsed immediately. CSV/Excel/text inputs are stored as PENDING and
    turned into UIR by the AI assistant. Parse failures keep a FAILED file record and return 422.
    """
    # Row lock serialises concurrent uploads so snapshot versions stay gap-free and unique.
    project = await _get_owned_project(session, user, project_id, for_update=True)
    try:
        stored = await storage.save(upload, project.id)
    except FileTooLargeError as exc:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, str(exc)) from exc
    except StorageError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    parsed: ParseResult | None = None
    parse_error: str | None = None
    if not requires_ai_ingestion(stored.path):
        try:
            parsed = await anyio.to_thread.run_sync(
                lambda: parse_file(stored.path, source_filename=stored.filename)
            )
        except ParseError as exc:
            parse_error = str(exc)

    try:
        file = File(
            project_id=project.id,
            filename=stored.filename,
            local_path=str(stored.path),
            file_size_bytes=stored.size_bytes,
            parse_status=FileParseStatus.PENDING,
        )
        session.add(file)
        snapshot = None
        metadata: dict[str, Any] = {
            "file_id": str(file.id),
            "filename": stored.filename,
            "size_bytes": stored.size_bytes,
        }
        if parse_error is not None:
            file.parse_status = FileParseStatus.FAILED
            session.add(
                _audit(user, project.id, "file.parse_failed", metadata | {"error": parse_error})
            )
        else:
            if parsed is not None:
                file.parse_status = FileParseStatus.SUCCESS
                snapshot = await add_snapshot(
                    session, project.id, parsed.project.model_dump(mode="json")
                )
                project.status = ProjectStatus.READY
                metadata |= {"snapshot_version": snapshot.version, "warnings": parsed.warnings}
            project.updated_at = utcnow()
            session.add(project)
            session.add(_audit(user, project.id, "file.uploaded", metadata))
        await session.commit()
    except BaseException:
        await session.rollback()
        await storage.delete(stored.path)
        raise

    if parse_error is not None:
        logger.info("file.parse_failed", project_id=str(project.id), error=parse_error)
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"Could not parse file: {parse_error}"
        )

    await session.refresh(file)
    if snapshot is not None:
        await session.refresh(snapshot)
    logger.info(
        "file.uploaded",
        project_id=str(project.id),
        file_id=str(file.id),
        version=snapshot.version if snapshot else None,
    )
    return FileUploadResponse(
        file=FileRead.model_validate(file),
        snapshot=UIRSnapshotSummary.model_validate(snapshot) if snapshot else None,
        warnings=parsed.warnings if parsed else [],
    )


def _snapshot_read(snapshot: Any) -> UIRSnapshotRead:
    return UIRSnapshotRead(
        **UIRSnapshotSummary.model_validate(snapshot).model_dump(),
        uir=UIRProject.model_validate(snapshot.uir_json),
    )


@router.get("/{project_id}/uir/latest", response_model=UIRSnapshotRead)
async def get_latest_uir(
    project_id: uuid.UUID, session: SessionDep, user: CurrentUserDep
) -> UIRSnapshotRead:
    await _get_owned_project(session, user, project_id)
    return _snapshot_read(await get_snapshot(session, project_id))


@router.get("/{project_id}/uir/versions", response_model=list[UIRSnapshotSummary])
async def list_uir_versions(
    project_id: uuid.UUID, session: SessionDep, user: CurrentUserDep
) -> list[UIRSnapshotSummary]:
    await _get_owned_project(session, user, project_id)
    return [UIRSnapshotSummary.model_validate(s) for s in await list_snapshots(session, project_id)]


@router.get("/{project_id}/uir/diff", response_model=UIRDiffResponse)
async def diff_uir_versions(
    project_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUserDep,
    base: Annotated[int | None, Query(ge=1, description="Defaults to target - 1")] = None,
    target: Annotated[int | None, Query(ge=1, description="Defaults to latest")] = None,
) -> UIRDiffResponse:
    """Structured ADDED/REMOVED/MODIFIED changes between two snapshot versions."""
    await _get_owned_project(session, user, project_id)
    target_snapshot = await get_snapshot(session, project_id, target)
    base_version = base if base is not None else target_snapshot.version - 1 or None
    base_json = (
        (await get_snapshot(session, project_id, base_version)).uir_json if base_version else None
    )
    result = diff_uir(base_json, target_snapshot.uir_json)
    return UIRDiffResponse(
        base_version=base_version,
        target_version=target_snapshot.version,
        summary=result.summary,
        changes=result.changes,
    )


@router.get("/{project_id}/uir/audit", response_model=AuditReport)
async def audit_uir(
    project_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUserDep,
    version: Annotated[int | None, Query(ge=1)] = None,
) -> AuditReport:
    """Run the deterministic safety rules (R-001..R-003) against a snapshot."""
    await _get_owned_project(session, user, project_id)
    snapshot = await get_snapshot(session, project_id, version)
    return audit(snapshot.uir_json)


@router.get("/{project_id}/uir/{version}", response_model=UIRSnapshotRead)
async def get_uir_version(
    project_id: uuid.UUID, version: int, session: SessionDep, user: CurrentUserDep
) -> UIRSnapshotRead:
    await _get_owned_project(session, user, project_id)
    return _snapshot_read(await get_snapshot(session, project_id, version))


_UNSAFE_FILENAME = re.compile(r"[^A-Za-z0-9_-]+")


@router.get(
    "/{project_id}/export/l5x",
    response_class=Response,
    responses={200: {"content": {"application/xml": {}}}},
)
async def export_l5x(
    project_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUserDep,
    version: Annotated[int | None, Query(ge=1)] = None,
) -> Response:
    """Compile a snapshot into a Rockwell L5X file (deterministic Jinja2, no LLM)."""
    project = await _get_owned_project(session, user, project_id)
    snapshot = await get_snapshot(session, project_id, version)
    try:
        xml = compile_rockwell_l5x(UIRProject.model_validate(snapshot.uir_json))
    except CompileError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    filename = (
        f"{_UNSAFE_FILENAME.sub('_', project.name).strip('_') or 'project'}_v{snapshot.version}.L5X"
    )
    return Response(
        content=xml,
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
