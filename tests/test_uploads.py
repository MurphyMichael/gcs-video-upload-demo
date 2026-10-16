from fastapi.testclient import TestClient

from tests.fake_storage import FakeStorage

VIDEO = {"filename": "clip.mp4", "content_type": "video/mp4", "size_bytes": 10}


def start(client: TestClient, **overrides: object) -> dict[str, str]:
    response = client.post("/api/uploads", json={**VIDEO, **overrides})
    assert response.status_code == 201, response.text
    body: dict[str, str] = response.json()
    return body


def test_start_upload_opens_a_session_and_returns_its_url(
    client: TestClient, storage: FakeStorage
) -> None:
    body = start(client)

    assert body["status"] == "pending"
    assert storage.sessions == [
        {
            "key": f"uploads/{body['id']}",
            "content_type": "video/mp4",
            "size": 10,
            "origin": "http://localhost:8000",
        }
    ]
    assert body["upload_url"] == f"https://storage.test/upload/uploads/{body['id']}"


def test_start_upload_rejects_non_video(client: TestClient) -> None:
    response = client.post("/api/uploads", json={**VIDEO, "content_type": "text/html"})
    assert response.status_code == 422


def test_start_upload_rejects_files_over_the_limit(client: TestClient) -> None:
    response = client.post("/api/uploads", json={**VIDEO, "size_bytes": 1001})
    assert response.status_code == 413


def test_status_stays_pending_while_the_object_is_missing(client: TestClient) -> None:
    upload_id = start(client)["id"]

    assert client.get(f"/api/uploads/{upload_id}").json()["status"] == "pending"


def test_status_becomes_ready_once_the_object_matches(
    client: TestClient, storage: FakeStorage
) -> None:
    upload_id = start(client)["id"]
    storage.put(f"uploads/{upload_id}", b"0123456789")

    assert client.get(f"/api/uploads/{upload_id}").json()["status"] == "ready"


def test_status_fails_when_the_object_has_the_wrong_size(
    client: TestClient, storage: FakeStorage
) -> None:
    upload_id = start(client)["id"]
    storage.put(f"uploads/{upload_id}", b"too short")

    assert client.get(f"/api/uploads/{upload_id}").json()["status"] == "failed"


def test_status_of_unknown_upload_is_404(client: TestClient) -> None:
    response = client.get("/api/uploads/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
