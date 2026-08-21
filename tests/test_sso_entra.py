"""SSO Microsoft Entra ID (Degrau 3) — dormente por padrão nos testes (nenhum
ENTRA_* setado no ambiente de teste), e monkeypatchado pra "ligado" nos testes
que exercitam o fluxo completo. `msal` nunca é chamado de verdade: os métodos
`authorization_url`/`exchange_code` são substituídos, então nenhum teste bate
na rede do Microsoft.
"""
from urllib.parse import parse_qs, urlparse

from sqlalchemy import text

from backend.auth import entra as entra_module
from backend.auth import provisioning
from backend.core.database import db
from backend.usuarios import service as usuarios_service


def _ligar_sso(monkeypatch):
    monkeypatch.setattr(entra_module, "ENTRA_TENANT_ID", "fake-tenant")
    monkeypatch.setattr(entra_module, "ENTRA_CLIENT_ID", "fake-client")
    monkeypatch.setattr(entra_module, "ENTRA_CLIENT_SECRET", "fake-secret")
    monkeypatch.setattr(entra_module, "ENTRA_REDIRECT_URI", "http://localhost:8000/api/auth/callback")
    # Default de producao: criacao automatica de cadastro DESLIGADA. Fixado aqui
    # pra suite nao mudar de resultado se quem roda tiver ENTRA_AUTO_PROVISION no shell.
    monkeypatch.setattr(entra_module, "ENTRA_AUTO_PROVISION", False)


def _mock_authorization_url(monkeypatch):
    monkeypatch.setattr(
        entra_module.EntraAuthProvider,
        "authorization_url",
        lambda self, state: f"https://login.microsoftonline.com/fake/authorize?state={state}",
    )


def _mock_exchange_code(monkeypatch, claims):
    monkeypatch.setattr(
        entra_module.EntraAuthProvider, "exchange_code", lambda self, code: claims
    )


# ---------- unidade: sso_enabled ----------

def test_sso_desligado_por_padrao():
    assert entra_module.sso_enabled() is False


def test_sso_liga_so_com_os_4_segredos(monkeypatch):
    _ligar_sso(monkeypatch)
    assert entra_module.sso_enabled() is True
    monkeypatch.setattr(entra_module, "ENTRA_CLIENT_SECRET", "")
    assert entra_module.sso_enabled() is False


# ---------- unidade: provisioning (claims -> usuário) ----------

def test_email_from_claims_ordem_de_preferencia():
    assert provisioning.email_from_claims({"email": "A@Superfrio.com.br"}) == "a@superfrio.com.br"
    assert provisioning.email_from_claims({"upn": "b@superfrio.com.br"}) == "b@superfrio.com.br"
    assert provisioning.email_from_claims({}) is None


def test_is_group_allowed_sem_grupo_exigido_libera_todos():
    assert provisioning.is_group_allowed({}, "") is True


def test_is_group_allowed_com_grupo_exigido():
    assert provisioning.is_group_allowed({"groups": ["g1", "g2"]}, "g2") is True
    assert provisioning.is_group_allowed({"groups": ["g1"]}, "g2") is False
    assert provisioning.is_group_allowed({}, "g2") is False


def test_resolve_user_sem_email_recusa():
    with db() as session:
        user, motivo = provisioning.resolve_user(session, {}, "")
    assert user is None
    assert motivo == provisioning.RECUSA_SEM_EMAIL


def test_resolve_user_fora_do_grupo_recusa():
    with db() as session:
        claims = {"email": "admin@superfrio.com.br", "groups": ["outro"]}
        user, motivo = provisioning.resolve_user(session, claims, "grupo-exigido")
    assert user is None
    assert motivo == provisioning.RECUSA_FORA_DO_GRUPO


def test_resolve_user_existente_reaproveita_cadastro():
    with db() as session:
        user, motivo = provisioning.resolve_user(session, {"email": "admin@superfrio.com.br"}, "")
    assert motivo == provisioning.OK
    assert user is not None
    assert user["username"] == "admin"
    assert user["is_admin"] == 1


def test_resolve_user_sem_cadastro_recusa_quando_auto_provision_desligado():
    """Decisao de 2026-08-21: cadastro previo e obrigatorio por padrao — quem nao
    tem cadastro e recusado e NADA e gravado na tabela de usuarios."""
    email = "sem.cadastro@superfrio.com.br"
    with db() as session:
        user, motivo = provisioning.resolve_user(session, {"email": email}, "")
    assert user is None
    assert motivo == provisioning.RECUSA_SEM_CADASTRO
    with db() as session:
        assert usuarios_service.por_email(session, email, apenas_ativos=False) is None


def test_resolve_user_desativado_recusa_e_nao_recria():
    """Regressao do 500 em producao (2026-08-21): o usuario desativado ficava
    invisivel na busca (`apenas_ativos=True` era o default) e o codigo concluia
    "usuario novo", tentando inserir de novo e violando o UNIQUE de `username`.

    Vale mesmo com o auto-provisionamento LIGADO: desativado e recusa, sempre."""
    email = "desativado.sso@superfrio.com.br"
    try:
        with db() as session:
            novo = usuarios_service.provisionar_usuario_ad(session, email, "Desativado")
            session.execute(
                text("UPDATE usuarios SET ativo = 0 WHERE id = :i"), {"i": novo["id"]}
            )
        with db() as session:
            user, motivo = provisioning.resolve_user(
                session, {"email": email}, "", auto_provision=True
            )
        assert user is None
        assert motivo == provisioning.RECUSA_DESATIVADO
        with db() as session:
            qtd = session.execute(
                text("SELECT count(*) FROM usuarios WHERE email = :e"), {"e": email}
            ).scalar()
        assert qtd == 1  # nao criou um segundo cadastro
    finally:
        with db() as session:
            session.execute(text("DELETE FROM usuarios WHERE email = :e"), {"e": email})


def test_resolve_user_novo_provisiona_sem_role_e_sem_senha():
    email = "novo.sso@superfrio.com.br"
    try:
        with db() as session:
            user, motivo = provisioning.resolve_user(
                session, {"email": email, "name": "Novo SSO"}, "", auto_provision=True
            )
        assert motivo == provisioning.OK
        assert user is not None
        assert user["auth_source"] == "ad"
        assert user["password_hash"] is None
        assert user["is_admin"] == 0
        with db() as session:
            assert usuarios_service.permissoes_do_usuario(session, user["id"]) == set()
    finally:
        with db() as conn:
            conn.execute(text("DELETE FROM usuarios WHERE email = :e"), {"e": email})


def test_resolve_user_email_case_insensitive_nao_duplica():
    with db() as session:
        primeira, _ = provisioning.resolve_user(session, {"email": "ADMIN@superfrio.com.br"}, "")
    assert primeira["username"] == "admin"  # casou com o usuário seed, não criou outro


# ---------- endpoint: /api/auth/config, /login/entra, /callback ----------

def test_config_dormente_por_padrao(client):
    assert client.get("/api/auth/config").json() == {"sso_enabled": False}


def test_login_entra_501_enquanto_dormente(client):
    r = client.get("/api/auth/login/entra", follow_redirects=False)
    assert r.status_code == 501


def test_callback_501_enquanto_dormente(client):
    r = client.get("/api/auth/callback", follow_redirects=False)
    assert r.status_code == 501


def test_config_true_quando_ligado(client, monkeypatch):
    _ligar_sso(monkeypatch)
    assert client.get("/api/auth/config").json() == {"sso_enabled": True}


def test_login_entra_redireciona_e_seta_cookie_state(client, monkeypatch):
    _ligar_sso(monkeypatch)
    _mock_authorization_url(monkeypatch)
    r = client.get("/api/auth/login/entra", follow_redirects=False)
    assert r.status_code == 307
    assert "login.microsoftonline.com" in r.headers["location"]
    assert client.cookies.get("sf_entra_state")


def test_callback_sem_state_volta_pro_login_em_vez_de_400(client, monkeypatch):
    """Regressao da tela branca de JSON (2026-08-21): o Voltar do navegador
    reexecuta esta URL com um `code` ja usado e sem o cookie de state. Isso nao
    pode virar 400 no meio de uma navegacao de topo."""
    _ligar_sso(monkeypatch)
    r = client.get("/api/auth/callback", params={"code": "x", "state": "y"}, follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"] == "/#sso_erro=sessao"


def test_callback_state_nao_bate_volta_pro_login(client, monkeypatch):
    _ligar_sso(monkeypatch)
    _mock_authorization_url(monkeypatch)
    client.get("/api/auth/login/entra", follow_redirects=False)
    r = client.get(
        "/api/auth/callback", params={"code": "x", "state": "adulterado"}, follow_redirects=False
    )
    assert r.status_code == 307
    assert r.headers["location"] == "/#sso_erro=sessao"


def test_callback_error_do_microsoft_volta_pro_login(client, monkeypatch):
    _ligar_sso(monkeypatch)
    r = client.get("/api/auth/callback", params={"error": "access_denied"}, follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"] == "/#sso_erro=microsoft"


def _iniciar_e_capturar_state(client) -> str:
    r = client.get("/api/auth/login/entra", follow_redirects=False)
    return parse_qs(urlparse(r.headers["location"]).query)["state"][0]


def test_callback_token_invalido_volta_pro_login(client, monkeypatch):
    _ligar_sso(monkeypatch)
    _mock_authorization_url(monkeypatch)
    _mock_exchange_code(monkeypatch, None)
    state = _iniciar_e_capturar_state(client)
    r = client.get("/api/auth/callback", params={"code": "x", "state": state}, follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"] == "/#sso_erro=microsoft"


def test_callback_sem_claim_de_email_volta_pro_login(client, monkeypatch):
    _ligar_sso(monkeypatch)
    _mock_authorization_url(monkeypatch)
    _mock_exchange_code(monkeypatch, {})  # sem claim de e-mail -> resolve_user recusa
    state = _iniciar_e_capturar_state(client)
    r = client.get("/api/auth/callback", params={"code": "x", "state": state}, follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"] == "/#sso_erro=sem_email"


def test_callback_sem_cadastro_recusa_e_nao_grava(client, monkeypatch):
    """Comportamento padrao a partir de 2026-08-21: sem cadastro previo, a pessoa
    recebe a mensagem certa na tela de login e a tabela de usuarios nao muda."""
    email = "ninguem.novo@superfrio.com.br"
    _ligar_sso(monkeypatch)  # auto-provisionamento fica DESLIGADO
    _mock_authorization_url(monkeypatch)
    _mock_exchange_code(monkeypatch, {"email": email, "name": "Ninguem"})
    state = _iniciar_e_capturar_state(client)
    r = client.get("/api/auth/callback", params={"code": "x", "state": state}, follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"] == "/#sso_erro=sem_cadastro"
    with db() as session:
        assert usuarios_service.por_email(session, email, apenas_ativos=False) is None


def test_callback_usuario_desativado_nao_da_500(client, monkeypatch):
    """Regressao do 500 (UniqueViolation) que travou um usuario real desativado
    em producao em 2026-08-21."""
    email = "bloqueado.sso@superfrio.com.br"
    _ligar_sso(monkeypatch)
    monkeypatch.setattr(entra_module, "ENTRA_AUTO_PROVISION", True)  # pior caso
    _mock_authorization_url(monkeypatch)
    _mock_exchange_code(monkeypatch, {"email": email, "name": "Bloqueado"})
    try:
        with db() as session:
            novo = usuarios_service.provisionar_usuario_ad(session, email, "Bloqueado")
            session.execute(
                text("UPDATE usuarios SET ativo = 0 WHERE id = :i"), {"i": novo["id"]}
            )
        state = _iniciar_e_capturar_state(client)
        r = client.get(
            "/api/auth/callback", params={"code": "x", "state": state}, follow_redirects=False
        )
        assert r.status_code == 307
        assert r.headers["location"] == "/#sso_erro=desativado"
    finally:
        with db() as session:
            session.execute(text("DELETE FROM usuarios WHERE email = :e"), {"e": email})


def test_callback_ok_devolve_token_no_fragmento(client, monkeypatch):
    _ligar_sso(monkeypatch)
    _mock_authorization_url(monkeypatch)
    _mock_exchange_code(monkeypatch, {"email": "admin@superfrio.com.br", "name": "Administrador"})
    state = _iniciar_e_capturar_state(client)
    r = client.get("/api/auth/callback", params={"code": "x", "state": state}, follow_redirects=False)
    assert r.status_code == 307
    location = r.headers["location"]
    assert location.startswith("/#sso_token=")
    token = location.split("sso_token=", 1)[1]

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["username"] == "admin"


def test_callback_novo_usuario_via_sso_e_criado_ad(client, monkeypatch):
    """Com ENTRA_AUTO_PROVISION=1 o comportamento antigo (JIT) volta intacto."""
    email = "primeiro.acesso@superfrio.com.br"
    _ligar_sso(monkeypatch)
    monkeypatch.setattr(entra_module, "ENTRA_AUTO_PROVISION", True)
    _mock_authorization_url(monkeypatch)
    _mock_exchange_code(monkeypatch, {"email": email, "name": "Primeiro Acesso"})
    try:
        state = _iniciar_e_capturar_state(client)
        r = client.get(
            "/api/auth/callback", params={"code": "x", "state": state}, follow_redirects=False
        )
        assert r.status_code == 307
        with db() as session:
            user = usuarios_service.por_email(session, email)
        assert user is not None
        assert user["auth_source"] == "ad"
        assert user["is_admin"] == 0
    finally:
        with db() as conn:
            conn.execute(text("DELETE FROM usuarios WHERE email = :e"), {"e": email})


def test_provisionar_usuario_ad_em_corrida_reaproveita_cadastro():
    """Dois primeiros logins simultâneos (duas abas): o segundo insert viola o
    UNIQUE de `username`. Com o SAVEPOINT em `provisionar_usuario_ad`, a violação
    desfaz só o insert e devolve o cadastro que venceu — antes ela derrubava a
    transação inteira e o callback do SSO respondia 500."""
    email = "corrida.sso@superfrio.com.br"
    try:
        with db() as session:
            primeiro = usuarios_service.provisionar_usuario_ad(session, email, "Corrida")
            segundo = usuarios_service.provisionar_usuario_ad(session, email, "Corrida")
            # a transação continua utilizável depois da violação (o que o savepoint garante)
            assert usuarios_service.por_email(session, email) is not None
        assert primeiro is not None and segundo is not None
        assert segundo["id"] == primeiro["id"]
        with db() as session:
            qtd = session.execute(
                text("SELECT count(*) FROM usuarios WHERE email = :e"), {"e": email}
            ).scalar()
        assert qtd == 1
    finally:
        with db() as session:
            session.execute(text("DELETE FROM usuarios WHERE email = :e"), {"e": email})
