from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.health import router as health_router
from main import mount_frontend


def _app_with_frontend(static_dir: str) -> tuple[FastAPI, bool]:
    app = FastAPI()
    app.include_router(health_router)
    return app, mount_frontend(app, static_dir)


def test_frontend_served_from_same_origin(tmp_path):
    (tmp_path / "index.html").write_text("<div id=root></div>", encoding="utf-8")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    app, mounted = _app_with_frontend(str(tmp_path))
    client = TestClient(app)

    assert mounted
    assert "id=root" in client.get("/").text
    assert client.get("/assets/app.js").status_code == 200
    # Rotas da API continuam com precedência sobre os estáticos.
    assert client.get("/health").json()["status"] == "ok"


def test_frontend_not_mounted_without_dir_or_build(tmp_path):
    assert _app_with_frontend("")[1] is False
    assert _app_with_frontend(str(tmp_path))[1] is False
