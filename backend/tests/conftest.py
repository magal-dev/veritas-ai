import pytest

from services.session_store import session_store


@pytest.fixture(autouse=True)
def _isolated_sessions():
    session_store.clear()
    yield
    session_store.clear()
