from app.models import KEY_PREFIX, UploadStatus, new_upload


def test_new_upload_is_pending_and_keyed_by_its_id() -> None:
    upload = new_upload("clip.mp4", "video/mp4", 1234)

    assert upload.status is UploadStatus.PENDING
    assert upload.object_key == f"{KEY_PREFIX}{upload.id}"
