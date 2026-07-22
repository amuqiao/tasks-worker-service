from dataclasses import dataclass

from fastapi import Header, Request

from app.core.exceptions import AppError


@dataclass(frozen=True)
class Principal:
    subject: str


def get_current_principal(
    request: Request,
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> Principal:
    settings = request.app.state.settings
    if settings.security.disable_auth:
        return Principal(subject="dev")
    expected = f"Bearer {settings.security.service_api_key_value}"
    if authorization != expected:
        raise AppError("UNAUTHORIZED")
    return Principal(subject="service")
