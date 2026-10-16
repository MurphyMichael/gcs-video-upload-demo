"""The storage boundary: the only module that imports google-cloud-storage."""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from urllib.parse import quote

import google.auth
from google.api_core.exceptions import NotFound
from google.auth.credentials import AnonymousCredentials, Credentials, Signing
from google.auth.transport.requests import Request
from google.cloud import storage

from app.config import Settings

CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True)
class ObjectInfo:
    key: str
    size: int
    content_type: str | None
    created_at: datetime


class Storage(Protocol):
    def create_upload_session(
        self, key: str, content_type: str, size: int, origin: str
    ) -> str: ...

    def get_info(self, key: str) -> ObjectInfo | None: ...

    def download_url(self, key: str) -> str: ...

    def iter_range(self, key: str, start: int, end: int) -> Iterator[bytes]: ...

    def list_objects(self, prefix: str) -> Iterator[ObjectInfo]: ...

    def delete(self, key: str) -> None: ...


class GcsStorage:
    def __init__(self, settings: Settings) -> None:
        self._emulator = settings.gcs_endpoint
        self._public_endpoint = settings.gcs_public_endpoint or settings.gcs_endpoint
        self._url_expiry = timedelta(seconds=settings.signed_url_expiry_seconds)

        if self._emulator:
            self._credentials: Credentials = AnonymousCredentials()
            client_options = {"api_endpoint": self._emulator}
        else:
            self._credentials, _ = google.auth.default()
            client_options = None
        self._client = storage.Client(
            project=settings.gcs_project,
            credentials=self._credentials,
            client_options=client_options,
        )
        self._bucket = self._client.bucket(settings.gcs_bucket)

    def create_upload_session(
        self, key: str, content_type: str, size: int, origin: str
    ) -> str:
        # `size` makes GCS reject a body of any other length; `origin` makes GCS
        # answer the browser's CORS preflight for this session URL.
        url: str = self._bucket.blob(key).create_resumable_upload_session(
            content_type=content_type, size=size, origin=origin
        )
        if self._emulator and self._public_endpoint:
            # The emulator builds the URL from the address we called it on,
            # which the browser may not be able to reach.
            url = url.replace(self._emulator, self._public_endpoint, 1)
        return url

    def get_info(self, key: str) -> ObjectInfo | None:
        blob = self._bucket.get_blob(key)
        return _to_info(blob) if blob else None

    def download_url(self, key: str) -> str:
        if self._emulator:
            # The emulator can't check V4 signatures, so local dev gets a plain URL.
            return (
                f"{self._public_endpoint}/storage/v1/b/{self._bucket.name}"
                f"/o/{quote(key, safe='')}?alt=media"
            )
        url: str = self._bucket.blob(key).generate_signed_url(
            version="v4",
            expiration=self._url_expiry,
            method="GET",
            **self._signing_kwargs(),
        )
        return url

    def _signing_kwargs(self) -> dict[str, str]:
        if isinstance(self._credentials, Signing):  # e.g. a service account key
            return {}
        # Cloud Run's default credentials hold only a token, no private key.
        # Passing the account email + token makes the library sign via IAM signBlob.
        if not self._credentials.valid:
            self._credentials.refresh(Request())
        return {
            "service_account_email": self._credentials.service_account_email,  # type: ignore[attr-defined]
            "access_token": str(self._credentials.token),
        }

    def iter_range(self, key: str, start: int, end: int) -> Iterator[bytes]:
        blob = self._bucket.blob(key)
        position = start
        while position <= end:
            chunk_end = min(position + CHUNK_SIZE - 1, end)
            chunk: bytes = blob.download_as_bytes(start=position, end=chunk_end)
            yield chunk
            position = chunk_end + 1

    def list_objects(self, prefix: str) -> Iterator[ObjectInfo]:
        for blob in self._client.list_blobs(self._bucket, prefix=prefix):
            yield _to_info(blob)

    def delete(self, key: str) -> None:
        try:
            self._bucket.blob(key).delete()
        except NotFound:
            pass  # already gone, which is what we wanted


def _to_info(blob: storage.Blob) -> ObjectInfo:
    return ObjectInfo(
        key=blob.name,
        size=blob.size or 0,
        content_type=blob.content_type,
        created_at=blob.time_created,
    )
