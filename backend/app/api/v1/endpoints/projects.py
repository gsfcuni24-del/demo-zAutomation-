"""Project, file upload and UIR snapshot endpoints."""

import uuid
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, HTTPException, UploadFile, status
from fastapi import File as FileParam
from sqlmodel import col, select

from app.api.deps import CurrentUserDep, SessionDep, StorageDep
from app.models import AuditLog, File, FileParseStatus, Project, ProjectStatus, UIRSnapshot, User
from app.models.base import utcnow
from app.schemas.project import (
    FileRead,
    FileUploadResponse,
    ProjectCreate,
    ProjectRead,
    UIRSnapshotRead,
    UIRSnapshotSummary,
)
from app.schemas.uir import UIRProject
from app.services.storage import FileTooLargeError, StorageError
from app.services.uir import build_mock_uir, hash_uir

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
)
async def upload_project_file(
    project_id: uuid.UUID,
    upload: Annotated[UploadFile, FileParam(alias="file")],
    session: SessionDep,
    user: CurrentUserDep,
    storage: StorageDep,
) -> FileUploadResponse:
    # Row lock serialises concurrent uploads so snapshot versions stay gap-free and unique.
    project = await _get_owned_project(session, user, project_id, for_update=True)
    try:
        stored = await storage.save(upload, project.id)
    except FileTooLargeError as exc:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, str(exc)) from exc
    except StorageError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    try:
        file = File(
            project_id=project.id,
            filename=stored.filename,
            local_path=str(stored.path),
            file_size_bytes=stored.size_bytes,
            parse_status=FileParseStatus.PARSING,
        )
        session.add(file)

        # Phase 2: no real parsing yet; every upload yields a mock UIR snapshot.
        uir = build_mock_uir(project.name, project.original_vendor, stored.filename)
        uir_json = uir.model_dump(mode="json")
        latest = (
            await session.exec(
                select(UIRSnapshot)
                .where(UIRSnapshot.project_id == project.id)
                .order_by(col(UIRSnapshot.version).desc())
                .limit(1)
            )
        ).first()
        snapshot = UIRSnapshot(
            project_id=project.id,
            version=(latest.version + 1) if latest else 1,
            version_hash=hash_uir(uir_json),
            parent_version_hash=latest.version_hash if latest else None,
            uir_json=uir_json,
        )
        session.add(snapshot)

        file.parse_status = FileParseStatus.SUCCESS
        project.status = ProjectStatus.READY
        project.updated_at = utcnow()
        session.add(project)
        session.add(
            _audit(
                user,
                project.id,
                "file.uploaded",
                {
                    "file_id": str(file.id),
                    "filename": stored.filename,
                    "size_bytes": stored.size_bytes,
                    "snapshot_version": snapshot.version,
                },
            )
        )
        await session.commit()
    except BaseException:
        await session.rollback()
        await storage.delete(stored.path)
        raise

    await session.refresh(file)
    await session.refresh(snapshot)
    logger.info(
        "file.uploaded", project_id=str(project.id), file_id=str(file.id), version=snapshot.version
    )
    return FileUploadResponse(
        file=FileRead.model_validate(file),
        snapshot=UIRSnapshotSummary.model_validate(snapshot),
    )


@router.get("/{project_id}/uir/latest", response_model=UIRSnapshotRead)
async def get_latest_uir(
    project_id: uuid.UUID, session: SessionDep, user: CurrentUserDep
) -> UIRSnapshotRead:
    await _get_owned_project(session, user, project_id)
    snapshot = (
        await session.exec(
            select(UIRSnapshot)
            .where(UIRSnapshot.project_id == project_id)
            .order_by(col(UIRSnapshot.version).desc())
            .limit(1)
        )
    ).first()
    if snapshot is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No UIR snapshot for this project yet")
    return UIRSnapshotRead(
        **UIRSnapshotSummary.model_validate(snapshot).model_dump(),
        uir=UIRProject.model_validate(snapshot.uir_json),
    )
