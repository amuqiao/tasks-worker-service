from __future__ import annotations

import argparse
import asyncio
import json
import sys

import httpx

from app.core.config import get_settings
from app.job_platform_worker.manifest import build_registry_from_manifest, load_worker_manifest, manifest_registration_payload, validate_manifest_runtime
from app.job_platform_worker.registry_client import JobServiceRegistryClient


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Worker manifest registration utility")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("validate", "render", "register"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--manifest")
    return parser


def _manifest_path(value: str | None) -> str:
    return value or get_settings().worker.manifest_path


def validate_manifest(path: str | None = None) -> None:
    settings = get_settings()
    manifest = load_worker_manifest(_manifest_path(path))
    validate_manifest_runtime(manifest, worker_service=settings.worker.service_name, queue_name=settings.taskiq.queue_name)
    build_registry_from_manifest(manifest)


def render_manifest(path: str | None = None) -> dict:
    settings = get_settings()
    manifest = load_worker_manifest(_manifest_path(path))
    validate_manifest_runtime(manifest, worker_service=settings.worker.service_name, queue_name=settings.taskiq.queue_name)
    build_registry_from_manifest(manifest)
    return manifest_registration_payload(manifest)


async def register_manifest(path: str | None = None) -> dict:
    settings = get_settings()
    payload = render_manifest(path)
    async with httpx.AsyncClient(timeout=settings.http_client.timeout_seconds) as http_client:
        client = JobServiceRegistryClient(
            http_client,
            base_url=settings.worker.job_service_base_url,
            worker_service=settings.worker.service_name,
            registry_api_key=settings.worker.job_service_registry_api_key_value,
        )
        return await client.register_worker_manifest(payload)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "validate":
        validate_manifest(args.manifest)
        print("OK worker-manifest")
        return 0
    if args.command == "render":
        print(json.dumps(render_manifest(args.manifest), sort_keys=True, indent=2))
        return 0
    if args.command == "register":
        print(json.dumps(asyncio.run(register_manifest(args.manifest)), sort_keys=True, indent=2))
        return 0
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
