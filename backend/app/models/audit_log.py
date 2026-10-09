import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Column, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.models.base import created_at_field


class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_logs"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="users.id", index=True, ondelete="CASCADE")
    project_id: uuid.UUID | None = Field(
        default=None, foreign_key="projects.id", index=True, ondelete="SET NULL"
    )
    action: str = Field(max_length=64, index=True)
    # `metadata` is reserved on SQLAlchemy declarative classes, so the attribute is suffixed.
    metadata_: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column("metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    )
    created_at: datetime = created_at_field()
