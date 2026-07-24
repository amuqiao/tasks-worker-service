from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, unquote, urlsplit


@dataclass(frozen=True, slots=True)
class CanonicalObjectRef:
    provider: str
    bucket: str
    region: str
    key: str
    content_type: str
    content_hash: str


@dataclass(frozen=True, slots=True)
class AliyunOSSObjectLocation:
    bucket: str
    region: str
    key: str
    internal: bool

    @property
    def object_identity(self) -> tuple[str, str, str]:
        return self.bucket, self.region, self.key


def canonical_ref_from_oss_url_ref(
    payload: Mapping[str, Any],
    *,
    allowed_buckets: Collection[str] | None = None,
    allowed_regions: Collection[str] | None = None,
    allowed_content_types: Collection[str] | None = None,
    public_endpoint: str | None = None,
    public_endpoint_bucket: str | None = None,
    public_endpoint_region: str | None = None,
) -> CanonicalObjectRef:
    public_url = _required_str(payload, "public_url")
    internal_url = _required_str(payload, "internal_url")
    content_type = _required_str(payload, "content_type")
    digest = _required_bare_sha256(payload)

    normalized_public_endpoint = normalize_public_endpoint(public_endpoint)
    if normalized_public_endpoint and _url_host(public_url) == normalized_public_endpoint:
        key = _parse_public_endpoint_key(public_url, public_endpoint=normalized_public_endpoint)
        bucket = _required_setting("OSS bucket", public_endpoint_bucket)
        region = _required_setting("OSS region", public_endpoint_region)
        internal_location = parse_aliyun_oss_url(internal_url)
        if not internal_location.internal:
            raise ValueError("internal_url must use an internal OSS endpoint")
        if internal_location.object_identity != (bucket, region, key):
            raise ValueError("OSS URLs must reference the same object")
    else:
        location = parse_aliyun_oss_url(public_url)
        if location.internal:
            raise ValueError("public_url must use a public OSS endpoint")
        internal_location = parse_aliyun_oss_url(internal_url)
        if not internal_location.internal:
            raise ValueError("internal_url must use an internal OSS endpoint")
        if internal_location.object_identity != location.object_identity:
            raise ValueError("OSS URLs must reference the same object")
        bucket = location.bucket
        region = location.region
        key = location.key

    _validate_allowed("OSS bucket", bucket, allowed_buckets)
    _validate_allowed("OSS region", region, allowed_regions)
    _validate_allowed("content_type", content_type, allowed_content_types)
    return CanonicalObjectRef(
        provider="aliyun_oss",
        bucket=bucket,
        region=region,
        key=key,
        content_type=content_type,
        content_hash=f"sha256:{digest}",
    )


def oss_url_ref_from_output_object(
    *,
    bucket: str,
    region: str,
    key: str,
    content_type: str,
    content_hash: str,
    public_endpoint: str | None = None,
) -> dict[str, str]:
    normalized_public_endpoint = normalize_public_endpoint(public_endpoint)
    encoded_key = quote(key.lstrip("/"), safe="/")
    public_host = normalized_public_endpoint or f"{bucket}.oss-{region}.aliyuncs.com"
    return {
        "public_url": f"https://{public_host}/{encoded_key}",
        "internal_url": f"https://{bucket}.oss-{region}-internal.aliyuncs.com/{encoded_key}",
        "content_type": content_type,
        "sha256": bare_sha256(content_hash),
    }


def parse_aliyun_oss_url(url: str) -> AliyunOSSObjectLocation:
    parsed = urlsplit(url.strip())
    if parsed.scheme != "https":
        raise ValueError("OSS URL must use https")
    if parsed.query or parsed.fragment:
        raise ValueError("OSS URL must not contain query string or fragment")
    if parsed.username or parsed.password or parsed.port is not None:
        raise ValueError("OSS URL must not contain credentials or port")
    host = (parsed.hostname or "").lower()
    suffix = ".aliyuncs.com"
    marker = ".oss-"
    if not host.endswith(suffix) or marker not in host:
        raise ValueError("OSS URL host is not an Aliyun OSS virtual-host endpoint")
    bucket, endpoint_part = host.split(marker, 1)
    if not bucket or not endpoint_part.endswith(suffix.removeprefix(".")):
        raise ValueError("OSS URL host is invalid")
    region = endpoint_part.removesuffix(suffix.removeprefix(".")).rstrip(".")
    internal = False
    if region.endswith("-internal"):
        internal = True
        region = region.removesuffix("-internal")
    if not region:
        raise ValueError("OSS URL region is missing")
    key = unquote(parsed.path.lstrip("/"))
    if not key:
        raise ValueError("OSS URL object key is missing")
    if any(part == ".." for part in key.split("/")):
        raise ValueError("OSS URL object key contains illegal path traversal")
    return AliyunOSSObjectLocation(bucket=bucket, region=region, key=key, internal=internal)


def normalize_public_endpoint(value: str | None) -> str:
    return (value or "").strip().removeprefix("https://").removeprefix("http://").strip("/").lower()


def bare_sha256(value: str) -> str:
    digest = value.strip().removeprefix("sha256:")
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ValueError("sha256 must be 64 lowercase hex characters")
    return digest


def _parse_public_endpoint_key(url: str, *, public_endpoint: str) -> str:
    parsed = urlsplit(url.strip())
    if parsed.scheme != "https":
        raise ValueError("OSS URL must use https")
    if parsed.fragment:
        raise ValueError("OSS URL must not contain fragment")
    if parsed.username or parsed.password or parsed.port is not None:
        raise ValueError("OSS URL must not contain credentials or port")
    if (parsed.hostname or "").lower() != public_endpoint:
        raise ValueError("public_url host does not match OSS public endpoint")
    key = unquote(parsed.path.lstrip("/"))
    if not key:
        raise ValueError("OSS URL object key is missing")
    if any(part == ".." for part in key.split("/")):
        raise ValueError("OSS URL object key contains illegal path traversal")
    return key


def _required_setting(label: str, value: str | None) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} is required for public endpoint refs")
    return value.strip()


def _url_host(url: str) -> str:
    parsed = urlsplit(url.strip())
    if parsed.username or parsed.password or parsed.port is not None:
        raise ValueError("OSS URL must not contain credentials or port")
    return (parsed.hostname or "").lower()


def _required_str(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} is required")
    return value.strip()


def _required_bare_sha256(payload: Mapping[str, Any]) -> str:
    value = _required_str(payload, "sha256")
    if value.startswith("sha256:"):
        raise ValueError("sha256 must be 64 lowercase hex characters")
    return bare_sha256(value)


def _validate_allowed(label: str, value: str, allowed: Collection[str] | None) -> None:
    if allowed is not None and value not in set(allowed):
        raise ValueError(f"{label} is not allowed")
