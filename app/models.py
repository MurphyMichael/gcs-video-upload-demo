import uuid
from datetime import UTC, datetime
from enum import StrEnum

from sqlmodel import Field, SQLModel

KEY_PREFIX = "uploads/"


def utcnow() -> datetime:
    return datetime.now(UTC)


class UploadStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"


class Upload(SQLModel, table=True):
    id: uuid.UUID = Field(primary_key=True)
    object_key: str = Field(unique=True, index=True)
    filename: str
    content_type: str
    size_bytes: int
    status: UploadStatus = Field(default=UploadStatus.PENDING, index=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


def new_upload(filename: str, content_type: str, size_bytes: int) -> Upload:
    upload_id = uuid.uuid4()
    return Upload(
        id=upload_id,
        object_key=f"{KEY_PREFIX}{upload_id}",
        filename=filename,
        content_type=content_type,
        size_bytes=size_bytes,
    )
