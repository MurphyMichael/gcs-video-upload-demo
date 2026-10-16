from collections.abc import Iterator
from datetime import datetime

from app.models import utcnow
from app.storage import ObjectInfo


class FakeStorage:
    """In-memory stand-in for GcsStorage. `put` plays the browser's PUT."""

    def __init__(self, chunk_size: int = 4) -> None:
        self.chunk_size = chunk_size
        self.data: dict[str, bytes] = {}
        self.info: dict[str, ObjectInfo] = {}
        self.sessions: list[dict[str, object]] = []
        self.deleted: list[str] = []

    def put(
        self,
        key: str,
        data: bytes,
        content_type: str = "video/mp4",
        created_at: datetime | None = None,
    ) -> None:
        self.data[key] = data
        self.info[key] = ObjectInfo(
            key, len(data), content_type, created_at or utcnow()
        )

    def create_upload_session(
        self, key: str, content_type: str, size: int, origin: str
    ) -> str:
        self.sessions.append(
            {"key": key, "content_type": content_type, "size": size, "origin": origin}
        )
        return f"https://storage.test/upload/{key}"

    def get_info(self, key: str) -> ObjectInfo | None:
        return self.info.get(key)

    def download_url(self, key: str) -> str:
        return f"https://storage.test/signed/{key}"

    def iter_range(self, key: str, start: int, end: int) -> Iterator[bytes]:
        for position in range(start, end + 1, self.chunk_size):
            yield self.data[key][position : min(position + self.chunk_size, end + 1)]

    def list_objects(self, prefix: str) -> Iterator[ObjectInfo]:
        return iter([info for key, info in self.info.items() if key.startswith(prefix)])

    def delete(self, key: str) -> None:
        self.data.pop(key, None)
        self.info.pop(key, None)
        self.deleted.append(key)
