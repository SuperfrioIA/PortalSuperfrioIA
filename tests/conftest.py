"""Infra dos testes do Hub SuperFrio.

Banco isolado em arquivo temporário (SQLite real, não mock) — o env precisa
ser definido ANTES de importar qualquer módulo do backend, pois
`core/database.py` lê `SUPERFRIO_DB_PATH` no import.
"""
import os
import tempfile
from pathlib import Path

import pytest

_TMP_DIR = tempfile.mkdtemp(prefix="superfrio_test_")
os.environ["SUPERFRIO_DB_PATH"] = str(Path(_TMP_DIR) / "test_portal.db")
os.environ.setdefault("SUPERFRIO_ENV", "dev")

from fastapi.testclient import TestClient  # noqa: E402

from backend.core.database import init_db  # noqa: E402
from backend.core.limiter import limiter  # noqa: E402
from backend.main import app  # noqa: E402
from backend.seed import seed_initial  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _banco_seedado():
    """Cria schema + seed uma vez por sessão no banco temporário."""
    init_db()
    seed_initial()
    yield


@pytest.fixture(autouse=True)
def _sem_rate_limit():
    """Rate limit atrapalha os logins repetidos dos testes; o teste de
    lockout religa explicitamente. Reseta o storage entre cada teste."""
    limiter.enabled = False
    limiter.reset()
    yield
    limiter.enabled = False
    limiter.reset()


@pytest.fixture
def client():
    # Sem context manager de propósito: o lifespan (init_db+seed) não roda;
    # quem controla o banco é a fixture _banco_seedado.
    return TestClient(app)


def _auth_header(client, username: str, senha: str) -> dict:
    r = client.post("/api/auth/login", data={"username": username, "password": senha})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def admin_headers(client):
    return _auth_header(client, "admin", "admin123")


@pytest.fixture
def operador_headers(client):
    return _auth_header(client, "operador.armazem", "armazem123")


@pytest.fixture
def analista_headers(client):
    return _auth_header(client, "analista.bo", "backoffice123")
