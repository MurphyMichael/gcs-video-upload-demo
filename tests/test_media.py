import pytest
from fastapi.testclient import TestClient

from app.ranges import RangeNotSatisfiable, parse_range
from tests.fake_storage import FakeStorage

DATA = b"0123456789"


@pytest.fixture
def ready_id(client: TestClient, storage: FakeStorage) -> str:
    body = client.post(
        "/api/uploads",
        json={"filename": "clip.mp4", "content_type": "video/mp4", "size_bytes": 10},
    ).json()
    storage.put(f"uploads/{body['id']}", DATA)
    client.get(f"/api/uploads/{body['id']}")  # confirms it: pending -> ready
    upload_id: str = body["id"]
    return upload_id


def test_media_redirects_to_a_signed_url(client: TestClient, ready_id: str) -> None:
    response = client.get(f"/api/media/{ready_id}", follow_redirects=False)

    assert response.status_code == 302
    assert (
        response.headers["location"]
        == f"https://storage.test/signed/uploads/{ready_id}"
    )
    assert response.headers["cache-control"] == "no-store"


def test_media_is_404_until_the_upload_is_ready(client: TestClient) -> None:
    body = client.post(
        "/api/uploads",
        json={"filename": "clip.mp4", "content_type": "video/mp4", "size_bytes": 10},
    ).json()

    assert client.get(f"/api/media/{body['id']}").status_code == 404


def test_stream_without_range_returns_the_whole_object(
    client: TestClient, ready_id: str
) -> None:
    response = client.get(f"/api/media/{ready_id}?stream=1")

    assert response.status_code == 200
    assert response.content == DATA
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-type"] == "video/mp4"


@pytest.mark.parametrize(
    ("header", "body", "content_range"),
    [
        ("bytes=2-5", b"2345", "bytes 2-5/10"),
        ("bytes=7-", b"789", "bytes 7-9/10"),
        ("bytes=-3", b"789", "bytes 7-9/10"),
        ("bytes=8-100", b"89", "bytes 8-9/10"),
    ],
)
def test_stream_with_range_returns_partial_content(
    client: TestClient, ready_id: str, header: str, body: bytes, content_range: str
) -> None:
    response = client.get(f"/api/media/{ready_id}?stream=1", headers={"Range": header})

    assert response.status_code == 206
    assert response.content == body
    assert response.headers["content-range"] == content_range
    assert response.headers["content-length"] == str(len(body))


def test_stream_with_unsatisfiable_range_is_416(
    client: TestClient, ready_id: str
) -> None:
    response = client.get(
        f"/api/media/{ready_id}?stream=1", headers={"Range": "bytes=10-20"}
    )

    assert response.status_code == 416
    assert response.headers["content-range"] == "bytes */10"


def test_stream_ignores_a_malformed_range(client: TestClient, ready_id: str) -> None:
    response = client.get(
        f"/api/media/{ready_id}?stream=1", headers={"Range": "bytes=abc"}
    )

    assert response.status_code == 200
    assert response.content == DATA


@pytest.mark.parametrize(
    "header", ["items=0-5", "bytes=0-1,4-5", "bytes=-", "bytes=5-2", "bytes=1-x"]
)
def test_parse_range_ignores_headers_it_does_not_understand(header: str) -> None:
    assert parse_range(header, 10) is None


@pytest.mark.parametrize("header", ["bytes=10-", "bytes=-0"])
def test_parse_range_rejects_ranges_outside_the_object(header: str) -> None:
    with pytest.raises(RangeNotSatisfiable):
        parse_range(header, 10)


def test_parse_range_suffix_longer_than_the_object_returns_all_of_it() -> None:
    assert parse_range("bytes=-50", 10) == (0, 9)
