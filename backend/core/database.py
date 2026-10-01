"""Engine async do PostgreSQL. Uso exclusivo: metadados operacionais."""

import asyncio
from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from core.config import settings


class Base(DeclarativeBase):
    pass


engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    echo=False,
)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session


DB_PROBE_TIMEOUT_SECONDS = 3


async def _probe() -> None:
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))


async def database_is_reachable() -> bool:
    # Sem Postgres local, a API segue sem metadados; não pode travar a primeira requisição.
    try:
        await asyncio.wait_for(_probe(), timeout=DB_PROBE_TIMEOUT_SECONDS)
        return True
    except Exception:
        return False
