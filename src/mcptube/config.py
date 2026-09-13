"""Configuration management for mcptube."""

from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings with environment variable overrides.

    All settings can be overridden via environment variables
    prefixed with MCPTUBE_ (e.g. MCPTUBE_DATA_DIR, MCPTUBE_HOST).
    """

    model_config = {"env_prefix": "MCPTUBE_"}

    # Storage
    data_dir: Path = Field(
        default_factory=lambda: Path.home() / ".mcptube",
        description="Root directory for all mcptube data",
    )
    frames_dir: Path | None = Field(
        default=None,
        description="Directory for cached extracted frames. Defaults to data_dir/frames.",
    )
    wiki_dir: Path | None = Field(
        default=None,
        description="Directory for wiki JSON store. Defaults to data_dir/wiki.",
    )
    wiki_db: Path | None = Field(
        default=None,
        description="SQLite FTS index for the wiki. Defaults to wiki_dir/wiki.db.",
    )

    # Server
    host: str = "127.0.0.1"
    port: int = 9093

    # LLM (BYOK — used in CLI mode, wired up later)
    default_model: str = "gpt-4o"

    @model_validator(mode="after")
    def _set_defaults(self) -> "Settings":
        """Set derived defaults that depend on other fields."""
        if self.frames_dir is None:
            self.frames_dir = self.data_dir / "frames"
        if self.wiki_dir is None:
            self.wiki_dir = self.data_dir / "wiki"
        if self.wiki_db is None:
            self.wiki_db = self.wiki_dir / "wiki.db"
        return self

    @property
    def db_path(self) -> Path:
        """SQLite database path."""
        return self.data_dir / "mcptube.db"

    def ensure_dirs(self) -> None:
        """Create all required directories if they don't exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.frames_dir.mkdir(parents=True, exist_ok=True)


# Module-level singleton — import this throughout the app
settings = Settings()
