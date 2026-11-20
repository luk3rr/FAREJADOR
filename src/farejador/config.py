# Filename: config.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""Runtime configuration read from FAREJADOR_* environment variables (FR-22).

Configuration errors name the offending variable and never echo its value, so
secrets cannot leak through startup failures (NFR-3).
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated, Self

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

ENV_PREFIX = "FAREJADOR_"


class Mode(StrEnum):
    """How events reach the review core."""

    POLLING = "polling"
    WEBHOOK = "webhook"
    BOTH = "both"


class ConfigError(Exception):
    """Raised at startup when the configuration is missing or invalid."""


class Settings(BaseSettings):
    """All settings of the service; see design.md section 2.8, contract C-C."""

    model_config = SettingsConfigDict(env_prefix=ENV_PREFIX, extra="ignore", env_file=None)

    mode: Mode = Mode.POLLING
    github_app_id: int
    github_private_key_path: Path
    webhook_secret: SecretStr | None = None
    openrouter_api_key: SecretStr
    model: str = Field(min_length=1)
    trigger_text: str = Field(default="@farejador", min_length=1)
    bot_login: str | None = None
    poll_interval_s: int = Field(default=60, ge=5)
    workers: int = Field(default=2, ge=1, le=16)
    max_steps: int = Field(default=15, ge=1)
    max_tokens: int = Field(default=200_000, ge=1_000)
    max_seconds: int = Field(default=300, ge=10)
    max_files: int = Field(default=40, ge=1)
    ignore_globs: Annotated[list[str], NoDecode] = Field(default_factory=list)
    state_path: Path = Path("/data/farejador.db")
    host: str = "127.0.0.1"
    port: int = Field(default=8080, ge=1, le=65535)
    log_level: str = "INFO"

    @field_validator("ignore_globs", mode="before")
    @classmethod
    def _split_globs(cls, value: object) -> object:
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @field_validator("log_level")
    @classmethod
    def _check_log_level(cls, value: str) -> str:
        level = value.upper()
        if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("must be one of DEBUG, INFO, WARNING, ERROR, CRITICAL")
        return level

    @model_validator(mode="after")
    def _check_cross_fields(self) -> Self:
        if self.mode in (Mode.WEBHOOK, Mode.BOTH) and self.webhook_secret is None:
            raise ValueError(
                f"{ENV_PREFIX}WEBHOOK_SECRET is required when {ENV_PREFIX}MODE is webhook or both"
            )
        if not self.github_private_key_path.is_file():
            raise ValueError(f"{ENV_PREFIX}GITHUB_PRIVATE_KEY_PATH must point to an existing file")
        return self

    @classmethod
    def load(cls) -> Self:
        """Build settings from the environment or raise ``ConfigError`` without leaking values."""
        try:
            return cls()
        except ValidationError as exc:
            raise ConfigError(_describe(exc)) from None

    def secret_values(self) -> list[str]:
        """Return the secret strings that must be masked in logs and comments."""
        secrets = [self.openrouter_api_key.get_secret_value()]
        if self.webhook_secret is not None:
            secrets.append(self.webhook_secret.get_secret_value())
        return secrets


def _describe(exc: ValidationError) -> str:
    """Summarise validation errors by variable name only, never by input value."""
    lines: list[str] = []
    for error in exc.errors(include_input=False, include_url=False):
        message = str(error["msg"]).removeprefix("Value error, ")
        loc = error["loc"]
        if loc:
            name = f"{ENV_PREFIX}{str(loc[0]).upper()}"
            if error["type"] == "missing":
                lines.append(f"{name} is required")
            else:
                lines.append(f"{name} is invalid: {message}")
        else:
            lines.append(message)
    return "Invalid configuration: " + "; ".join(lines)
