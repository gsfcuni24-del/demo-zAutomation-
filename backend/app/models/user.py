import uuid
from datetime import datetime

from sqlmodel import Field, SQLModel

from app.models.base import created_at_field


class User(SQLModel, table=True):
    """Account table; field layout matches fastapi-users so auth can be wired in later."""

    __tablename__ = "users"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    email: str = Field(max_length=320, unique=True, index=True)
    hashed_password: str = Field(max_length=1024)
    is_active: bool = True
    is_superuser: bool = False
    is_verified: bool = False
    created_at: datetime = created_at_field()
