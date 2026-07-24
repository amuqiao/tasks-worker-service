from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Protocol

from fastapi import FastAPI

from app.core.config import AppSettings
from app.core.lifecycle import HealthCheck, HealthCheckResult
from app.integrations.aliyun_oss import AliyunOSSClient, AliyunOSSConfig, AliyunOSSError


class ObjectStorage(Protocol):
    async def put(
        self,
        bucket: str,
        key: str,
        content: bytes,
        *,
        content_type: str = "application/octet-stream",
    ) -> None:
        ...

    async def get(self, bucket: str, key: str) -> bytes:
        ...

    async def delete(self, bucket: str, key: str) -> None:
        ...

    async def close(self) -> None:
        ...


class DisabledObjectStorage:
    async def put(
        self,
        bucket: str,
        key: str,
        content: bytes,
        *,
        content_type: str = "application/octet-stream",
    ) -> None:
        raise RuntimeError("object storage is disabled")

    async def get(self, bucket: str, key: str) -> bytes:
        raise RuntimeError("object storage is disabled")

    async def delete(self, bucket: str, key: str) -> None:
        raise RuntimeError("object storage is disabled")

    async def close(self) -> None:
        return None


class LocalObjectStorage:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, bucket: str, key: str) -> Path:
        path = (self.root / bucket / key).resolve()
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("storage key escapes storage root") from exc
        if path == self.root:
            raise ValueError("storage key escapes storage root")
        return path

    async def put(
        self,
        bucket: str,
        key: str,
        content: bytes,
        *,
        content_type: str = "application/octet-stream",
    ) -> None:
        path = self._path(bucket, key)
        await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_bytes, content)

    async def get(self, bucket: str, key: str) -> bytes:
        return await asyncio.to_thread(self._path(bucket, key).read_bytes)

    async def delete(self, bucket: str, key: str) -> None:
        await asyncio.to_thread(self._path(bucket, key).unlink, missing_ok=True)

    async def close(self) -> None:
        return None


class AliyunObjectStorage:
    def __init__(self, config: AliyunOSSConfig) -> None:
        self.config = config

    def _assert_target(self, *, bucket: str) -> None:
        if bucket != self.config.bucket:
            raise RuntimeError("OSS bucket does not match configured Aliyun OSS bucket")

    async def put(
        self,
        bucket: str,
        key: str,
        content: bytes,
        *,
        content_type: str = "application/octet-stream",
    ) -> None:
        self._assert_target(bucket=bucket)
        await asyncio.to_thread(AliyunOSSClient(self.config).put_object, key, content, content_type=content_type)

    async def get(self, bucket: str, key: str) -> bytes:
        self._assert_target(bucket=bucket)
        try:
            return await asyncio.to_thread(AliyunOSSClient(self.config).get_object, key)
        except AliyunOSSError as exc:
            raise RuntimeError("failed to read Aliyun OSS object") from exc

    async def delete(self, bucket: str, key: str) -> None:
        self._assert_target(bucket=bucket)
        try:
            await asyncio.to_thread(AliyunOSSClient(self.config).delete_object, key)
        except AliyunOSSError as exc:
            raise RuntimeError("failed to delete Aliyun OSS object") from exc

    async def close(self) -> None:
        return None


def build_object_storage(settings: AppSettings) -> ObjectStorage:
    if settings.storage.backend == "disabled":
        return DisabledObjectStorage()
    if settings.storage.backend == "local":
        return LocalObjectStorage(Path(settings.storage.local_path))
    if settings.storage.backend == "aliyun_oss":
        return AliyunObjectStorage(
            AliyunOSSConfig(
                bucket=settings.storage.bucket,
                region=settings.storage.region,
                access_key_id=settings.storage.access_key_id,
                access_key_secret=settings.storage.access_key_secret.get_secret_value(),
                project_root=settings.storage.project_root,
                endpoint=settings.storage.endpoint,
                endpoint_style=settings.storage.endpoint_style,
                scheme=settings.storage.scheme,
            )
        )
    raise RuntimeError("s3_compatible storage adapter is not implemented")


class ObjectStorageProvider:
    name = "object_storage"
    required = False

    async def startup(self, app: FastAPI, settings: AppSettings) -> ObjectStorage:
        storage = build_object_storage(settings)
        app.state.object_storage = storage
        return storage

    async def shutdown(self, app: FastAPI, resource: ObjectStorage) -> None:
        await resource.close()
        if hasattr(app.state, "object_storage"):
            delattr(app.state, "object_storage")

    def health_check(self, resource: ObjectStorage) -> HealthCheck | None:
        async def check() -> HealthCheckResult:
            return HealthCheckResult("object_storage", "ok", {"backend": type(resource).__name__})

        return HealthCheck(name="object_storage", check=check, required=self.required)


def get_storage(app: FastAPI) -> ObjectStorage:
    return app.state.object_storage
