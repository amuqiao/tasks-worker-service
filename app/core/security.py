from dataclasses import dataclass

from fastapi import Depends, Header

from app.core.config import AppSettings, get_settings
from app.core.exceptions import AppError


@dataclass(frozen=True)
class Principal:
    subject: str


def get_current_principal(
    authorization: str | None = Header(default=None, alias="Authorization"),
    settings: AppSettings = Depends(get_settings),
) -> Principal:
    if settings.security.disable_auth:
        return Principal(subject="dev")
    expected = f"Bearer {settings.security.service_api_key_value}"
    if authorization != expected:
        raise AppError("UNAUTHORIZED")
    return Principal(subject="service")

