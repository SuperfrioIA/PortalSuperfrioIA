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
def _sem_rede_externa(monkeypatch):
    """A suíte nunca sai da máquina (Lote 3: o provedor do modelo tem SDK de verdade, e um
    teste que esquecesse de simular o transporte chamaria a API paga). Conectar fora do
    loopback falha na hora. Não afeta o libpq (Postgres local) nem o TestClient."""
    import socket

    original = socket.socket.connect

    def guardado(self, endereco):
        host = endereco[0] if isinstance(endereco, tuple) else None
        if host is not None and host not in ("127.0.0.1", "::1", "localhost", "0.0.0.0"):
            raise AssertionError(f"rede bloqueada nos testes: {host}")
        return original(self, endereco)

    monkeypatch.setattr(socket.socket, "connect", guardado)


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


# ======================================================== SuperfrioIA (Lote 2)
# O banco é um só para a sessão inteira, e há testes com contagem fixa de apps
# (`total_apps == 11`...). Por isso o app `superfrioia` e as tabelas `ia_*` só
# existem DENTRO dos testes que pedem `ia_ligada`, e são desfeitos no fim.

@pytest.fixture
def ia_ligada(monkeypatch):
    """`IA_HABILITADO` ligada e o app `superfrioia` no catálogo, desfeitos no fim."""
    from sqlalchemy import delete, select

    from backend.core.database import db
    from backend.ia import dominios as ia_dominios
    from backend.ia.models import IaConcessao, IaConsulta, IaConversa, IaMensagem
    from backend.portal import seed as portal_seed
    from backend.portal.models import App
    from backend.usuarios.models import role_apps

    def _limpar():
        with db() as session:
            for tabela in (IaConsulta, IaMensagem, IaConversa, IaConcessao):
                session.execute(delete(tabela))
            app_id = session.execute(select(App.id).where(App.slug == "superfrioia")).scalar_one_or_none()
            if app_id is not None:
                session.execute(delete(role_apps).where(role_apps.c.app_id == app_id))
                session.execute(delete(App).where(App.id == app_id))

    monkeypatch.setenv("IA_HABILITADO", "true")
    ia_dominios.carregar()
    with db() as session:
        portal_seed.seed(session)
    yield
    _limpar()


@pytest.fixture
def ia_dw(monkeypatch):
    """Fábrica do DW de mentira (`tests/dw_falso.py`). Chame `ia_dw()` ou
    `ia_dw(n_unidades=14)`; os caches do módulo são zerados no fim."""
    import dw_falso

    from backend.volumetria_catering import dimensoes_dw, schema_dw

    def _ligar(**kwargs):
        return dw_falso.instalar(monkeypatch, **kwargs)

    yield _ligar
    dimensoes_dw.invalidar()
    schema_dw.invalidar()


@pytest.fixture
def usuario_ia(ia_ligada, ia_dw, criar_usuario_ia, client, admin_headers):
    """Usuário comum com `ver` do app, `ver` do card e concessão ativa, e o DW de
    mentira ligado. É o ponto de partida da maioria dos testes do SuperfrioIA."""
    ia_dw()
    u = criar_usuario_ia("analista")
    r = client.post("/api/ia/concessoes/pedidos", headers=u["headers"],
                    json={"dominio": "volumetria-catering", "motivo": "análise de volumetria"})
    assert r.status_code == 201, r.text
    r = client.post(f"/api/ia/administracao/concessoes/{r.json()['id']}/aprovar", headers=admin_headers, json={})
    assert r.status_code == 200, r.text
    u["concessao_id"] = r.json()["id"]
    return u


@pytest.fixture
def criar_usuario_ia(client, admin_headers):
    """Fábrica de usuário comum com as células da matriz que o teste pedir.

    `ver_sistema`: `volumetria-catering:ver`; `ver_ia`: `superfrioia:ver` (o card);
    `administrar`: `volumetria-catering:administrar`. Nome único por chamada: o
    banco da sessão é compartilhado e o admin não tem exclusão de usuário."""
    import uuid

    def _criar(prefixo="ia", *, ver_sistema=True, ver_ia=True, administrar=False):
        sufixo = uuid.uuid4().hex[:8]
        apps = (["volumetria-catering"] if ver_sistema else []) + (["superfrioia"] if ver_ia else [])
        permissoes = ["volumetria-catering:administrar"] if administrar else []
        role = f"ia-{sufixo}"
        r = client.post("/api/admin/roles", headers=admin_headers,
                        json={"slug": role, "nome": f"IA {sufixo}", "apps": apps, "permissoes": permissoes})
        assert r.status_code == 201, r.text
        username = f"{prefixo}.{sufixo}"
        r = client.post("/api/admin/usuarios", headers=admin_headers,
                        json={"username": username, "senha": "senha-de-teste-123", "roles": [role]})
        assert r.status_code == 201, r.text
        token = client.post("/api/auth/login",
                            data={"username": username, "password": "senha-de-teste-123"}).json()["access_token"]
        return {"headers": {"Authorization": f"Bearer {token}"}, "username": username,
                "id": r.json()["id"], "role": role}

    return _criar
