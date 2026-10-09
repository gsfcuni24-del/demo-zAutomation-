import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Column
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field, SQLModel

from app.models.base import created_at_field, updated_at_field


class ProjectStatus(StrEnum):
    DRAFT = "DRAFT"
    PARSING = "PARSING"
    READY = "READY"
    ARCHIVED = "ARCHIVED"


class Project(SQLModel, table=True):
    __tablename__ = "projects"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(max_length=255)
    owner_id: uuid.UUID = Field(foreign_key="users.id", index=True, ondelete="CASCADE")
    original_vendor: str | None = Field(default=None, max_length=64)
    status: ProjectStatus = Field(
        default=ProjectStatus.DRAFT,
        sa_column=Column(SAEnum(ProjectStatus, name="project_status"), nullable=False),
    )
    created_at: datetime = created_at_field()
    updated_at: datetime = updated_at_field()
