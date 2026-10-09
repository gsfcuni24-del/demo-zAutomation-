"""ARQ worker configuration. Run with: arq app.workers.settings.WorkerSettings"""

from typing import Any, ClassVar

import structlog
from arq.connections import RedisSettings

from app.core.config import settings

logger = structlog.get_logger(__name__)


async def ping(ctx: dict[str, Any]) -> str:
    logger.info("worker.ping", job_id=ctx.get("job_id"))
    return "pong"


async def startup(ctx: dict[str, Any]) -> None:
    logger.info("worker.startup")


async def shutdown(ctx: dict[str, Any]) -> None:
    logger.info("worker.shutdown")


class WorkerSettings:
    functions: ClassVar[list[Any]] = [ping]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(str(settings.REDIS_URL))
    max_jobs = 10
    job_timeout = 600
