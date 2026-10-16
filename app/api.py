import uuid
from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.responses import RedirectResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.config import Settings
from app.models import Upload, UploadStatus, new_upload, utcnow
from app.ranges import RangeNotSatisfiable, parse_range
from app.storage import ObjectInfo, Storage

router = APIRouter(prefix="/api")


def get_session(request: Request) -> Iterator[Session]:
    with Session(request.app.state.engine) as session:
        yield session


def get_storage(request: Request) -> Storage:
    storage: Storage = request.app.state.storage
    return storage


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


SessionDep = Annotated[Session, Depends(get_session)]
StorageDep = Annotated[Storage, Depends(get_storage)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


class StartUploadRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(pattern=r"^video/[\w.+-]+$")
    size_bytes: int = Field(gt=0)


class StartUploadResponse(BaseModel):
    id: uuid.UUID
    status: UploadStatus
    upload_url: str


class UploadOut(BaseModel):
    id: uuid.UUID
    filename: str
    content_type: str
    size_bytes: int
    status: UploadStatus


@router.post("/uploads", status_code=201)
def start_upload(
    body: StartUploadRequest,
    session: SessionDep,
    storage: StorageDep,
    settings: SettingsDep,
) -> StartUploadResponse:
    if body.size_bytes > settings.max_upload_bytes:
        raise HTTPException(413, "File is larger than the upload limit")

    upload = new_upload(body.filename, body.content_type, body.size_bytes)
    # Open the session before saving the record: if this fails, nothing is left
    # behind. An unused session expires on its own and never creates an object.
    upload_url = storage.create_upload_session(
        upload.object_key,
        body.content_type,
        body.size_bytes,
        origin=settings.allowed_origin,
    )
    session.add(upload)
    session.commit()
    return StartUploadResponse(
        id=upload.id, status=upload.status, upload_url=upload_url
    )


@router.get("/uploads/{upload_id}")
def get_upload(
    upload_id: uuid.UUID, session: SessionDep, storage: StorageDep
) -> UploadOut:
    upload = _get_upload_or_404(session, upload_id)
    if upload.status is UploadStatus.PENDING:
        new_status = check_upload(upload, storage.get_info(upload.object_key))
        if new_status is not UploadStatus.PENDING:
            upload.status = new_status
            upload.updated_at = utcnow()
            session.add(upload)
            session.commit()
    return UploadOut.model_validate(upload, from_attributes=True)


def check_upload(upload: Upload, info: ObjectInfo | None) -> UploadStatus:
    """Decide a pending upload's status from what is actually in the bucket."""
    if info is None:
        return UploadStatus.PENDING
    if info.size == upload.size_bytes and info.content_type == upload.content_type:
        return UploadStatus.READY
    return UploadStatus.FAILED


@router.get("/media/{upload_id}")
def get_media(
    upload_id: uuid.UUID,
    session: SessionDep,
    storage: StorageDep,
    stream: bool = False,
    range_header: Annotated[str | None, Header(alias="range")] = None,
) -> Response:
    upload = _get_upload_or_404(session, upload_id)
    if upload.status is not UploadStatus.READY:
        raise HTTPException(404, "Upload not found")

    if not stream:
        # no-store: a cached redirect would outlive the signed URL it points to.
        return RedirectResponse(
            storage.download_url(upload.object_key),
            status_code=302,
            headers={"Cache-Control": "no-store"},
        )
    return _stream_object(storage, upload, range_header)


def _stream_object(
    storage: Storage, upload: Upload, range_header: str | None
) -> Response:
    size = upload.size_bytes
    headers = {"Accept-Ranges": "bytes"}
    try:
        byte_range = parse_range(range_header, size) if range_header else None
    except RangeNotSatisfiable:
        return Response(
            status_code=416, headers={**headers, "Content-Range": f"bytes */{size}"}
        )

    if byte_range is None:
        start, end, status_code = 0, size - 1, 200
    else:
        (start, end), status_code = byte_range, 206
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    headers["Content-Length"] = str(end - start + 1)

    return StreamingResponse(
        storage.iter_range(upload.object_key, start, end),
        status_code=status_code,
        media_type=upload.content_type,
        headers=headers,
    )


def _get_upload_or_404(session: Session, upload_id: uuid.UUID) -> Upload:
    upload = session.get(Upload, upload_id)
    if upload is None:
        raise HTTPException(404, "Upload not found")
    return upload
