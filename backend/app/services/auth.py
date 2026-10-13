from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.errors import APIError
from app.core.security import DUMMY_PASSWORD_HASH, hash_password, verify_password
from app.models import User
from app.models.enums import Role
from app.schemas.auth import LoginRequest, RegisterRequest


async def register_user(session: AsyncSession, request: RegisterRequest, role: Role) -> User:
    if role not in {Role.CUSTOMER, Role.HOST}:
        raise APIError(403, "FORBIDDEN", "Public registration supports Customer and Host only")
    password_hash = await run_in_threadpool(hash_password, request.password.get_secret_value())
    # Unique-email conflict handling remains correct for concurrent signups.
    result = await session.scalars(
        insert(User)
        .values(
            name=request.name,
            email=request.email,
            phone=request.phone,
            password_hash=password_hash,
            role=role,
        )
        .on_conflict_do_nothing(index_elements=[User.email])
        .returning(User)
    )
    user = result.one_or_none()
    if user is None:
        await session.rollback()
        raise APIError(409, "EMAIL_ALREADY_REGISTERED", "Email is already registered")
    await session.commit()
    return user


async def authenticate_user(session: AsyncSession, request: LoginRequest) -> User:
    user = await session.scalar(select(User).where(User.email == request.email))
    password_hash = user.password_hash if user else DUMMY_PASSWORD_HASH
    valid = await run_in_threadpool(
        verify_password, request.password.get_secret_value(), password_hash
    )
    if not valid or user is None:
        raise APIError(
            401,
            "INVALID_CREDENTIALS",
            "Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user
