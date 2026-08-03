import asyncio
import uuid
from datetime import UTC, date, datetime, time, timedelta
from urllib.parse import urlencode

import pyotp
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, func, select, text

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
from talos_panel.models import (
    AuditEvent,
    MinecraftServer,
    ServerMember,
    User,
    UserRole,
    UserSession,
)
from talos_panel.security_service import security_findings

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
async def login(
    request: Request,
    email: str = Form(),
    password: str = Form(),
    totp_code: str = Form("", max_length=8),
):
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
        totp_valid = bool(
            user
            and (
                not user.totp_enabled
                or (
                    user.totp_secret
                    and pyotp.TOTP(user.totp_secret).verify(totp_code.strip(), valid_window=1)
                )
            )
        )
        if not user or not valid or not user.is_active or not totp_valid:
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
    user = require_user(request)
    async with SessionFactory() as database:
        stored = await database.get(User, user.id)
        if stored is None:
            raise HTTPException(status_code=404, detail="User not found")
        if not stored.totp_secret:
            stored.totp_secret = pyotp.random_base32()
            await database.commit()
        sessions = list(
            await database.scalars(
                select(UserSession)
                .where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
                .order_by(UserSession.last_seen_at.desc())
            )
        )
        provisioning_uri = pyotp.TOTP(stored.totp_secret).provisioning_uri(
            name=stored.email, issuer_name="Talos Panel"
        )
        enabled = stored.totp_enabled
        secret = stored.totp_secret
    return templates.TemplateResponse(
        request,
        "account.html",
        {
            "message": None,
            "sessions": sessions,
            "totp_enabled": enabled,
            "totp_secret": secret,
            "totp_uri": provisioning_uri,
        },
    )


@router.post("/account/2fa")
async def update_two_factor(
    request: Request,
    action: str = Form(pattern=r"^(enable|disable)$"),
    totp_code: str = Form(min_length=6, max_length=8),
    csrf_token: str = Form(),
):
    user = require_user(request)
    require_csrf(request, csrf_token)
    async with SessionFactory() as database:
        stored = await database.get(User, user.id)
        if stored is None or not stored.totp_secret:
            raise HTTPException(status_code=409, detail="Two-factor setup is not ready")
        if not pyotp.TOTP(stored.totp_secret).verify(totp_code.strip(), valid_window=1):
            raise HTTPException(status_code=422, detail="Invalid authentication code")
        stored.totp_enabled = action == "enable"
        if action == "disable":
            stored.totp_secret = pyotp.random_base32()
        await database.commit()
    await record_audit(request, f"auth.2fa_{action}")
    return RedirectResponse("/account", status_code=303)


@router.post("/account/sessions/{session_id}/revoke")
async def revoke_own_session(
    request: Request, session_id: uuid.UUID, csrf_token: str = Form()
):
    user = require_user(request)
    require_csrf(request, csrf_token)
    if session_id == request.state.auth_session.id:
        raise HTTPException(status_code=409, detail="Use log out to close the current session")
    async with SessionFactory() as database:
        session = await database.scalar(
            select(UserSession).where(
                UserSession.id == session_id,
                UserSession.user_id == user.id,
                UserSession.revoked_at.is_(None),
            )
        )
        if session:
            session.revoked_at = datetime.now(UTC)
            await database.commit()
    await record_audit(request, "auth.session_revoke", details=str(session_id))
    return RedirectResponse("/account", status_code=303)


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
            raise HTTPException(status_code=400, detail="Current password is incorrect")
        try:
            stored.password_hash = hash_password(new_password)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
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
    return RedirectResponse("/account", status_code=303)


@router.get("/admin/users", response_class=HTMLResponse)
async def users_page(request: Request):
    current_user = require_admin(request)
    async with SessionFactory() as database:
        users = list(await database.scalars(select(User).order_by(User.created_at)))
        access_by_user: dict[uuid.UUID, list[tuple[MinecraftServer, ServerMember]]] = {
            user.id: [] for user in users
        }
        access_rows = (
            await database.execute(
                select(MinecraftServer, ServerMember)
                .join(ServerMember, ServerMember.server_id == MinecraftServer.id)
                .order_by(MinecraftServer.name)
            )
        ).all()
        for server, membership in access_rows:
            access_by_user.setdefault(membership.user_id, []).append((server, membership))
    return templates.TemplateResponse(
        request,
        "users.html",
        {
            "users": users,
            "access_by_user": access_by_user,
            "current_user_id": current_user.id,
            "message": request.query_params.get("message"),
        },
    )


@router.get("/admin/security", response_class=HTMLResponse)
async def security_review_page(request: Request):
    require_admin(request)
    findings = await asyncio.to_thread(
        security_findings, get_settings(), request.app.state.runtime
    )
    now = datetime.now(UTC)
    async with SessionFactory() as database:
        active_admins = int(
            await database.scalar(
                select(func.count(User.id)).where(
                    User.role == UserRole.ADMIN, User.is_active.is_(True)
                )
            )
            or 0
        )
        admins_with_2fa = int(
            await database.scalar(
                select(func.count(User.id)).where(
                    User.role == UserRole.ADMIN,
                    User.is_active.is_(True),
                    User.totp_enabled.is_(True),
                )
            )
            or 0
        )
        active_sessions = int(
            await database.scalar(
                select(func.count(UserSession.id)).where(
                    UserSession.revoked_at.is_(None), UserSession.expires_at > now
                )
            )
            or 0
        )
        failed_logins = int(
            await database.scalar(
                select(func.count(AuditEvent.id)).where(
                    AuditEvent.action == "auth.login_failed",
                    AuditEvent.created_at >= now - timedelta(hours=24),
                )
            )
            or 0
        )
        server_count = int(await database.scalar(select(func.count(MinecraftServer.id))) or 0)
    if admins_with_2fa < active_admins:
        missing_2fa = active_admins - admins_with_2fa
        findings.insert(
            0,
            {
                "severity": "warning",
                "title": "Administrator accounts without 2FA",
                "detail": ui_message(
                    request,
                    "{count} active administrator account(s) do not use two-factor authentication.",
                ).format(count=missing_2fa),
            },
        )
    if active_admins == 1:
        findings.append(
            {
                "severity": "info",
                "title": "Single administrator account",
                "detail": "Consider a second protected administrator account for account recovery.",
            }
        )
    return templates.TemplateResponse(
        request,
        "security_review.html",
        {
            "security_findings": findings,
            "security_summary": {
                "active_admins": active_admins,
                "admins_with_2fa": admins_with_2fa,
                "active_sessions": active_sessions,
                "failed_logins": failed_logins,
                "servers": server_count,
            },
        },
    )


@router.get("/admin/audit", response_class=HTMLResponse)
async def audit_logs_page(
    request: Request,
    audit_action: str = "",
    audit_user: str = "",
    audit_server: str = "",
    audit_ip: str = "",
    audit_details: str = "",
    date_from: str = "",
    date_to: str = "",
    page: int = 1,
):
    require_admin(request)
    page_size = 50
    page = max(page, 1)
    conditions = []
    if audit_action.strip():
        conditions.append(AuditEvent.action.ilike(f"%{audit_action.strip()}%"))
    if audit_ip.strip():
        conditions.append(AuditEvent.ip_address.ilike(f"%{audit_ip.strip()}%"))
    if audit_details.strip():
        conditions.append(AuditEvent.details.ilike(f"%{audit_details.strip()}%"))
    for raw_value, column in (
        (audit_user, AuditEvent.user_id),
        (audit_server, AuditEvent.server_id),
    ):
        if raw_value:
            try:
                conditions.append(column == uuid.UUID(raw_value))
            except ValueError as exc:
                raise HTTPException(status_code=422, detail="Invalid audit filter") from exc
    for raw_value, lower_bound in ((date_from, True), (date_to, False)):
        if raw_value:
            try:
                parsed = date.fromisoformat(raw_value)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail="Invalid audit date") from exc
            boundary = datetime.combine(parsed, time.min, tzinfo=UTC)
            conditions.append(
                AuditEvent.created_at >= boundary
                if lower_bound
                else AuditEvent.created_at < boundary + timedelta(days=1)
            )
    async with SessionFactory() as database:
        total = int(
            await database.scalar(select(func.count(AuditEvent.id)).where(*conditions)) or 0
        )
        total_pages = max(1, (total + page_size - 1) // page_size)
        page = min(page, total_pages)
        events = (
            await database.execute(
                select(AuditEvent, User.email, MinecraftServer.name)
                .outerjoin(User, User.id == AuditEvent.user_id)
                .outerjoin(MinecraftServer, MinecraftServer.id == AuditEvent.server_id)
                .where(*conditions)
                .order_by(AuditEvent.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        users = list(await database.scalars(select(User).order_by(User.email)))
        servers = list(
            await database.scalars(select(MinecraftServer).order_by(MinecraftServer.name))
        )
    filter_values = {
        "audit_action": audit_action,
        "audit_user": audit_user,
        "audit_server": audit_server,
        "audit_ip": audit_ip,
        "audit_details": audit_details,
        "date_from": date_from,
        "date_to": date_to,
    }

    def page_url(target: int) -> str:
        values = {key: value for key, value in filter_values.items() if value}
        values["page"] = target
        return f"/admin/audit?{urlencode(values)}"

    return templates.TemplateResponse(
        request,
        "audit_logs.html",
        {
            "events": events,
            "users": users,
            "servers": servers,
            **filter_values,
            "page": page,
            "total": total,
            "total_pages": total_pages,
            "previous_url": page_url(page - 1) if page > 1 else None,
            "next_url": page_url(page + 1) if page < total_pages else None,
        },
    )


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
    return RedirectResponse("/admin/users?message=Sessions+revoked", status_code=303)


@router.post("/admin/users/{user_id}/status")
async def update_user_status(
    request: Request,
    user_id: uuid.UUID,
    action: str = Form(pattern=r"^(enable|disable)$"),
    csrf_token: str = Form(),
):
    current_user = require_admin(request)
    require_csrf(request, csrf_token)
    if user_id == current_user.id and action == "disable":
        raise HTTPException(status_code=409, detail="You cannot disable your own account")
    async with SessionFactory() as database:
        target = await database.get(User, user_id)
        if target is None:
            raise HTTPException(status_code=404, detail="User not found")
        if action == "disable" and target.role is UserRole.ADMIN and target.is_active:
            active_admins = int(
                await database.scalar(
                    select(func.count(User.id)).where(
                        User.role == UserRole.ADMIN, User.is_active.is_(True)
                    )
                )
                or 0
            )
            if active_admins <= 1:
                raise HTTPException(status_code=409, detail="The last active administrator cannot be disabled")
        target.is_active = action == "enable"
        if action == "disable":
            now = datetime.now(UTC)
            sessions = list(
                await database.scalars(
                    select(UserSession).where(
                        UserSession.user_id == user_id, UserSession.revoked_at.is_(None)
                    )
                )
            )
            for session in sessions:
                session.revoked_at = now
        target_email = target.email
        await database.commit()
    await record_audit(request, f"user.{action}", details=f"{target_email}:{user_id}")
    return RedirectResponse(f"/admin/users?message=User+{action}d", status_code=303)


@router.post("/admin/users/{user_id}/delete")
async def delete_user(request: Request, user_id: uuid.UUID, csrf_token: str = Form()):
    current_user = require_admin(request)
    require_csrf(request, csrf_token)
    if user_id == current_user.id:
        raise HTTPException(status_code=409, detail="You cannot delete your own account")
    async with SessionFactory() as database:
        target = await database.get(User, user_id)
        if target is None:
            raise HTTPException(status_code=404, detail="User not found")
        if target.role is UserRole.ADMIN:
            admin_count = int(
                await database.scalar(select(func.count(User.id)).where(User.role == UserRole.ADMIN))
                or 0
            )
            if admin_count <= 1:
                raise HTTPException(status_code=409, detail="The last administrator cannot be deleted")
        target_email = target.email
        await database.execute(delete(ServerMember).where(ServerMember.user_id == user_id))
        await database.delete(target)
        await database.commit()
    await record_audit(request, "user.delete", details=f"{target_email}:{user_id}")
    return RedirectResponse("/admin/users?message=User+deleted", status_code=303)
