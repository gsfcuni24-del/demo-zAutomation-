import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import BigInteger, Column
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field, SQLModel

from app.models.base import created_at_field


class FileParseStatus(StrEnum):
    PENDING = "PENDING"
    PARSING = "PARSING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class File(SQLModel, table=True):
    __tablename__ = "files"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    project_id: uuid.UUID = Field(foreign_key="projects.id", index=True, ondelete="CASCADE")
    filename: str = Field(max_length=255)
    local_path: str = Field(max_length=1024)
    file_size_bytes: int = Field(sa_type=BigInteger)
    parse_status: FileParseStatus = Field(
        default=FileParseStatus.PENDING,
        sa_column=Column(SAEnum(FileParseStatus, name="file_parse_status"), nullable=False),
    )
    created_at: datetime = created_at_field()
