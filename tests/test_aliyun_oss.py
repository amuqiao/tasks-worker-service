from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

from app.integrations.aliyun_oss import AliyunOSSClient, AliyunOSSConfig, normalize_object_key


def test_normalize_object_key_is_project_root_idempotent() -> None:
    assert normalize_object_key("project/root", "input.wav") == "project/root/input.wav"
    assert normalize_object_key("project/root", "project/root/input.wav") == "project/root/input.wav"


def test_aliyun_oss_client_builds_supported_request_urls() -> None:
    base = {
        "bucket": "bucket-a",
        "region": "cn-test",
        "access_key_id": "ak",
        "access_key_secret": "sk",
        "endpoint": "oss-cn-test.aliyuncs.com",
    }

    assert (
        AliyunOSSClient(AliyunOSSConfig(**base, endpoint_style="virtual_host"))._request_url("a/b.wav")
        == "https://bucket-a.oss-cn-test.aliyuncs.com/a/b.wav"
    )
    assert (
        AliyunOSSClient(AliyunOSSConfig(**base, endpoint_style="path"))._request_url("a/b.wav")
        == "https://oss-cn-test.aliyuncs.com/bucket-a/a/b.wav"
    )


def test_aliyun_oss_client_signed_get_url_contains_required_query() -> None:
    client = AliyunOSSClient(
        AliyunOSSConfig(
            bucket="bucket-a",
            region="cn-test",
            access_key_id="ak",
            access_key_secret="sk",
            endpoint="oss-cn-test.aliyuncs.com",
        )
    )

    signed = client.signed_get_url("a/b.wav", expires_seconds=60)
    parsed = urlsplit(signed)
    query = parse_qs(parsed.query)

    assert parsed.netloc == "bucket-a.oss-cn-test.aliyuncs.com"
    assert query["OSSAccessKeyId"] == ["ak"]
    assert "Expires" in query
    assert "Signature" in query
