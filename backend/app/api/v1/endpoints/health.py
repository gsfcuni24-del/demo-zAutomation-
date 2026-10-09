"""Liveness and readiness probes."""

import asyncio
from collections.abc import Coroutine
from typing import Any, Literal

import httpx
from fastapi import APIRouter, Response, status
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import text

from app.core.config import settings
from app.db.session import engine

router = APIRouter()

CheckStatus = Literal["ok", "error"]


class HealthResponse(BaseModel):
    status: CheckStatus
    version: str
    environment: str


class ReadinessResponse(BaseModel):
    status: CheckStatus
    checks: dict[str, CheckStatus]


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok", version=settings.VERSION, environment=settings.ENVIRONMENT.value
    )


async def _check_postgres() -> None:
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


async def _check_redis() -> None:
    client: Redis = Redis.from_url(str(settings.REDIS_URL))
    try:
        await client.ping()
    finally:
        await client.aclose()


async def _check_qdrant() -> None:
    headers = (
        {"api-key": settings.QDRANT_API_KEY.get_secret_value()} if settings.QDRANT_API_KEY else {}
    )
    async with httpx.AsyncClient(timeout=3.0) as client:
        url = f"{str(settings.QDRANT_URL).rstrip('/')}/readyz"
        response = await client.get(url, headers=headers)
        response.raise_for_status()


async def _run(check_name: str, coro: Coroutine[Any, Any, None]) -> tuple[str, CheckStatus]:
    try:
        await asyncio.wait_for(coro, timeout=5.0)
    except Exception:
        return check_name, "error"
    return check_name, "ok"


@router.get("/health/ready", response_model=ReadinessResponse)
async def readiness(response: Response) -> ReadinessResponse:
    results = await asyncio.gather(
        _run("postgres", _check_postgres()),
        _run("redis", _check_redis()),
        _run("qdrant", _check_qdrant()),
    )
    checks: dict[str, CheckStatus] = dict(results)
    overall: CheckStatus = "ok" if all(v == "ok" for v in checks.values()) else "error"
    if overall == "error":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(status=overall, checks=checks)
