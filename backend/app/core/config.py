"""Application configuration (Pydantic Settings) for development, staging and production."""

from enum import StrEnum
from functools import lru_cache
from typing import Annotated, Literal, Self

from pydantic import (
    AnyHttpUrl,
    Field,
    PostgresDsn,
    RedisDsn,
    SecretStr,
    computed_field,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

INSECURE_SECRET_PREFIX = "change-me"  # noqa: S105


class Environment(StrEnum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class LLMModels(BaseSettings):
    """LiteLLM model identifiers per agent (overridable via LLM__<AGENT> env vars)."""

    model_config = SettingsConfigDict(extra="ignore")

    excel_parser: str = "gpt-4o-mini"
    tag_namer: str = "gpt-4o-mini"
    logic_drafter: str = "anthropic/claude-3-5-sonnet-20241022"
    hmi_layout: str = "gpt-4o"
    embedding: str = "text-embedding-3-small"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        env_ignore_empty=True,
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application ---
    PROJECT_NAME: str = "zAutomation Helper AI"
    VERSION: str = "0.1.0"
    ENVIRONMENT: Environment = Environment.DEVELOPMENT
    DEBUG: bool = False
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    API_V1_PREFIX: str = "/api/v1"
    BACKEND_CORS_ORIGINS: Annotated[list[AnyHttpUrl], NoDecode] = Field(
        default_factory=lambda: [AnyHttpUrl("http://localhost:3000")]
    )

    # --- Security / Auth (fastapi-users JWT) ---
    SECRET_KEY: SecretStr = SecretStr(f"{INSECURE_SECRET_PREFIX}-dev-only-secret-key-min-32-chars")
    ACCESS_TOKEN_EXPIRE_SECONDS: int = Field(default=60 * 60, gt=0)

    # --- PostgreSQL ---
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "zautomation"
    POSTGRES_PASSWORD: SecretStr = SecretStr("zautomation")
    POSTGRES_DB: str = "zautomation"
    DB_POOL_SIZE: int = Field(default=10, gt=0)
    DB_MAX_OVERFLOW: int = Field(default=20, ge=0)
    DB_ECHO: bool = False

    # --- Redis / ARQ ---
    REDIS_URL: RedisDsn = RedisDsn("redis://localhost:6379/0")

    # --- Qdrant ---
    QDRANT_URL: AnyHttpUrl = AnyHttpUrl("http://localhost:6333")
    QDRANT_API_KEY: SecretStr | None = None
    QDRANT_STANDARDS_COLLECTION: str = "automation_standards"

    # --- Object storage (S3-compatible) ---
    S3_ENDPOINT_URL: AnyHttpUrl | None = None
    S3_BUCKET: str = "zautomation-files"
    S3_REGION: str = "us-east-1"
    S3_ACCESS_KEY_ID: SecretStr | None = None
    S3_SECRET_ACCESS_KEY: SecretStr | None = None
    MAX_UPLOAD_SIZE_MB: int = Field(default=100, gt=0)

    # --- LLM providers (LiteLLM) ---
    OPENAI_API_KEY: SecretStr | None = None
    ANTHROPIC_API_KEY: SecretStr | None = None
    LLM: LLMModels = Field(default_factory=LLMModels)
    LLM_TIMEOUT_SECONDS: float = Field(default=120.0, gt=0)
    LLM_MAX_RETRIES: int = Field(default=3, ge=0)
    LOGIC_DRAFTER_MAX_AUDIT_LOOPS: int = Field(default=3, ge=1)

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def _parse_cors(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("["):
                import json

                return json.loads(stripped)
            return [origin.strip() for origin in stripped.split(",") if origin.strip()]
        return value

    @computed_field  # type: ignore[prop-decorator]
    @property
    def DATABASE_URL(self) -> str:  # noqa: N802
        return str(
            PostgresDsn.build(
                scheme="postgresql+asyncpg",
                username=self.POSTGRES_USER,
                password=self.POSTGRES_PASSWORD.get_secret_value(),
                host=self.POSTGRES_HOST,
                port=self.POSTGRES_PORT,
                path=self.POSTGRES_DB,
            )
        )

    @property
    def cors_origins(self) -> list[str]:
        return [str(origin).rstrip("/") for origin in self.BACKEND_CORS_ORIGINS]

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT is Environment.PRODUCTION

    @model_validator(mode="after")
    def _enforce_environment_rules(self) -> Self:
        if self.ENVIRONMENT is Environment.DEVELOPMENT:
            return self
        secret = self.SECRET_KEY.get_secret_value()
        if secret.startswith(INSECURE_SECRET_PREFIX) or len(secret) < 32:
            raise ValueError(
                f"SECRET_KEY must be a strong (>=32 chars) non-default value in {self.ENVIRONMENT}"
            )
        if self.POSTGRES_PASSWORD.get_secret_value() == "zautomation":
            raise ValueError(f"POSTGRES_PASSWORD must not use the default in {self.ENVIRONMENT}")
        if self.ENVIRONMENT is Environment.PRODUCTION:
            if self.DEBUG:
                raise ValueError("DEBUG must be false in production")
            if self.DB_ECHO:
                raise ValueError("DB_ECHO must be false in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
