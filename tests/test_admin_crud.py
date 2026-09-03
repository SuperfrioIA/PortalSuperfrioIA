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
    # 3 exemplos + processos-abertos, integracao-in-out, gerador-qrcode,
    # volumetria-catering e volumetria-transporte (apps reais do repo)
    assert armazem["apps_count"] == 8


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


def test_criar_app_url_relativa_ok(client, admin_headers):
    sid = _id_por_slug(client, admin_headers, "secoes", "armazem")
    r = client.post(
        "/api/admin/apps",
        json=_payload_app("app-html-embutido", sid, url="/mapa-estatistico/", tipo_acesso="iframe"),
        headers=admin_headers,
    )
    assert r.status_code == 201
    assert r.json()["url"] == "/mapa-estatistico/"


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
    # 3 apps da role + governanca-ti, que nasceu liberado para todas as roles
    # (era botão fixo da sidebar antes de virar app — ver backend/usuarios/seed.py)
    assert len(armazem_full["apps"]) == 4


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


# ---------- Cadastro de usuário: acesso Microsoft e filial (lote de 21/08/2026) ----------

def _id_filial(client, admin_headers, codigo):
    filiais = client.get("/api/admin/filiais", headers=admin_headers).json()
    return next(f["id"] for f in filiais if f["codigo"] == codigo)


def test_criar_usuario_sem_senha_e_acesso_microsoft(client, admin_headers):
    """Cadastro prévio para quem vai entrar pelo Entra: sem senha nenhuma, e-mail
    obrigatório porque é o que casa com o claim do token."""
    r = client.post(
        "/api/admin/usuarios",
        json={"username": "novo.ad", "email": "Novo.AD@SuperFrio.com.br", "nome": "Novo AD"},
        headers=admin_headers,
    )
    assert r.status_code == 201
    body = r.json()
    assert body["auth_source"] == "ad"
    assert body["email"] == "novo.ad@superfrio.com.br"  # normalizado


def test_usuario_microsoft_nao_loga_com_senha_local(client, admin_headers):
    """Sem password_hash, nenhuma senha pode funcionar — o caminho dele é o SSO."""
    client.post(
        "/api/admin/usuarios",
        json={"username": "so.ad", "email": "so.ad@superfrio.com.br"},
        headers=admin_headers,
    )
    r = client.post("/api/auth/login", data={"username": "so.ad", "password": "qualquer-coisa"})
    assert r.status_code == 401


def test_criar_usuario_sem_senha_exige_email(client, admin_headers):
    r = client.post(
        "/api/admin/usuarios", json={"username": "sem.email.ad"}, headers=admin_headers
    )
    assert r.status_code == 400
    assert "e-mail" in r.json()["detail"].lower()


def test_criar_usuario_email_duplicado_409(client, admin_headers):
    """E-mail é a chave do login SSO: dois cadastros com o mesmo e-mail deixariam o
    login escolher um deles de forma arbitrária (índice único da migration 0005)."""
    client.post(
        "/api/admin/usuarios",
        json={"username": "primeiro.dono", "email": "disputado@superfrio.com.br"},
        headers=admin_headers,
    )
    r = client.post(
        "/api/admin/usuarios",
        json={"username": "segundo.dono", "email": "DISPUTADO@superfrio.com.br"},
        headers=admin_headers,
    )
    assert r.status_code == 409
    assert "primeiro.dono" in r.json()["detail"]  # diz de quem é o e-mail


def test_criar_usuario_com_senha_ainda_e_local(client, admin_headers):
    """A tela não oferece mais, mas a API continua criando usuário local — é o
    acesso de emergência se o SSO cair."""
    r = client.post(
        "/api/admin/usuarios",
        json={"username": "emergencia.local", "senha": "senha12345"},
        headers=admin_headers,
    )
    assert r.status_code == 201
    assert r.json()["auth_source"] == "local"


def test_criar_usuario_com_filial(client, admin_headers):
    fid = _id_filial(client, admin_headers, "1011")  # CSC
    r = client.post(
        "/api/admin/usuarios",
        json={
            "username": "lotado.csc",
            "email": "lotado.csc@superfrio.com.br",
            "filial_id": fid,
        },
        headers=admin_headers,
    )
    assert r.status_code == 201
    assert r.json()["filial_id"] == fid
    # Enriquecimento on-read: a tela não precisa cruzar as duas listas.
    assert r.json()["filial_codigo"] == "1011"
    assert r.json()["filial_nome"] == "CSC"


def test_criar_usuario_filial_inexistente_400(client, admin_headers):
    r = client.post(
        "/api/admin/usuarios",
        json={"username": "filial.ruim", "email": "filial.ruim@superfrio.com.br", "filial_id": 999999},
        headers=admin_headers,
    )
    assert r.status_code == 400


def test_patch_usuario_troca_e_limpa_filial(client, admin_headers):
    fid = _id_filial(client, admin_headers, "1011")
    uid = client.post(
        "/api/admin/usuarios",
        json={"username": "troca.filial", "email": "troca.filial@superfrio.com.br"},
        headers=admin_headers,
    ).json()["id"]

    r = client.patch(f"/api/admin/usuarios/{uid}", json={"filial_id": fid}, headers=admin_headers)
    assert r.json()["filial_codigo"] == "1011"

    r = client.patch(f"/api/admin/usuarios/{uid}", json={"filial_id": None}, headers=admin_headers)
    assert r.json()["filial_id"] is None
    assert r.json()["filial_codigo"] is None


def test_patch_usuario_email_duplicado_409(client, admin_headers):
    """Sem esta checagem o e-mail repetido bateria no índice único e viraria 500."""
    client.post(
        "/api/admin/usuarios",
        json={"username": "dono.original", "email": "unico@superfrio.com.br"},
        headers=admin_headers,
    )
    outro = client.post(
        "/api/admin/usuarios",
        json={"username": "outro.qualquer", "email": "outro@superfrio.com.br"},
        headers=admin_headers,
    ).json()["id"]
    r = client.patch(
        f"/api/admin/usuarios/{outro}",
        json={"email": "unico@superfrio.com.br"},
        headers=admin_headers,
    )
    assert r.status_code == 409


def test_patch_usuario_mantendo_o_proprio_email_nao_conflita(client, admin_headers):
    uid = client.post(
        "/api/admin/usuarios",
        json={"username": "mesmo.email", "email": "mesmo@superfrio.com.br"},
        headers=admin_headers,
    ).json()["id"]
    r = client.patch(
        f"/api/admin/usuarios/{uid}",
        json={"email": "mesmo@superfrio.com.br", "nome": "Mesmo Email"},
        headers=admin_headers,
    )
    assert r.status_code == 200
    assert r.json()["nome"] == "Mesmo Email"
# ---------- URL de app embutido: barra no fim (bug do mapa-estatistico) ----------

def test_criar_app_iframe_ganha_barra_no_fim(client, admin_headers):
    """App embutido cadastrado sem a barra fazia o StaticFiles redirecionar, e o
    redirect (http:// atrás do ALB) era barrado pelo frame-src do CSP — o app
    abria em branco. Cadastro passa a normalizar."""
    sid = _id_por_slug(client, admin_headers, "secoes", "armazem")
    r = client.post(
        "/api/admin/apps",
        json=_payload_app("app-sem-barra", sid, url="/app-sem-barra", tipo_acesso="iframe"),
        headers=admin_headers,
    )
    assert r.status_code == 201
    assert r.json()["url"] == "/app-sem-barra/"


def test_criar_app_url_externa_e_interno_nao_sao_alterados(client, admin_headers):
    """Normalizar só vale pra iframe: em `url` a barra é indiferente e em `interno`
    o campo é identificador de tela do SPA, não caminho."""
    sid = _id_por_slug(client, admin_headers, "secoes", "armazem")
    externo = client.post(
        "/api/admin/apps",
        json=_payload_app("app-externo", sid, url="https://exemplo.interno/x", tipo_acesso="url"),
        headers=admin_headers,
    )
    assert externo.json()["url"] == "https://exemplo.interno/x"
    interno = client.post(
        "/api/admin/apps",
        json=_payload_app("app-interno-spa", sid, url="/tela-nativa", tipo_acesso="interno"),
        headers=admin_headers,
    )
    assert interno.json()["url"] == "/tela-nativa"


def test_criar_app_iframe_apontando_arquivo_nao_ganha_barra(client, admin_headers):
    sid = _id_por_slug(client, admin_headers, "secoes", "armazem")
    r = client.post(
        "/api/admin/apps",
        json=_payload_app("app-arquivo", sid, url="/pasta/index.html", tipo_acesso="iframe"),
        headers=admin_headers,
    )
    assert r.json()["url"] == "/pasta/index.html"


def test_patch_app_url_ganha_barra_usando_tipo_ja_gravado(client, admin_headers):
    """No PATCH o tipo_acesso costuma não vir no corpo — a normalização tem que
    usar o que já está gravado, senão a barra não é aplicada."""
    sid = _id_por_slug(client, admin_headers, "secoes", "armazem")
    criado = client.post(
        "/api/admin/apps",
        json=_payload_app("app-patch-barra", sid, url="/x/", tipo_acesso="iframe"),
        headers=admin_headers,
    ).json()
    r = client.patch(
        f"/api/admin/apps/{criado['id']}", json={"url": "/mapa-qualquer"}, headers=admin_headers
    )
    assert r.status_code == 200
    assert r.json()["url"] == "/mapa-qualquer/"
