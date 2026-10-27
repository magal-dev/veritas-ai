import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.health import router as health_router
from api.jobs import router as jobs_router
from core.config import settings
from core.database import database_is_reachable
from core.logging import logger
from services.session_store import session_store

SESSION_SWEEP_SECONDS = 60


async def _sweep_sessions() -> None:
    """Tira sessões vencidas da memória mesmo sem outra request."""
    while True:
        await asyncio.sleep(SESSION_SWEEP_SECONDS)
        removed = session_store.purge_expired()
        if removed:
            logger.info("session.purged count=%s", removed)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db_ok = await database_is_reachable()
    logger.info("startup database=%s", "connected" if db_ok else "unavailable")
    sweep = asyncio.create_task(_sweep_sessions())
    try:
        yield
    finally:
        sweep.cancel()
        with suppress(asyncio.CancelledError):
            await sweep


app = FastAPI(
    title="Veritas AI",
    description=(
        "API do Veritas AI. Jobs são stateless (memória + TTL). "
        "PostgreSQL guarda só metadados operacionais, nunca conteúdo processual."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin, "http://127.0.0.1:4174", "http://localhost:4174"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(jobs_router)
