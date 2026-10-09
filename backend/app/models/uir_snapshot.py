import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Column, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.models.base import created_at_field


class UIRSnapshot(SQLModel, table=True):
    """Immutable, versioned UIR document. Snapshots form a hash chain per project."""

    __tablename__ = "uir_snapshots"
    __table_args__ = (UniqueConstraint("project_id", "version", name="uq_uir_snapshot_version"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    project_id: uuid.UUID = Field(foreign_key="projects.id", index=True, ondelete="CASCADE")
    version: int = Field(ge=1)
    version_hash: str = Field(max_length=64)
    parent_version_hash: str | None = Field(default=None, max_length=64)
    uir_json: dict[str, Any] = Field(sa_column=Column(JSONB, nullable=False))
    created_at: datetime = created_at_field()
