from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy import Engine

from app.api import router
from app.config import Settings, get_settings
from app.db import make_engine
from app.storage import GcsStorage, Storage

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def create_app(settings: Settings, storage: Storage, engine: Engine) -> FastAPI:
    """Build the app around its dependencies, so tests can pass in fakes."""
    app = FastAPI(title="GCS video upload demo")
    app.state.settings = settings
    app.state.storage = storage
    app.state.engine = engine
    app.include_router(router)
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app


def build_app() -> FastAPI:
    """Entry point for `uvicorn app.main:build_app --factory`."""
    settings = get_settings()
    return create_app(
        settings, GcsStorage(settings), make_engine(settings.database_url)
    )
