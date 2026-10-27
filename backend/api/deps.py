import time
from collections.abc import AsyncGenerator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import SessionLocal, database_is_reachable
from repositories.processing_run_repository import ProcessingRunRepository
from services.job_service import JobService

# Sucesso fica em cache: o banco que cai no meio da sessão só faz o metadado ser omitido.
# Falha é reavaliada, senão um Postgres que sobe depois nunca volta a ser usado.
_db_enabled: bool | None = None
_db_checked_at = 0.0
DB_RECHECK_SECONDS = 30


async def db_enabled() -> bool:
    global _db_enabled, _db_checked_at
    now = time.monotonic()
    if _db_enabled is True:
        return True
    if _db_enabled is False and now - _db_checked_at < DB_RECHECK_SECONDS:
        return False
    _db_enabled = await database_is_reachable()
    _db_checked_at = now
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
