from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlmodel import Session

from app.config import Settings
from app.db import make_engine
from app.main import create_app
from tests.fake_storage import FakeStorage


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, max_upload_bytes=1000)  # type: ignore[call-arg]


@pytest.fixture
def storage() -> FakeStorage:
    return FakeStorage()


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return make_engine(f"sqlite:///{tmp_path / 'test.db'}")


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    with Session(engine) as session:
        yield session


@pytest.fixture
def client(settings: Settings, storage: FakeStorage, engine: Engine) -> TestClient:
    return TestClient(create_app(settings, storage, engine))
