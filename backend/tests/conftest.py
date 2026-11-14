import pytest

from core.config import settings
from services.session_store import session_store


@pytest.fixture(autouse=True)
def _no_real_gemini_key(monkeypatch):
    # O Settings lê o .env da máquina; sem isto, quem tem GEMINI_API_KEY local chamaria o
    # Gemini real nos testes. Teste que precisa de chave faz o próprio monkeypatch.
    monkeypatch.setattr(settings, "gemini_api_key", "")


@pytest.fixture(autouse=True)
def _isolated_sessions():
    session_store.clear()
    yield
    session_store.clear()
