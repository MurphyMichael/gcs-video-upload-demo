from app.storage import Storage
from tests.fake_storage import FakeStorage


def test_fake_satisfies_the_storage_protocol() -> None:
    storage: Storage = FakeStorage()  # mypy checks the fake against the protocol
    assert storage.get_info("missing") is None


def test_iter_range_yields_inclusive_range_in_chunks() -> None:
    storage = FakeStorage(chunk_size=4)
    storage.put("k", b"0123456789")

    assert list(storage.iter_range("k", 1, 8)) == [b"1234", b"5678"]
