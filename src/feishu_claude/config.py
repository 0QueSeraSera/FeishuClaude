"""Configuration management using pydantic-settings."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # Feishu Configuration
    feishu_app_id: str = Field(default="", alias="FEISHU_APP_ID")
    feishu_app_secret: str = Field(default="", alias="FEISHU_APP_SECRET")
    feishu_verification_token: str = Field(default="", alias="FEISHU_VERIFICATION_TOKEN")
    feishu_connection_mode: Literal["long_connection", "webhook"] = Field(
        default="long_connection", alias="FEISHU_CONNECTION_MODE"
    )
    feishu_allow_user_ids: str = Field(default="", alias="FEISHU_ALLOW_USER_IDS")
    feishu_allow_group_chats: bool = Field(default=True, alias="FEISHU_ALLOW_GROUP_CHATS")
    feishu_backend: Literal["claude", "codex"] = Field(default="codex", alias="FEISHU_BACKEND")
    feishu_default_language: Literal["zh", "en"] = Field(default="zh", alias="FEISHU_DEFAULT_LANGUAGE")
    feishu_progress_updates_enabled: bool = Field(
        default=True,
        alias="FEISHU_PROGRESS_UPDATES_ENABLED",
    )
    feishu_progress_event_interval: int = Field(default=30, alias="FEISHU_PROGRESS_EVENT_INTERVAL")
    feishu_progress_min_seconds: float = Field(default=8.0, alias="FEISHU_PROGRESS_MIN_SECONDS")
    feishu_progress_min_interval_seconds: float = Field(
        default=2.0,
        alias="FEISHU_PROGRESS_MIN_INTERVAL_SECONDS",
    )
    feishu_default_turn_limit: int | None = Field(default=None, alias="FEISHU_DEFAULT_TURN_LIMIT")
    feishu_default_budget_usd: float | None = Field(default=None, alias="FEISHU_DEFAULT_BUDGET_USD")

    # Claude Configuration
    claude_workspace: Path = Field(default=Path("."), alias="CLAUDE_WORKSPACE")
    claude_model: str | None = Field(default=None, alias="CLAUDE_MODEL")
    claude_max_turns: int | None = Field(default=None, alias="CLAUDE_MAX_TURNS")

    # Codex Configuration
    codex_workspace: Path | None = Field(default=None, alias="CODEX_WORKSPACE")
    codex_model: str | None = Field(default="gpt-5.3-codex", alias="CODEX_MODEL")
    codex_search_enabled: bool = Field(default=False, alias="CODEX_SEARCH_ENABLED")
    codex_default_mode: Literal["safe", "normal", "full"] = Field(
        default="safe", alias="CODEX_DEFAULT_MODE"
    )
    codex_execpolicy_rules: str = Field(default="", alias="CODEX_EXECPOLICY_RULES")

    @field_validator("feishu_allow_user_ids", mode="before")
    @classmethod
    def parse_user_ids(cls, v: str) -> str:
        """Normalize user IDs string."""
        if isinstance(v, str):
            return v.strip()
        return ""

    @property
    def allowed_user_ids(self) -> set[str]:
        """Parse allowed user IDs into a set."""
        if not self.feishu_allow_user_ids:
            return set()
        return {uid.strip() for uid in self.feishu_allow_user_ids.split(",") if uid.strip()}

    def validate_feishu(self) -> list[str]:
        """Validate Feishu configuration. Returns list of errors."""
        errors: list[str] = []
        if not self.feishu_app_id:
            errors.append("FEISHU_APP_ID is required")
        if not self.feishu_app_secret:
            errors.append("FEISHU_APP_SECRET is required")
        return errors

    @property
    def effective_codex_workspace(self) -> Path:
        """Return codex workspace, defaulting to Claude workspace/current directory."""
        return self.codex_workspace or self.claude_workspace

    @property
    def codex_execpolicy_rule_paths(self) -> list[Path]:
        """Return parsed execpolicy rule file paths."""
        if not self.codex_execpolicy_rules.strip():
            return []
        return [
            Path(value.strip())
            for value in self.codex_execpolicy_rules.split(",")
            if value.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
