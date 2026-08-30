from collections.abc import AsyncGenerator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import SessionLocal, database_is_reachable
from repositories.processing_run_repository import ProcessingRunRepository
from services.job_service import JobService

_db_enabled: bool | None = None


async def db_enabled() -> bool:
    global _db_enabled
    if _db_enabled is None:
        _db_enabled = await database_is_reachable()
    return _db_enabled


async def get_run_repository() -> AsyncGenerator[ProcessingRunRepository | None, None]:
    if not await db_enabled():
        yield None
        return
    async with SessionLocal() as session:
        yield ProcessingRunRepository(session)


async def get_job_service(
    repository: ProcessingRunRepository | None = Depends(get_run_repository),
) -> JobService:
    return JobService(repository)
