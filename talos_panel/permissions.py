import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from talos_panel.models import MinecraftServer, ServerMember, ServerRole, User, UserRole


async def accessible_servers(session: AsyncSession, user: User) -> list[MinecraftServer]:
    query = select(MinecraftServer).order_by(MinecraftServer.created_at)
    if user.role is not UserRole.ADMIN:
        query = query.join(ServerMember).where(ServerMember.user_id == user.id)
    return list(await session.scalars(query))


async def require_server_access(
    session: AsyncSession,
    user: User,
    server_id: uuid.UUID,
    *,
    owner: bool = False,
) -> MinecraftServer:
    server = await session.get(MinecraftServer, server_id)
    if server is None:
        raise HTTPException(status_code=404, detail="Server not found")
    if user.role is UserRole.ADMIN:
        return server
    membership = await session.scalar(
        select(ServerMember).where(
            ServerMember.server_id == server_id, ServerMember.user_id == user.id
        )
    )
    if membership is None or (owner and membership.role is not ServerRole.OWNER):
        raise HTTPException(status_code=404, detail="Server not found")
    return server


async def can_manage_server(session: AsyncSession, user: User, server_id: uuid.UUID) -> bool:
    if user.role is UserRole.ADMIN:
        return True
    role = await session.scalar(
        select(ServerMember.role).where(
            ServerMember.server_id == server_id, ServerMember.user_id == user.id
        )
    )
    return role is ServerRole.OWNER
