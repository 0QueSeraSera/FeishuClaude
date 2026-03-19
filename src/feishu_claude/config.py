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

    # Claude Configuration
    claude_workspace: Path = Field(default=Path("."), alias="CLAUDE_WORKSPACE")
    claude_model: str | None = Field(default=None, alias="CLAUDE_MODEL")
    claude_max_turns: int | None = Field(default=None, alias="CLAUDE_MAX_TURNS")

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


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
