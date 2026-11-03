import hmac
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..dependencies import AuthContext, get_auth_context, require_csrf
from ..models import SessionRecord, User
from ..rate_limit import limiter
from ..schemas import BootstrapRequest, BootstrapStatus, LoginRequest, UserOut
from ..security import (
    clear_auth_cookies,
    create_session,
    hash_password,
    set_auth_cookies,
    verify_password,
)
from ..services.audit import audit

router = APIRouter(prefix="/api/auth", tags=["authentication"])
settings = get_settings()
DUMMY_HASH = hash_password("invalid-password-timing")


def establish_session(db: Session, response: Response, user: User) -> None:
    db.flush()  # Materialize ORM defaults before signing the user/session IDs.
    session, token, csrf = create_session(user)
    db.add(session)
    db.commit()
    set_auth_cookies(response, token, csrf)


@router.get("/bootstrap-status", response_model=BootstrapStatus)
@limiter.limit("30/minute")
def bootstrap_status(request: Request, db: Session = Depends(get_db)) -> BootstrapStatus:
    count = db.scalar(select(func.count()).select_from(User)) or 0
    return BootstrapStatus(required=count == 0, token_required=bool(settings.bootstrap_token))


@router.post("/bootstrap", response_model=UserOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("3/minute")
def bootstrap(
    payload: BootstrapRequest, request: Request, response: Response, db: Session = Depends(get_db)
) -> User:
    count = db.scalar(select(func.count()).select_from(User)) or 0
    if count:
        raise HTTPException(status.HTTP_409_CONFLICT, "Initial setup is already complete")
    if settings.bootstrap_token and not hmac.compare_digest(
        payload.bootstrap_token, settings.bootstrap_token
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid bootstrap token")
    user = User(username=payload.username, password_hash=hash_password(payload.password), role="admin")
    db.add(user)
    audit(db, request, user.username, "initial_admin_created")
    establish_session(db, response, user)
    return user


@router.post("/login", response_model=UserOut)
@limiter.limit("5/minute")
def login(
    payload: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)
) -> User:
    user = db.scalar(select(User).where(User.username == payload.username))
    valid, needs_rehash = verify_password(user.password_hash if user else DUMMY_HASH, payload.password)
    if not user or not valid or not user.active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")
    if needs_rehash:
        user.password_hash = hash_password(payload.password)
    db.query(SessionRecord).filter(SessionRecord.expires_at < datetime.now(timezone.utc)).delete(
        synchronize_session=False
    )
    establish_session(db, response, user)
    audit(db, request, user.username, "login_succeeded")
    db.commit()
    return user


@router.get("/session", response_model=UserOut | None)
def session_status(request: Request, db: Session = Depends(get_db)) -> User | None:
    """A non-error probe avoids console noise for normal logged-out visits."""
    try:
        return get_auth_context(request, db).user
    except HTTPException:
        return None


@router.get("/me", response_model=UserOut)
def me(context: AuthContext = Depends(get_auth_context)) -> User:
    return context.user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("30/minute")
def logout(
    request: Request,
    response: Response,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> Response:
    context.session.revoked_at = datetime.now(timezone.utc)
    audit(db, request, context.user.username, "logout")
    db.commit()
    clear_auth_cookies(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response
