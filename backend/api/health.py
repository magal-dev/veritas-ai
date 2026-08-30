from fastapi import APIRouter

from core.database import database_is_reachable

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    db_ok = await database_is_reachable()
    return {
        "status": "ok",
        "database": "connected" if db_ok else "unavailable",
        "note": (
            "Postgres armazena só metadados operacionais. "
            "Jobs funcionam em memória mesmo com o banco indisponível."
        ),
    }
