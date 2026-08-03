import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import HTTPException, Request, WebSocket
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import func, select

from talos_panel.config import Settings
from talos_panel.db import SessionFactory
from talos_panel.models import AuditEvent, User, UserRole, UserSession

password_hasher = PasswordHasher()
DUMMY_HASH = password_hasher.hash("talos-panel-dummy-password")


def hash_password(password: str) -> str:
    if len(password) < 12 or len(password) > 256:
        raise ValueError("Password must contain between 12 and 256 characters")
    return password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def client_ip(connection: Request | WebSocket) -> str | None:
    return connection.client.host if connection.client else None


async def create_session(request: Request, user: User, settings: Settings) -> tuple[str, UserSession]:
    now = datetime.now(UTC)
    raw_token = secrets.token_urlsafe(32)
    session = UserSession(
        user_id=user.id,
        token_hash=token_hash(raw_token),
        csrf_secret=secrets.token_urlsafe(32),
        last_seen_at=now,
        expires_at=now + timedelta(hours=settings.session_absolute_hours),
        user_agent=(request.headers.get("user-agent") or "")[:255] or None,
        ip_address=client_ip(request),
    )
    async with SessionFactory() as database:
        database.add(session)
        database.add(
            AuditEvent(
                user_id=user.id,
                action="auth.login",
                ip_address=client_ip(request),
            )
        )
        await database.commit()
    return raw_token, session


def set_session_cookie(response, raw_token: str, settings: Settings) -> None:
    response.set_cookie(
        settings.session_cookie_name,
        raw_token,
        max_age=settings.session_absolute_hours * 3600,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        path="/",
    )


async def load_identity(connection: Request | WebSocket, settings: Settings):
    raw_token = connection.cookies.get(settings.session_cookie_name)
    if not raw_token:
        return None, None
    now = datetime.now(UTC)
    async with SessionFactory() as database:
        session = await database.scalar(
            select(UserSession).where(UserSession.token_hash == token_hash(raw_token))
        )
        if session is None or session.revoked_at is not None or session.expires_at <= now:
            return None, None
        if session.last_seen_at + timedelta(minutes=settings.session_idle_minutes) <= now:
            session.revoked_at = now
            await database.commit()
            return None, None
        user = await database.get(User, session.user_id)
        if user is None or not user.is_active:
            return None, None
        if session.last_seen_at + timedelta(minutes=1) <= now:
            session.last_seen_at = now
            await database.commit()
        database.expunge(user)
        database.expunge(session)
        return user, session


def require_csrf(request: Request, supplied: str | None) -> None:
    session = getattr(request.state, "auth_session", None)
    if session is None or not supplied or not hmac.compare_digest(session.csrf_secret, supplied):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")


def require_same_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") not in {
        f"http://{request.headers.get('host')}",
        f"https://{request.headers.get('host')}",
    }:
        raise HTTPException(status_code=403, detail="Invalid request origin")


def require_user(request: Request) -> User:
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def require_admin(request: Request) -> User:
    user = require_user(request)
    if user.role is not UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Administrator access required")
    return user


def content_security_policy(path: str) -> str:
    policy = (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; connect-src 'self' ws: wss:; "
        "img-src 'self' data:"
    )
    if path.startswith("/docs") or path == "/redoc":
        policy = (
            "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "connect-src 'self'; img-src 'self' data: https://fastapi.tiangolo.com"
        )
    return policy


async def record_audit(
    request: Request,
    action: str,
    *,
    server_id=None,
    details: str | None = None,
) -> None:
    user = require_user(request)
    async with SessionFactory() as database:
        database.add(
            AuditEvent(
                user_id=user.id,
                action=action,
                server_id=server_id,
                ip_address=client_ip(request),
                details=details,
            )
        )
        await database.commit()


class AuthenticationMiddleware:
    def __init__(self, app, settings: Settings) -> None:
        self.app = app
        self.settings = settings

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope, receive=receive)
        user, session = await load_identity(request, self.settings)
        scope.setdefault("state", {})["user"] = user
        scope["state"]["auth_session"] = session
        scope["state"]["csrf_token"] = session.csrf_secret if session else None
        path = scope["path"]
        public = path == "/health" or path.startswith(("/static/", "/language/")) or path in {"/login", "/setup"}
        async with SessionFactory() as database:
            has_users = bool(await database.scalar(select(func.count(User.id))))
        if not has_users and path != "/setup" and path != "/health" and not path.startswith(("/static/", "/language/")):
            response = JSONResponse({"detail": "Initial administrator setup required"}, status_code=503) if path.startswith("/api/") else RedirectResponse("/setup", status_code=303)
            await response(scope, receive, send)
            return
        if has_users and not public and user is None:
            response = JSONResponse({"detail": "Authentication required"}, status_code=401) if path.startswith("/api/") else RedirectResponse("/login", status_code=303)
            response.delete_cookie(self.settings.session_cookie_name, path="/")
            await response(scope, receive, send)
            return
        async def secure_send(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(
                    [
                        (b"x-content-type-options", b"nosniff"),
                        (b"referrer-policy", b"same-origin"),
                        (b"x-frame-options", b"DENY"),
                        (b"content-security-policy", content_security_policy(path).encode()),
                    ]
                )
                if self.settings.secure_cookies:
                    headers.append((b"strict-transport-security", b"max-age=31536000"))
                message["headers"] = headers
            await send(message)
        await self.app(scope, receive, secure_send)
