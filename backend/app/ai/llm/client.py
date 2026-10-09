"""LiteLLM router (Claude primary -> GPT-4o fallback) wrapped by Instructor.

Every AI agent goes through :meth:`LLMClient.structured`, which forces a Pydantic-validated
response (Instructor re-asks the model with the validation errors on failure). In mock mode the
same LiteLLM + Instructor path is used, with LiteLLM's ``mock_response`` supplying deterministic
JSON so the full pipeline (including validation) runs offline.
"""

from collections.abc import Callable
from functools import lru_cache
from typing import Any, Literal, TypeVar

import instructor
import litellm
import structlog
from litellm.router import Router
from pydantic import BaseModel

from app.core.config import Settings, settings

logger = structlog.get_logger(__name__)
litellm.suppress_debug_info = True

AgentModelGroup = Literal["excel_parser", "tag_namer", "logic_drafter", "hmi_layouter"]
AGENT_MODEL_GROUPS: tuple[AgentModelGroup, ...] = (
    "excel_parser",
    "tag_namer",
    "logic_drafter",
    "hmi_layouter",
)
FALLBACK_GROUP = "fallback"

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    """The model could not produce a valid structured response (after retries/fallbacks)."""


def _api_key(model: str, cfg: Settings) -> str | None:
    secret = cfg.ANTHROPIC_API_KEY if "anthropic/" in model or "claude" in model else None
    if secret is None and not ("anthropic/" in model or "claude" in model):
        secret = cfg.OPENAI_API_KEY
    return secret.get_secret_value() if secret else None


def build_router(cfg: Settings) -> Router:
    def params(model: str) -> dict[str, Any]:
        out: dict[str, Any] = {"model": model, "timeout": cfg.LLM_TIMEOUT_SECONDS}
        if key := _api_key(model, cfg):
            out["api_key"] = key
        return out

    model_list: list[dict[str, Any]] = [
        {"model_name": group, "litellm_params": params(getattr(cfg.LLM, group))}
        for group in AGENT_MODEL_GROUPS
    ]
    model_list.append({"model_name": FALLBACK_GROUP, "litellm_params": params(cfg.LLM.fallback)})
    fallbacks: list[Any] = [{group: [FALLBACK_GROUP]} for group in AGENT_MODEL_GROUPS]
    return Router(
        model_list=model_list,
        fallbacks=fallbacks,
        num_retries=1,
        timeout=cfg.LLM_TIMEOUT_SECONDS,
    )


class LLMClient:
    def __init__(self, cfg: Settings = settings, *, mock: bool | None = None) -> None:
        self.mock = cfg.llm_mock if mock is None else mock
        self.max_retries = cfg.LLM_MAX_RETRIES
        self.router = build_router(cfg)
        self.instructor = instructor.from_litellm(
            self.router.acompletion, mode=instructor.Mode.JSON
        )

    async def structured(
        self,
        agent: AgentModelGroup,
        response_model: type[T],
        messages: list[dict[str, str]],
        *,
        mock: Callable[[], T],
        context: dict[str, Any] | None = None,
    ) -> T:
        kwargs: dict[str, Any] = {}
        if self.mock:
            kwargs["mock_response"] = mock().model_dump_json()
        try:
            result: T = await self.instructor.chat.completions.create(
                model=agent,
                response_model=response_model,  # type: ignore[arg-type]
                messages=messages,  # type: ignore[arg-type]
                max_retries=self.max_retries,
                context=context,
                temperature=0,
                **kwargs,
            )
        except Exception as exc:
            logger.warning("llm.failed", agent=agent, error=str(exc)[:500])
            raise LLMError(f"{agent}: {_short(exc)}") from exc
        return result


def _short(exc: Exception) -> str:
    text = str(exc).strip().splitlines()
    return (text[0] if text else type(exc).__name__)[:300]


@lru_cache
def get_llm_client() -> LLMClient:
    return LLMClient()
