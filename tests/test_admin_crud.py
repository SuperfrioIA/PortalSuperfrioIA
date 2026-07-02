"""CRUD admin + validações de boundary ([admin.py]).

O banco é seedado uma vez por sessão; cada teste de mutação cria a própria
entidade (slug/username únicos) e a fixture `_restore_db` apaga tudo que foi
criado no fim — assim o seed volta intacto para os outros arquivos de teste.
Testes de toggle/patch operam SEMPRE em entidades criadas aqui, nunca no seed.
"""
import pytest
from sqlalchemy import text

from backend.core.database import db


@pytest.fixture(autouse=True)
def _restore_db():
    """Snapshot dos ids antes; remove os criados depois (FK cascade cuida do resto)."""
    tabelas = ["secoes", "apps", "roles", "usuarios"]
    with db() as conn:
        antes = {t: set(conn.execute(text(f"SELECT id FROM {t}")).scalars()) for t in tabelas}
    yield
    with db() as conn:
        for t in ["usuarios", "roles", "apps", "secoes"]:
            atuais = set(conn.execute(text(f"SELECT id FROM {t}")).scalars())
            for novo in atuais - antes[t]:
                conn.execute(text(f"DELETE FROM {t} WHERE id = :id"), {"id": novo})


def _id_por_slug(client, headers, recurso, slug):
    r = client.get(f"/api/admin/{recurso}", headers=headers)
    return next(x["id"] for x in r.json() if x["slug"] == slug)


# ============ Seções ============

def test_criar_secao_ok(client, admin_headers):
    r = client.post(
        "/api/admin/secoes",
        json={"slug": "teste-secao", "nome": "Teste", "ordem": 9},
        headers=admin_headers,
    )
    assert r.status_code == 201
    body = r.json()
    assert body["slug"] == "teste-secao"
    assert body["ativo"] == 1


def test_criar_secao_slug_invalido(client, admin_headers):
    r = client.post(
        "/api/admin/secoes",
        json={"slug": "Maiúsculo Com Espaço", "nome": "X"},
        headers=admin_headers,
    )
    assert r.status_code == 400


def test_criar_secao_slug_duplicado(client, admin_headers):
    r = client.post(
        "/api/admin/secoes",
        json={"slug": "armazem", "nome": "Duplicada"},
        headers=admin_headers,
    )
    assert r.status_code == 409


def test_listar_secoes_traz_apps_count(client, admin_headers):
    r = client.get("/api/admin/secoes", headers=admin_headers)
    assert r.status_code == 200
    armazem = next(s for s in r.json() if s["slug"] == "armazem")
    assert armazem["apps_count"] == 3


def test_patch_secao_parcial(client, admin_headers):
    sid = client.post(
        "/api/admin/secoes", json={"slug": "patch-secao", "nome": "Antigo"}, headers=admin_headers
    ).json()["id"]
    r = client.patch(f"/api/admin/secoes/{sid}", json={"nome": "Novo Nome"}, headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["nome"] == "Novo Nome"
    assert r.json()["slug"] == "patch-secao"  # slug é estável


def test_patch_secao_inexistente(client, admin_headers):
    r = client.patch("/api/admin/secoes/999999", json={"nome": "X"}, headers=admin_headers)
    assert r.status_code == 404


def test_toggle_secao(client, admin_headers):
    sid = client.post(
        "/api/admin/secoes", json={"slug": "toggle-secao", "nome": "T"}, headers=admin_headers
    ).json()["id"]
    r = client.post(f"/api/admin/secoes/{sid}/toggle", headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["ativo"] == 0


# ============ Apps ============

def _payload_app(slug, secao_id, **over):
    base = {
        "slug": slug,
        "nome": "App Teste",
        "secao_id": secao_id,
        "url": "https://example.internal/teste",
        "tipo_acesso": "url",
    }
    base.update(over)
    return base


def test_criar_app_ok(client, admin_headers):
    sid = _id_por_slug(client, admin_headers, "secoes", "armazem")
    r = client.post("/api/admin/apps", json=_payload_app("teste-app", sid), headers=admin_headers)
    assert r.status_code == 201
    assert r.json()["secao_slug"] == "armazem"


def test_criar_app_url_invalida(client, admin_headers):
    sid = _id_por_slug(client, admin_headers, "secoes", "armazem")
    r = client.post(
        "/api/admin/apps", json=_payload_app("app-url-ruim", sid, url="ftp://x"), headers=admin_headers
    )
    assert r.status_code == 400


def test_criar_app_tipo_invalido(client, admin_headers):
    sid = _id_por_slug(client, admin_headers, "secoes", "armazem")
    r = client.post(
        "/api/admin/apps", json=_payload_app("app-tipo-ruim", sid, tipo_acesso="popup"), headers=admin_headers
    )
    assert r.status_code == 400


def test_criar_app_secao_inexistente(client, admin_headers):
    r = client.post("/api/admin/apps", json=_payload_app("app-sem-secao", 999999), headers=admin_headers)
    assert r.status_code == 404


def test_criar_app_slug_duplicado(client, admin_headers):
    sid = _id_por_slug(client, admin_headers, "secoes", "armazem")
    r = client.post("/api/admin/apps", json=_payload_app("faq-slin", sid), headers=admin_headers)
    assert r.status_code == 409


def test_patch_app_url_invalida(client, admin_headers):
    sid = _id_por_slug(client, admin_headers, "secoes", "armazem")
    aid = client.post(
        "/api/admin/apps", json=_payload_app("patch-app", sid), headers=admin_headers
    ).json()["id"]
    r = client.patch(f"/api/admin/apps/{aid}", json={"url": "javascript:alert(1)"}, headers=admin_headers)
    assert r.status_code == 400


def test_toggle_app(client, admin_headers):
    sid = _id_por_slug(client, admin_headers, "secoes", "armazem")
    aid = client.post(
        "/api/admin/apps", json=_payload_app("toggle-app", sid), headers=admin_headers
    ).json()["id"]
    r = client.post(f"/api/admin/apps/{aid}/toggle", headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["ativo"] == 0


# ============ Roles ============

def test_criar_role_ok(client, admin_headers):
    r = client.post(
        "/api/admin/roles",
        json={"slug": "teste-role", "nome": "Role Teste", "apps": ["faq-slin"]},
        headers=admin_headers,
    )
    assert r.status_code == 201
    assert r.json()["apps"] == ["faq-slin"]


def test_criar_role_app_inexistente(client, admin_headers):
    r = client.post(
        "/api/admin/roles",
        json={"slug": "role-app-ruim", "nome": "X", "apps": ["nao-existe"]},
        headers=admin_headers,
    )
    assert r.status_code == 400


def test_patch_role_troca_apps(client, admin_headers):
    rid = client.post(
        "/api/admin/roles",
        json={"slug": "patch-role", "nome": "R", "apps": ["faq-slin"]},
        headers=admin_headers,
    ).json()["id"]
    r = client.patch(
        f"/api/admin/roles/{rid}",
        json={"apps": ["faq-blueyonder", "conciliacao-estoque"]},
        headers=admin_headers,
    )
    assert r.status_code == 200
    assert set(r.json()["apps"]) == {"faq-blueyonder", "conciliacao-estoque"}


def test_listar_roles_traz_counts(client, admin_headers):
    r = client.get("/api/admin/roles", headers=admin_headers)
    assert r.status_code == 200
    armazem_full = next(x for x in r.json() if x["slug"] == "armazem-full")
    assert armazem_full["usuarios_count"] == 1  # operador.armazem
    assert len(armazem_full["apps"]) == 3


# ============ Usuários ============

def test_criar_usuario_ok(client, admin_headers):
    r = client.post(
        "/api/admin/usuarios",
        json={"username": "teste.user", "senha": "inicial123", "roles": ["faq-leitor"]},
        headers=admin_headers,
    )
    assert r.status_code == 201
    assert r.json()["roles"] == ["faq-leitor"]
    assert "password_hash" not in r.json()  # nunca devolve hash


def test_criar_usuario_senha_curta(client, admin_headers):
    r = client.post(
        "/api/admin/usuarios",
        json={"username": "user.curto", "senha": "123"},
        headers=admin_headers,
    )
    assert r.status_code == 400


def test_criar_usuario_username_duplicado(client, admin_headers):
    r = client.post(
        "/api/admin/usuarios",
        json={"username": "admin", "senha": "outrasenha123"},
        headers=admin_headers,
    )
    assert r.status_code == 409


def test_criar_usuario_role_inexistente(client, admin_headers):
    r = client.post(
        "/api/admin/usuarios",
        json={"username": "user.role.ruim", "senha": "senha12345", "roles": ["nao-existe"]},
        headers=admin_headers,
    )
    assert r.status_code == 400


def test_patch_usuario_inexistente(client, admin_headers):
    r = client.patch("/api/admin/usuarios/999999", json={"nome": "X"}, headers=admin_headers)
    assert r.status_code == 404


def test_toggle_outro_usuario(client, admin_headers):
    uid = client.post(
        "/api/admin/usuarios",
        json={"username": "user.toggle", "senha": "senha12345"},
        headers=admin_headers,
    ).json()["id"]
    r = client.post(f"/api/admin/usuarios/{uid}/toggle", headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["ativo"] == 0


def test_reset_senha_curta_422(client, admin_headers):
    uid = client.post(
        "/api/admin/usuarios",
        json={"username": "user.reset.curto", "senha": "senha12345"},
        headers=admin_headers,
    ).json()["id"]
    r = client.post(f"/api/admin/usuarios/{uid}/password", json={"senha": "123"}, headers=admin_headers)
    assert r.status_code == 422  # validação Pydantic (Field min_length), não 400


def test_reset_senha_invalida_tokens_antigos(client, admin_headers):
    uid = client.post(
        "/api/admin/usuarios",
        json={"username": "user.reset", "senha": "inicial123"},
        headers=admin_headers,
    ).json()["id"]
    # token emitido com a senha inicial
    token = client.post(
        "/api/auth/login", data={"username": "user.reset", "password": "inicial123"}
    ).json()["access_token"]
    old_headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/auth/me", headers=old_headers).status_code == 200

    r = client.post(f"/api/admin/usuarios/{uid}/password", json={"senha": "novasenha123"}, headers=admin_headers)
    assert r.status_code == 200

    # reset incrementa token_version → token antigo morre
    assert client.get("/api/auth/me", headers=old_headers).status_code == 401
    # senha nova funciona
    assert client.post(
        "/api/auth/login", data={"username": "user.reset", "password": "novasenha123"}
    ).status_code == 200
