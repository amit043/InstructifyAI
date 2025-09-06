from io import BytesIO
from urllib.parse import parse_qs, urlparse

from storage.object_store import (
    ObjectStore,
    derived_key,
    export_key,
    raw_key,
    signed_url,
)


class FakeS3Client:
    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}

    def put_object(self, Bucket: str, Key: str, Body: bytes) -> None:
        self.store[Key] = Body

    def get_object(self, Bucket: str, Key: str) -> dict:
        return {"Body": BytesIO(self.store[Key])}

    def list_objects_v2(self, Bucket: str, Prefix: str) -> dict:
        keys = [k for k in self.store if k.startswith(Prefix)]
        return {"Contents": [{"Key": k} for k in keys]}

    def generate_presigned_url(
        self, operation: str, Params: dict, ExpiresIn: int
    ) -> str:
        return f"https://example.com/{Params['Key']}?X-Amz-Expires={ExpiresIn}"


def test_roundtrip_and_presign() -> None:
    client = FakeS3Client()
    store = ObjectStore(client=client, bucket="test-bucket")
    key = raw_key("doc1", "doc1.txt")
    store.put_bytes(key, b"hello")
    assert store.get_bytes(key) == b"hello"
    assert store.list("raw") == [key]
    url = store.presign_get(key, expiry=60)
    qs = parse_qs(urlparse(url).query)
    assert qs["X-Amz-Expires"] == ["60"]
    put_url = store.presign_put(key, expiry=60)
    qs = parse_qs(urlparse(put_url).query)
    assert qs["X-Amz-Expires"] == ["60"]


def test_signed_url_helper_uses_settings(monkeypatch) -> None:
    monkeypatch.setenv("EXPORT_SIGNED_URL_EXPIRY_SECONDS", "123")
    from core.settings import get_settings

    get_settings.cache_clear()
    client = FakeS3Client()
    store = ObjectStore(client=client, bucket="test-bucket")
    url = signed_url(store, "foo")
    qs = parse_qs(urlparse(url).query)
    assert qs["X-Amz-Expires"] == ["123"]
    get_settings.cache_clear()


def test_key_layout_helpers() -> None:
    assert raw_key("d", "f.txt") == "raw/d/f.txt"
    assert derived_key("d", "chunks.json") == "derived/d/chunks.json"
    assert export_key("e", "manifest.json") == "exports/e/manifest.json"
