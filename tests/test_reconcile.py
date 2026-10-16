from datetime import datetime, timedelta

from sqlmodel import Session

from app.config import Settings
from app.models import Upload, UploadStatus, new_upload, utcnow
from app.reconcile import reconcile
from tests.fake_storage import FakeStorage

NOW = utcnow()
OLD = NOW - timedelta(hours=25)  # past the 24h stale window
FRESH = NOW - timedelta(hours=1)


def add_upload(
    session: Session, status: UploadStatus, created_at: datetime = OLD
) -> Upload:
    upload = new_upload("clip.mp4", "video/mp4", 10)
    upload.status = status
    upload.created_at = upload.updated_at = created_at
    session.add(upload)
    session.commit()
    return upload


def run(
    session: Session, storage: FakeStorage, settings: Settings, fix: bool = True
) -> dict[str, object]:
    return vars(reconcile(session, storage, settings, now=NOW, fix=fix))


def test_old_pending_upload_with_no_object_is_marked_failed(
    session: Session, storage: FakeStorage, settings: Settings
) -> None:
    upload = add_upload(session, UploadStatus.PENDING)

    report = run(session, storage, settings)

    assert report["stuck_uploads"] == [str(upload.id)]
    session.refresh(upload)
    assert upload.status is UploadStatus.FAILED


def test_recent_pending_and_ready_uploads_are_left_alone(
    session: Session, storage: FakeStorage, settings: Settings
) -> None:
    recent = add_upload(session, UploadStatus.PENDING, created_at=FRESH)
    ready = add_upload(session, UploadStatus.READY)  # its object is missing too

    report = run(session, storage, settings)

    assert report["stuck_uploads"] == []
    session.refresh(recent)
    session.refresh(ready)
    assert recent.status is UploadStatus.PENDING
    assert ready.status is UploadStatus.READY


def test_old_orphan_objects_are_deleted_but_young_ones_kept(
    session: Session, storage: FakeStorage, settings: Settings
) -> None:
    for _ in range(9):  # referenced objects keep the orphan ratio low
        upload = add_upload(session, UploadStatus.READY)
        storage.put(upload.object_key, b"x" * 10)
    storage.put("uploads/old-orphan", b"x", created_at=OLD)
    storage.put("uploads/young-orphan", b"x", created_at=FRESH)

    report = run(session, storage, settings)

    assert report["orphan_objects"] == ["uploads/old-orphan"]
    assert storage.deleted == ["uploads/old-orphan"]
    assert "uploads/young-orphan" in storage.info


def test_safety_stop_changes_nothing_when_most_objects_look_orphaned(
    session: Session, storage: FakeStorage, settings: Settings
) -> None:
    stuck = add_upload(session, UploadStatus.PENDING)
    for i in range(25):
        storage.put(f"uploads/orphan-{i}", b"x", created_at=OLD)

    report = run(session, storage, settings)

    assert report["safety_stop"] is True
    assert report["fixed"] is False
    assert storage.deleted == []
    session.refresh(stuck)
    assert stuck.status is UploadStatus.PENDING


def test_failed_uploads_are_purged_after_the_grace_period(
    session: Session, storage: FakeStorage, settings: Settings
) -> None:
    expired = add_upload(
        session, UploadStatus.FAILED, created_at=NOW - timedelta(days=8)
    )
    recent = add_upload(
        session, UploadStatus.FAILED, created_at=NOW - timedelta(days=6)
    )
    expired_id = expired.id

    report = run(session, storage, settings)

    assert report["purged_uploads"] == [str(expired_id)]
    assert session.get(Upload, expired_id) is None
    assert session.get(Upload, recent.id) is not None


def test_report_only_by_default(
    session: Session, storage: FakeStorage, settings: Settings
) -> None:
    upload = add_upload(session, UploadStatus.PENDING)
    storage.put("uploads/orphan", b"x", created_at=OLD)

    report = run(session, storage, settings, fix=False)

    assert report["stuck_uploads"] == [str(upload.id)]
    assert report["orphan_objects"] == ["uploads/orphan"]
    assert report["fixed"] is False
    assert storage.deleted == []
    session.refresh(upload)
    assert upload.status is UploadStatus.PENDING
