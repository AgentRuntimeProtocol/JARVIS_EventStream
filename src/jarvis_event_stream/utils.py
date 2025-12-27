from __future__ import annotations

import base64
import os
from datetime import datetime, timezone

from arp_standard_server import AuthSettings

DEFAULT_DEV_KEYCLOAK_ISSUER = "http://localhost:8080/realms/arp-dev"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def encode_cursor(seq: int) -> str:
    return base64.urlsafe_b64encode(str(seq).encode()).decode()


def decode_cursor(token: str) -> int:
    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        return int(raw)
    except Exception as exc:
        raise ValueError("Invalid cursor.") from exc


def _has_auth_env() -> bool:
    return any(key.startswith("ARP_AUTH_") for key in os.environ)


def auth_settings_from_env_or_dev_secure() -> AuthSettings:
    if _has_auth_env():
        return AuthSettings.from_env()
    return AuthSettings(mode="required", issuer=DEFAULT_DEV_KEYCLOAK_ISSUER)
