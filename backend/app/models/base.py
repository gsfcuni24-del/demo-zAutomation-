"""Shared column helpers for SQLModel tables."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Column, DateTime
from sqlmodel import Field


def utcnow() -> datetime:
    return datetime.now(UTC)


def created_at_field() -> Any:
    return Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False, default=utcnow),
    )


def updated_at_field() -> Any:
    return Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow),
    )
