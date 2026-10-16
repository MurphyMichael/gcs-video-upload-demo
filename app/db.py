from sqlalchemy import Engine
from sqlmodel import SQLModel, create_engine


def make_engine(database_url: str) -> Engine:
    # FastAPI runs sync endpoints in a thread pool, so SQLite must allow that.
    engine = create_engine(database_url, connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine
