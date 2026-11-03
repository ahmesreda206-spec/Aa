from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError
from fastapi import Response

from .config import get_settings
from .models import SessionRecord, User

settings = get_settings()
password_hasher = PasswordHasher(time_cost=3, memory_cost=65_536, parallelism=4)


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> tuple[bool, bool]:
    try:
        valid = password_hasher.verify(password_hash, password)
        return valid, password_hasher.check_needs_rehash(password_hash)
    except (VerifyMismatchError, VerificationError):
        return False, False


def create_session(user: User) -> tuple[SessionRecord, str, str]:
    session = SessionRecord(
        id=str(uuid.uuid4()),
        user=user,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=settings.session_minutes),
    )
    csrf = secrets.token_urlsafe(32)
    session.csrf_hash = hashlib.sha256(csrf.encode()).hexdigest()
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "sub": user.id,
            "sid": session.id,
            "iat": now,
            "nbf": now,
            "exp": session.expires_at,
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "jti": str(uuid.uuid4()),
        },
        settings.secret_key,
        algorithm="HS256",
    )
    return session, token, csrf


def decode_token(token: str) -> dict:
    return jwt.decode(
        token,
        settings.secret_key,
        algorithms=["HS256"],
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
        options={"require": ["sub", "sid", "exp", "iat"]},
    )


def set_auth_cookies(response: Response, token: str, csrf: str) -> None:
    common = {
        "secure": settings.cookie_secure,
        "samesite": "strict",
        "path": "/",
        "max_age": settings.session_minutes * 60,
    }
    response.set_cookie(settings.session_cookie, token, httponly=True, **common)
    response.set_cookie(settings.csrf_cookie, csrf, httponly=False, **common)


def clear_auth_cookies(response: Response) -> None:
    common = {"secure": settings.cookie_secure, "samesite": "strict", "path": "/"}
    response.delete_cookie(settings.session_cookie, httponly=True, **common)
    response.delete_cookie(settings.csrf_cookie, httponly=False, **common)


def csrf_matches(session: SessionRecord, cookie_value: str, header_value: str) -> bool:
    if not cookie_value or not header_value:
        return False
    if not hmac.compare_digest(cookie_value, header_value):
        return False
    return hmac.compare_digest(session.csrf_hash, hashlib.sha256(header_value.encode()).hexdigest())


def new_device_credentials() -> tuple[str, str]:
    device_id = f"qf-{secrets.token_hex(6)}"
    token = f"{device_id}.{secrets.token_urlsafe(32)}"
    return device_id, token


def hash_device_token(token: str) -> str:
    return hmac.new(settings.secret_key.encode(), token.encode(), hashlib.sha256).hexdigest()


def device_token_matches(token: str, expected_hash: str) -> bool:
    return hmac.compare_digest(hash_device_token(token), expected_hash)
