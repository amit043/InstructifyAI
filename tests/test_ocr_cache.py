import base64
from io import BytesIO

import pytest

from storage.object_store import ObjectStore
from worker.ocr_cache import METRICS, cache_hit_ratio, ocr_cached, ocr_time

IMAGE_PNG_BASE64 = "iVBORw0KGgoAAAANSUhEUgAAAGQAAAAoCAIAAACHGsgUAAAB+UlEQVR4nO3Yv6uyUBjA8YyXgpYgqMH2gqJFpziDmuLSFASNTY3N/SVNDdUS/QVhP4YarE1CCILG2m3KMPLcQa5c3vcle6Dw3svzmfR0isO3ziFkKKUR9Jxo2Av4STAWAMYCwFgAGAsAYwFgLACMBYCxADAWAMYCCI7V7/d5ni+XyzzPD4dDb7DX63EcJwhCtVo9Ho/eYCKREEVREASO41ar1RtXHRb6kKZphBDLsiillmURQubz+Ww2kyTpcrlQSieTSaVS8SYnk0nvwjTNUqn0+JN/ooBYsiyv12v/Vtd1RVFUVd1sNv5gq9VyHId+ieW6biqVev1iwxYQi2VZ27b9W9u2WZbNZrPX6/XfyX4sTdPq9frrFvld/IHuWYZh7vf7f191HEcUxdvttt/vd7vdKw6J7yXggC8UCoZh+LeGYRSLxVwut91uvRFKabPZ9K5jsdhyudR1vdPpDAaDt6w3XI9/eNPplBByPp/p5wG/WCzG47GiKN5OHI1GjUbDm+xvQ8MwarXa23ZDaAK2oaqqp9NJkqR4PO44TrvdlmU5EokcDgee59PpdCaT6Xa7f70rn8+bpum6bjT6q/7HMRSfwT/tV33z74axADAWAMYCwFgAGAsAYwFgLACMBYCxADAWAMYCwFgAGAsAYwFgLACMBYCxADAWwAeEQLqnJKe0wQAAAABJRU5ErkJggg=="


class FakeS3Client:
    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}

    def put_object(self, Bucket: str, Key: str, Body: bytes) -> None:  # noqa: N803
        self.store[Key] = Body

    def get_object(self, Bucket: str, Key: str) -> dict:  # noqa: N803
        if Key not in self.store:
            raise KeyError(Key)
        return {"Body": BytesIO(self.store[Key])}

    def list_objects_v2(self, Bucket: str, Prefix: str) -> dict:  # noqa: N803
        keys = [k for k in self.store if k.startswith(Prefix)]
        return {"Contents": [{"Key": k} for k in keys]}


def test_ocr_cache_roundtrip(monkeypatch) -> None:
    METRICS.update({"hits": 0, "misses": 0, "time": 0.0})
    store = ObjectStore(client=FakeS3Client(), bucket="test")
    page_bytes = base64.b64decode(IMAGE_PNG_BASE64)

    monkeypatch.setattr(
        "worker.ocr_cache.run_ocr",
        lambda *_args, **_kwargs: {
            "text": "hello from cache",
            "md": None,
            "meta": {"confidence": 0.87},
            "ctx_compressed": None,
        },
    )

    text1, conf1 = ocr_cached(store, "doc1", page_bytes, langs="eng", dpi=300)
    assert text1 == "hello from cache"
    assert conf1 == pytest.approx(0.87)
    assert cache_hit_ratio() == 0.0

    text2, conf2 = ocr_cached(store, "doc1", page_bytes, langs="eng", dpi=300)
    assert text2 == text1
    assert conf2 == conf1
    assert cache_hit_ratio() == pytest.approx(0.5)
    assert ocr_time() > 0
    assert store.list("derived/doc1/ocr_cache")
