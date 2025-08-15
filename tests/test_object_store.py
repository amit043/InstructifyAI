from urllib.parse import parse_qs, urlparse

import boto3
from moto import mock_aws

from storage.object_store import ObjectStore


@mock_aws
def test_roundtrip_and_presign() -> None:
    client = boto3.client("s3", region_name="us-east-1")
    client.create_bucket(Bucket="test-bucket")
    store = ObjectStore(client=client, bucket="test-bucket")
    store.put_bytes("raw/doc1.txt", b"hello")
    assert store.get_bytes("raw/doc1.txt") == b"hello"
    assert store.list("raw") == ["raw/doc1.txt"]
    url = store.presign_get("raw/doc1.txt", expiry=60)
    qs = parse_qs(urlparse(url).query)
    assert qs["X-Amz-Expires"] == ["60"]
