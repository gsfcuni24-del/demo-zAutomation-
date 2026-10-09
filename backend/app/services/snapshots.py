"""Versioned UIR snapshot persistence (hash-chained per project)."""

import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import UIRSnapshot
from app.services.uir import hash_uir


async def latest_snapshot(session: AsyncSession, project_id: uuid.UUID) -> UIRSnapshot | None:
    stmt = (
        select(UIRSnapshot)
        .where(UIRSnapshot.project_id == project_id)
        .order_by(col(UIRSnapshot.version).desc())
        .limit(1)
    )
    return (await session.exec(stmt)).first()


async def get_snapshot(
    session: AsyncSession, project_id: uuid.UUID, version: int | None = None
) -> UIRSnapshot:
    """Return ``version`` (or the latest) or raise 404."""
    if version is None:
        snapshot = await latest_snapshot(session, project_id)
    else:
        stmt = select(UIRSnapshot).where(
            UIRSnapshot.project_id == project_id, UIRSnapshot.version == version
        )
        snapshot = (await session.exec(stmt)).first()
    if snapshot is None:
        detail = (
            "No UIR snapshot for this project yet"
            if version is None
            else f"UIR version {version} not found"
        )
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail)
    return snapshot


async def list_snapshots(session: AsyncSession, project_id: uuid.UUID) -> list[UIRSnapshot]:
    stmt = (
        select(UIRSnapshot)
        .where(UIRSnapshot.project_id == project_id)
        .order_by(col(UIRSnapshot.version).desc())
    )
    return list((await session.exec(stmt)).all())


async def add_snapshot(
    session: AsyncSession, project_id: uuid.UUID, uir_json: dict[str, Any]
) -> UIRSnapshot:
    """Stage the next snapshot version. Callers must hold the project row lock and commit."""
    latest = await latest_snapshot(session, project_id)
    snapshot = UIRSnapshot(
        project_id=project_id,
        version=(latest.version + 1) if latest else 1,
        version_hash=hash_uir(uir_json),
        parent_version_hash=latest.version_hash if latest else None,
        uir_json=uir_json,
    )
    session.add(snapshot)
    return snapshot
