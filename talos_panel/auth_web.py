import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select, text

from talos_panel.auth import (
    DUMMY_HASH,
    client_ip,
    create_session,
    hash_password,
    record_audit,
    require_admin,
    require_csrf,
    require_same_origin,
    require_user,
    set_session_cookie,
    verify_password,
)
from talos_panel.config import get_settings
from talos_panel.db import SessionFactory
from talos_panel.i18n import language_from_request, template_context, translate
from talos_panel.models import AuditEvent, User, UserRole, UserSession

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory="talos_panel/templates", context_processors=[template_context])


def ui_message(request: Request, text: str) -> str:
    return translate(text, language_from_request(request))


def normalized_email(email: str) -> str:
    value = email.strip().lower()
    if not value or len(value) > 320 or "@" not in value:
        raise HTTPException(status_code=422, detail="Enter a valid email address")
    return value


@router.get("/setup", response_class=HTMLResponse)
async def setup_page(request: Request):
    async with SessionFactory() as database:
        if await database.scalar(select(func.count(User.id))):
            return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(request, "setup.html", {})


@router.post("/setup")
async def setup_admin(request: Request, email: str = Form(), password: str = Form()):
    require_same_origin(request)
    try:
        password_hash = hash_password(password)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    async with SessionFactory() as database:
        await database.execute(text("SELECT pg_advisory_xact_lock(1412568147)"))
        if await database.scalar(select(func.count(User.id))):
            raise HTTPException(status_code=409, detail="Initial administrator already exists")
        user = User(
            email=normalized_email(email),
            password_hash=password_hash,
            role=UserRole.ADMIN,
            is_active=True,
        )
        database.add(user)
        await database.commit()
        await database.refresh(user)
    raw_token, _ = await create_session(request, user, get_settings())
    response = RedirectResponse("/", status_code=303)
    set_session_cookie(response, raw_token, get_settings())
    return response


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if request.state.user:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/login")
async def login(request: Request, email: str = Form(), password: str = Form()):
    require_same_origin(request)
    async with SessionFactory() as database:
        recent_failures = await database.scalar(
            select(func.count(AuditEvent.id)).where(
                AuditEvent.action == "auth.login_failed",
                AuditEvent.ip_address == client_ip(request),
                AuditEvent.created_at >= datetime.now(UTC) - timedelta(minutes=15),
            )
        )
        if recent_failures and recent_failures >= 5:
            raise HTTPException(status_code=429, detail="Too many login attempts; try again later")
        user = await database.scalar(select(User).where(User.email == email.strip().lower()))
        valid = verify_password(user.password_hash if user else DUMMY_HASH, password)
        if not user or not valid or not user.is_active:
            database.add(
                AuditEvent(action="auth.login_failed", ip_address=client_ip(request), details=email[:320])
            )
            await database.commit()
            return templates.TemplateResponse(
                request,
                "login.html",
                {"error": ui_message(request, "Invalid email or password")},
                status_code=401,
            )
    raw_token, _ = await create_session(request, user, get_settings())
    response = RedirectResponse("/", status_code=303)
    set_session_cookie(response, raw_token, get_settings())
    return response


@router.post("/logout")
async def logout(request: Request, csrf_token: str = Form()):
    require_csrf(request, csrf_token)
    auth_session = request.state.auth_session
    async with SessionFactory() as database:
        session = await database.get(UserSession, auth_session.id)
        if session:
            session.revoked_at = datetime.now(UTC)
            await database.commit()
    await record_audit(request, "auth.logout")
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(get_settings().session_cookie_name, path="/")
    return response


@router.get("/account", response_class=HTMLResponse)
async def account_page(request: Request):
    require_user(request)
    return templates.TemplateResponse(request, "account.html", {"message": None})


@router.post("/account/password", response_class=HTMLResponse)
async def change_password(
    request: Request,
    current_password: str = Form(),
    new_password: str = Form(),
    csrf_token: str = Form(),
):
    user = require_user(request)
    require_csrf(request, csrf_token)
    async with SessionFactory() as database:
        stored = await database.get(User, user.id)
        if stored is None or not verify_password(stored.password_hash, current_password):
            return templates.TemplateResponse(
                request,
                "account.html",
                {"message": ui_message(request, "Current password is incorrect"), "error": True},
                status_code=400,
            )
        try:
            stored.password_hash = hash_password(new_password)
        except ValueError as exc:
            return templates.TemplateResponse(
                request,
                "account.html",
                {"message": str(exc), "error": True},
                status_code=422,
            )
        sessions = list(
            await database.scalars(
                select(UserSession).where(
                    UserSession.user_id == user.id,
                    UserSession.id != request.state.auth_session.id,
                    UserSession.revoked_at.is_(None),
                )
            )
        )
        now = datetime.now(UTC)
        for session in sessions:
            session.revoked_at = now
        await database.commit()
    await record_audit(request, "auth.password_change")
    return templates.TemplateResponse(
        request,
        "account.html",
        {"message": ui_message(request, "Password changed"), "error": False},
    )


@router.get("/admin/users", response_class=HTMLResponse)
async def users_page(request: Request):
    require_admin(request)
    async with SessionFactory() as database:
        users = list(await database.scalars(select(User).order_by(User.created_at)))
        events = list(
            await database.scalars(select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(50))
        )
    return templates.TemplateResponse(request, "users.html", {"users": users, "events": events})


@router.post("/admin/users")
async def create_user(
    request: Request,
    email: str = Form(),
    password: str = Form(),
    role: UserRole = Form(UserRole.USER),
    csrf_token: str = Form(),
):
    require_admin(request)
    require_csrf(request, csrf_token)
    try:
        password_hash = hash_password(password)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    async with SessionFactory() as database:
        if await database.scalar(select(User.id).where(User.email == normalized_email(email))):
            raise HTTPException(status_code=409, detail="A user with this email already exists")
        user = User(email=normalized_email(email), password_hash=password_hash, role=role)
        database.add(user)
        await database.commit()
    await record_audit(request, "user.create", details=f"{user.email}:{user.role.value}")
    return RedirectResponse("/admin/users", status_code=303)


@router.post("/admin/users/{user_id}/sessions/revoke")
async def revoke_user_sessions(
    request: Request, user_id: uuid.UUID, csrf_token: str = Form()
):
    require_admin(request)
    require_csrf(request, csrf_token)
    async with SessionFactory() as database:
        sessions = list(
            await database.scalars(
                select(UserSession).where(
                    UserSession.user_id == user_id, UserSession.revoked_at.is_(None)
                )
            )
        )
        now = datetime.now(UTC)
        for session in sessions:
            session.revoked_at = now
        await database.commit()
    await record_audit(request, "user.sessions_revoke", details=str(user_id))
    return RedirectResponse("/admin/users", status_code=303)
