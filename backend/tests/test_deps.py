import time

import api.deps as deps


async def test_down_database_is_probed_again_after_the_cooldown(monkeypatch):
    previous = (deps._db_enabled, deps._db_checked_at)
    calls = {"n": 0}

    async def up() -> bool:
        calls["n"] += 1
        return True

    try:
        deps._db_enabled = False
        deps._db_checked_at = time.monotonic()

        async def unexpected() -> bool:
            raise AssertionError("probe dentro da janela")

        monkeypatch.setattr(deps, "database_is_reachable", unexpected)
        assert await deps.db_enabled() is False

        deps._db_checked_at = time.monotonic() - deps.DB_RECHECK_SECONDS - 1
        monkeypatch.setattr(deps, "database_is_reachable", up)
        assert await deps.db_enabled() is True
        assert await deps.db_enabled() is True
        assert calls["n"] == 1
    finally:
        deps._db_enabled, deps._db_checked_at = previous
