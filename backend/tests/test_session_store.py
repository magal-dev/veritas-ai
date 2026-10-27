import asyncio
import importlib
import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

# services/__init__.py reexporta o singleton com o mesmo nome do módulo.
store = importlib.import_module("services.session_store")
from schemas.jobs import JobStatus
from services.session_store import JobSession, SessionCapacityError


def _session() -> JobSession:
    return JobSession(
        job_id=uuid4(),
        status=JobStatus.COMPLETED,
        created_at=datetime.now(timezone.utc),
    )


def test_get_and_put_refresh_the_ttl():
    session = _session()
    store.session_store.put(session)
    session.expires_at = datetime.now(timezone.utc) + timedelta(seconds=30)
    before = session.expires_at

    loaded = store.session_store.get(session.job_id)

    assert loaded is session
    assert loaded is not None
    assert loaded.expires_at > before + timedelta(seconds=60)


def test_purge_expired_removes_only_due_sessions():
    kept = _session()
    due = _session()
    store.session_store.put(kept)
    store.session_store.put(due)
    due.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)

    assert store.session_store.purge_expired() == 1
    assert store.session_store.get(kept.job_id) is kept
    assert store.session_store.get(due.job_id) is None


def test_put_rejects_a_new_session_when_the_store_is_full(monkeypatch):
    monkeypatch.setattr(store, "MAX_JOB_SESSIONS", 1)
    store.session_store.put(_session())

    assert store.session_store.has_room() is False
    with pytest.raises(SessionCapacityError):
        store.session_store.put(_session())


async def test_idle_sweep_drops_expired_sessions(monkeypatch, caplog):
    from main import _sweep_sessions

    session = _session()
    store.session_store.put(session)
    session.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    calls = {"n": 0}

    async def sleep(_seconds: float) -> None:
        calls["n"] += 1
        if calls["n"] > 1:
            raise asyncio.CancelledError()

    monkeypatch.setattr("main.asyncio.sleep", sleep)
    with caplog.at_level(logging.INFO, logger="veritas_ai"):
        with pytest.raises(asyncio.CancelledError):
            await _sweep_sessions()

    assert calls["n"] == 2
    assert store.session_store.get(session.job_id) is None
    assert "session.purged count=1" in caplog.text
