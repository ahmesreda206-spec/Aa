from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from .config import get_settings
from .database import get_db
from .models import SessionRecord, User
from .security import csrf_matches, decode_token

settings = get_settings()


@dataclass
class AuthContext:
    user: User
    session: SessionRecord


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def get_auth_context(request: Request, db: Session = Depends(get_db)) -> AuthContext:
    token = request.cookies.get(settings.session_cookie, "")
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required")
    try:
        claims = decode_token(token)
        session = db.get(SessionRecord, claims["sid"])
        if (
            session is None
            or session.revoked_at is not None
            or as_utc(session.expires_at) <= datetime.now(timezone.utc)
            or session.user_id != claims["sub"]
            or not session.user.active
        ):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired")
        return AuthContext(user=session.user, session=session)
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid session") from None


def require_csrf(
    request: Request, context: AuthContext = Depends(get_auth_context)
) -> AuthContext:
    cookie_value = request.cookies.get(settings.csrf_cookie, "")
    header_value = request.headers.get("X-CSRF-Token", "")
    if not csrf_matches(context.session, cookie_value, header_value):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "CSRF validation failed")
    return context


def require_admin(context: AuthContext = Depends(require_csrf)) -> AuthContext:
    if context.user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator access required")
    return context
