"""WebSocket endpoint streaming AI synthesis progress: ``/ws/synthesis/{project_id}``.

Protocol (JSON text frames):
  client -> server  {"prompt": "...", "file_id": "<uuid>" | null}
  server -> client  SynthesisEvent {"agent", "status", "message", "attempt", "data", "timestamp"}
The last event of each run has ``agent == "orchestrator"`` and ``data.final == true``.
"""

import uuid
from typing import Annotated, Any

import anyio
import structlog
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.ai.agents.context import TabularSource, read_tabular
from app.ai.llm import LLMClient, get_llm_client
from app.ai.orchestrator import AgentName, EventStatus, SynthesisEvent, run_synthesis
from app.ai.rag import StandardsRetriever, get_retriever
from app.api.deps import get_current_user
from app.core.config import settings
from app.db.session import async_session_factory
from app.models import AuditLog, File, FileParseStatus, Project, ProjectStatus
from app.models.base import utcnow
from app.schemas.project import UIRSnapshotSummary
from app.schemas.uir import UIRProject
from app.services.parsers import requires_ai_ingestion
from app.services.snapshots import add_snapshot, latest_snapshot

router = APIRouter()
logger = structlog.get_logger(__name__)


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_session_factory


class SynthesisRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    file_id: uuid.UUID | None = None


def _event(status_: EventStatus, message: str, **data: Any) -> SynthesisEvent:
    return SynthesisEvent(
        agent=AgentName.ORCHESTRATOR, status=status_, message=message, data=data or None
    )


async def _load_source(
    session: AsyncSession, project_id: uuid.UUID, file_id: uuid.UUID | None
) -> tuple[File | None, TabularSource | None]:
    stmt = select(File).where(File.project_id == project_id)
    if file_id is not None:
        stmt = stmt.where(File.id == file_id)
    else:
        stmt = stmt.where(File.parse_status == FileParseStatus.PENDING)
    file = (await session.exec(stmt.order_by(col(File.created_at).desc()).limit(1))).first()
    if file is None:
        if file_id is not None:
            raise ValueError("file not found in this project")
        return None, None
    path = anyio.Path(file.local_path)
    if not requires_ai_ingestion(anyio.Path(file.filename)) or not await path.is_file():  # type: ignore[arg-type]
        if file_id is not None:
            raise ValueError(f"{file.filename} is not a CSV/Excel/text file awaiting ingestion")
        return None, None
    source = await anyio.to_thread.run_sync(read_tabular, path.as_posix(), file.filename)  # type: ignore[arg-type]
    return file, source


@router.websocket("/ws/synthesis/{project_id}")
async def synthesis_ws(
    websocket: WebSocket,
    project_id: uuid.UUID,
    factory: Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)],
    llm: Annotated[LLMClient, Depends(get_llm_client)],
    retriever: Annotated[StandardsRetriever, Depends(get_retriever)],
) -> None:
    origin = websocket.headers.get("origin")
    if origin is not None and origin.rstrip("/") not in settings.cors_origins:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await websocket.accept()

    async with factory() as session:
        user = await get_current_user(session)
        project = (
            await session.exec(
                select(Project).where(Project.id == project_id, Project.owner_id == user.id)
            )
        ).first()
    if project is None:
        await websocket.send_text(
            _event(EventStatus.FAILED, "Project not found", final=True).model_dump_json()
        )
        await websocket.close(code=4404)
        return

    async def emit(event: SynthesisEvent) -> None:
        await websocket.send_text(event.model_dump_json())

    await emit(
        _event(
            EventStatus.CONNECTED,
            "Connected to synthesis pipeline",
            mode="mock" if llm.mock else "live",
        )
    )
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                request = SynthesisRequest.model_validate_json(raw)
            except ValidationError as exc:
                await emit(
                    _event(
                        EventStatus.FAILED, f"Invalid request: {exc.errors()[0]['msg']}", final=True
                    )
                )
                continue
            await _run(request, project.id, user.id, factory, llm, retriever, emit)
    except WebSocketDisconnect:
        logger.info("synthesis.disconnected", project_id=str(project_id))


async def _run(
    request: SynthesisRequest,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    factory: async_sessionmaker[AsyncSession],
    llm: LLMClient,
    retriever: StandardsRetriever,
    emit: Any,
) -> None:
    async with factory() as session:
        project = await session.get(Project, project_id)
        assert project is not None
        latest = await latest_snapshot(session, project_id)
        base = (
            UIRProject.model_validate(latest.uir_json)
            if latest
            else UIRProject(name=project.name, vendor=project.original_vendor)
        )
        try:
            file, source = await _load_source(session, project_id, request.file_id)
        except ValueError as exc:
            await emit(_event(EventStatus.FAILED, str(exc), final=True))
            return
    await emit(
        _event(
            EventStatus.STARTED,
            f"Synthesis started on UIR v{latest.version}"
            if latest
            else "Synthesis started on an empty project",
            base_version=latest.version if latest else None,
        )
    )
    outcome = await run_synthesis(
        request.prompt, base, emit=emit, llm=llm, retriever=retriever, source=source
    )
    if outcome.status != "completed" or outcome.uir is None or outcome.diff is None:
        await emit(
            _event(
                EventStatus.FAILED,
                outcome.error or "Synthesis failed",
                final=True,
                retries=outcome.retries,
            )
        )
        return

    async with factory() as session:
        project = (
            await session.exec(select(Project).where(Project.id == project_id).with_for_update())
        ).one()
        snapshot = await add_snapshot(session, project_id, outcome.uir.model_dump(mode="json"))
        if file is not None:
            db_file = await session.get(File, file.id)
            if db_file is not None:
                db_file.parse_status = FileParseStatus.SUCCESS
                session.add(db_file)
        project.status = ProjectStatus.READY
        project.updated_at = utcnow()
        session.add(project)
        session.add(
            AuditLog(
                user_id=user_id,
                project_id=project_id,
                action="synthesis.completed",
                metadata_={
                    "prompt": request.prompt[:500],
                    "snapshot_version": snapshot.version,
                    "retries": outcome.retries,
                    "summary": outcome.diff.summary.model_dump(),
                },
            )
        )
        await session.commit()
        await session.refresh(snapshot)
    await emit(
        _event(
            EventStatus.COMPLETED,
            f"Saved UIR v{snapshot.version} ({outcome.diff.summary.added} added, "
            f"{outcome.diff.summary.removed} removed, {outcome.diff.summary.modified} modified)",
            final=True,
            retries=outcome.retries,
            snapshot=UIRSnapshotSummary.model_validate(snapshot).model_dump(mode="json"),
            summary=outcome.diff.summary.model_dump(),
        )
    )
