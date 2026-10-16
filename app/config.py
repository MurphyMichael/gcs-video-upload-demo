from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, read from environment variables (or a .env file)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gcs_bucket: str = "videos"
    gcs_project: str | None = None
    # Set to use an emulator (e.g. fake-gcs-server); leave unset for real GCS.
    gcs_endpoint: str | None = None
    # The emulator's address as the browser sees it, if different from gcs_endpoint.
    gcs_public_endpoint: str | None = None

    database_url: str = "sqlite:///./uploads.db"
    # The browser origin allowed to PUT to upload sessions.
    allowed_origin: str = "http://localhost:8000"

    signed_url_expiry_seconds: int = 15 * 60
    max_upload_bytes: int = 5 * 1024**3
    stale_after_hours: int = 24
    purge_grace_days: int = 7


@lru_cache
def get_settings() -> Settings:
    return Settings()
