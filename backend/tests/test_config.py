from typing import Any

import pytest
from pydantic import ValidationError

from app.core.config import Environment, Settings

STRONG_SECRET = "x" * 40


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in Settings.model_fields:
        monkeypatch.delenv(name, raising=False)


def make(**overrides: Any) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_development_defaults() -> None:
    s = make()
    assert s.ENVIRONMENT is Environment.DEVELOPMENT
    assert s.DATABASE_URL.startswith("postgresql+asyncpg://zautomation:zautomation@localhost:5432/")


def test_cors_parsing_from_csv_and_json() -> None:
    assert make(BACKEND_CORS_ORIGINS="http://a.com, http://b.com").cors_origins == [
        "http://a.com",
        "http://b.com",
    ]
    assert make(BACKEND_CORS_ORIGINS='["http://c.com"]').cors_origins == ["http://c.com"]


@pytest.mark.parametrize("env", [Environment.STAGING, Environment.PRODUCTION])
def test_non_dev_rejects_default_secret(env: Environment) -> None:
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        make(ENVIRONMENT=env, POSTGRES_PASSWORD="strong-db-pass")


def test_production_rejects_debug() -> None:
    with pytest.raises(ValidationError, match="DEBUG"):
        make(
            ENVIRONMENT="production",
            SECRET_KEY=STRONG_SECRET,
            POSTGRES_PASSWORD="strong-db-pass",
            DEBUG=True,
        )


def test_production_valid() -> None:
    s = make(ENVIRONMENT="production", SECRET_KEY=STRONG_SECRET, POSTGRES_PASSWORD="p" * 16)
    assert s.is_production


def test_nested_llm_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM__LOGIC_DRAFTER", "anthropic/claude-sonnet-x")
    assert make().LLM.logic_drafter == "anthropic/claude-sonnet-x"


def test_empty_env_values_fall_back_to_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("S3_ENDPOINT_URL", "")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    s = make()
    assert s.S3_ENDPOINT_URL is None
    assert s.OPENAI_API_KEY is None
