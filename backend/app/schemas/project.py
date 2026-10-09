"""API request/response DTOs for projects, files and UIR snapshots. Mirrored in types/api.ts."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import FileParseStatus, ProjectStatus
from app.schemas.uir import UIRProject


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    original_vendor: str | None = Field(default=None, max_length=64)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("name must not be blank")
        return stripped


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    owner_id: uuid.UUID
    original_vendor: str | None
    status: ProjectStatus
    created_at: datetime
    updated_at: datetime


class FileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    filename: str
    file_size_bytes: int
    parse_status: FileParseStatus
    created_at: datetime


class UIRSnapshotSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    version: int
    version_hash: str
    parent_version_hash: str | None
    created_at: datetime


class UIRSnapshotRead(UIRSnapshotSummary):
    uir: UIRProject


class FileUploadResponse(BaseModel):
    file: FileRead
    snapshot: UIRSnapshotSummary
