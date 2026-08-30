"""Engine async do PostgreSQL. Uso exclusivo: metadados operacionais."""

from collections.abc import AsyncGenerator

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


async def database_is_reachable() -> bool:
    try:
        async with engine.connect() as connection:
            await connection.execute(__import__("sqlalchemy").text("SELECT 1"))
        return True
    except Exception:
        return False
