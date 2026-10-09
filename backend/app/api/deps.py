"""Shared FastAPI dependencies."""

from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import Environment, settings
from app.db.session import get_session
from app.models import User
from app.services.storage import LocalFileStorage, get_storage

DEV_USER_EMAIL = "dev@zautomation.local"

SessionDep = Annotated[AsyncSession, Depends(get_session)]
StorageDep = Annotated[LocalFileStorage, Depends(get_storage)]


async def get_current_user(session: SessionDep) -> User:
    """Temporary stand-in until fastapi-users auth lands: every request acts as one dev user."""
    if settings.ENVIRONMENT is not Environment.DEVELOPMENT:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication is not configured")
    await session.exec(
        insert(User)
        .values(email=DEV_USER_EMAIL, hashed_password="!", is_verified=True)  # noqa: S106
        .on_conflict_do_nothing(index_elements=["email"])
    )
    user = (await session.exec(select(User).where(User.email == DEV_USER_EMAIL))).one()
    await session.commit()
    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]
