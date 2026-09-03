"""Fase 1 — auditoria núcleo (docs/AUDITORIA_FUNCIONAL.md).

Cobre: migration/trigger de imutabilidade, os seis eventos de auth/acesso,
diff em mutação administrativa (com atomicidade), leitura/exportação
restritas a admin, catálogo fechado usado de fato no código, e o
X-Request-ID ligando log e evento.
"""
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import select, text

from backend.auditoria import catalogo
from backend.auditoria import service as auditoria_service
from backend.auth import entra as entra_module
from backend.auditoria.models import AuditoriaEvento
from backend.core.database import _alembic_config, db

# ============ Migration + trigger ============


def test_migration_0008_sobe_e_desce(tmp_path):
    from alembic import command

    url = f"sqlite:///{(tmp_path / 'auditoria_updown.db').as_posix()}"
    cfg = _alembic_config(url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "0007")
    command.upgrade(cfg, "head")


def test_trigger_recusa_update_no_sqlite():
    with db() as session:
        session.execute(text(
            "INSERT INTO auditoria_eventos (ocorrido_em, categoria, acao, resultado) "
            "VALUES ('2026-01-01 00:00:00', 'auditoria', 'auditoria.consultar', 'ok')"
        ))
    with db() as session:
        id_ = session.execute(select(AuditoriaEvento.id)).scalars().first()
    with pytest.raises(Exception, match="append-only"):
        with db() as session:
            session.execute(
                text("UPDATE auditoria_eventos SET resultado = 'erro' WHERE id = :i"), {"i": id_}
            )


def test_trigger_recusa_delete_no_sqlite():
    with db() as session:
        session.execute(text(
            "INSERT INTO auditoria_eventos (ocorrido_em, categoria, acao, resultado) "
            "VALUES ('2026-01-01 00:00:00', 'auditoria', 'auditoria.consultar', 'ok')"
        ))
    with db() as session:
        id_ = session.execute(select(AuditoriaEvento.id)).scalars().first()
    with pytest.raises(Exception, match="append-only"):
        with db() as session:
            session.execute(text("DELETE FROM auditoria_eventos WHERE id = :i"), {"i": id_})


# ============ Login local ============


def _ultimo_evento(session, **filtro):
    stmt = select(AuditoriaEvento.__table__).order_by(AuditoriaEvento.id.desc())
    for campo, valor in filtro.items():
        stmt = stmt.where(getattr(AuditoriaEvento, campo) == valor)
    row = session.execute(stmt).mappings().first()
    return dict(row) if row else None


def test_login_ok_grava_evento(client):
    r = client.post("/api/auth/login", data={"username": "admin", "password": "admin123"})
    assert r.status_code == 200
    with db() as session:
        evento = _ultimo_evento(session, categoria="auth", acao="login.ok")
    assert evento is not None
    assert evento["resultado"] == "ok"
    assert evento["ator_username"] == "admin"


def test_login_falha_grava_evento_sem_senha_nos_detalhes(client):
    r = client.post("/api/auth/login", data={"username": "admin", "password": "senha-errada"})
    assert r.status_code == 401
    with db() as session:
        evento = _ultimo_evento(session, categoria="auth", acao="login.falha")
    assert evento is not None
    assert evento["resultado"] == "negado"
    assert evento["ator_username"] is None
    assert "senha-errada" not in evento["detalhes"]
    assert "senha" not in evento["detalhes"]


def test_logout_grava_evento(client, admin_headers):
    r = client.post("/api/auth/logout", headers=admin_headers)
    assert r.status_code == 204
    with db() as session:
        evento = _ultimo_evento(session, categoria="auth", acao="logout")
    assert evento is not None
    assert evento["ator_username"] == "admin"


def test_logout_sem_token_nao_estoura(client):
    r = client.post("/api/auth/logout")
    assert r.status_code == 204


# ============ SSO ============


def _ligar_sso(monkeypatch):
    monkeypatch.setattr(entra_module, "ENTRA_TENANT_ID", "fake-tenant")
    monkeypatch.setattr(entra_module, "ENTRA_CLIENT_ID", "fake-client")
    monkeypatch.setattr(entra_module, "ENTRA_CLIENT_SECRET", "fake-secret")
    monkeypatch.setattr(entra_module, "ENTRA_REDIRECT_URI", "http://localhost:8000/api/auth/callback")
    monkeypatch.setattr(entra_module, "ENTRA_AUTO_PROVISION", False)


def _mock_authorization_url(monkeypatch):
    monkeypatch.setattr(
        entra_module.EntraAuthProvider,
        "authorization_url",
        lambda self, state: f"https://login.microsoftonline.com/fake/authorize?state={state}",
    )


def _mock_exchange_code(monkeypatch, claims):
    monkeypatch.setattr(entra_module.EntraAuthProvider, "exchange_code", lambda self, code: claims)


def _iniciar_e_capturar_state(client) -> str:
    r = client.get("/api/auth/login/entra", follow_redirects=False)
    return parse_qs(urlparse(r.headers["location"]).query)["state"][0]


def test_sso_ok_grava_evento(client, monkeypatch):
    _ligar_sso(monkeypatch)
    _mock_authorization_url(monkeypatch)
    _mock_exchange_code(monkeypatch, {"email": "admin@superfrio.com.br", "name": "Administrador"})
    state = _iniciar_e_capturar_state(client)
    r = client.get("/api/auth/callback", params={"code": "x", "state": state}, follow_redirects=False)
    assert r.status_code == 307
    with db() as session:
        evento = _ultimo_evento(session, categoria="auth", acao="sso.ok")
    assert evento is not None
    assert evento["ator_username"] == "admin"


def test_sso_recusado_grava_evento_sem_code_nem_state(client, monkeypatch):
    email = "ninguem.auditoria@superfrio.com.br"
    _ligar_sso(monkeypatch)
    _mock_authorization_url(monkeypatch)
    _mock_exchange_code(monkeypatch, {"email": email, "name": "Ninguem"})
    state = _iniciar_e_capturar_state(client)
    r = client.get("/api/auth/callback", params={"code": "codigo-secreto", "state": state}, follow_redirects=False)
    assert r.status_code == 307
    with db() as session:
        evento = _ultimo_evento(session, categoria="auth", acao="sso.recusado")
    assert evento is not None
    assert evento["resultado"] == "negado"
    assert "sem_cadastro" in evento["detalhes"]
    assert "codigo-secreto" not in evento["detalhes"]
    assert "code" not in evento["detalhes"]
    assert "state" not in evento["detalhes"]


# ============ app.abrir / acesso.negado ============


def test_app_abrir_grava_evento_quando_permitido(client, operador_headers):
    r = client.post("/api/portal/abrir/faq-blueyonder", headers=operador_headers)
    assert r.status_code == 200
    assert r.json()["url"]
    with db() as session:
        evento = _ultimo_evento(session, categoria="acesso", acao="app.abrir")
    assert evento is not None
    assert evento["app_slug"] == "faq-blueyonder"
    assert evento["resultado"] == "ok"


def test_app_abrir_403_grava_acesso_negado(client, operador_headers):
    r = client.post("/api/portal/abrir/duvidas-financeiro", headers=operador_headers)
    assert r.status_code == 403
    with db() as session:
        evento = _ultimo_evento(session, categoria="acesso", acao="acesso.negado")
    assert evento is not None
    assert evento["app_slug"] == "duvidas-financeiro"
    assert evento["resultado"] == "negado"


def test_require_admin_403_grava_acesso_negado(client, operador_headers):
    r = client.get("/api/admin/usuarios", headers=operador_headers)
    assert r.status_code == 403
    with db() as session:
        evento = _ultimo_evento(session, categoria="acesso", acao="acesso.negado")
    assert evento is not None
    assert evento["detalhes"]  # rota + exigia


# ============ Diff em mutação administrativa (e atomicidade) ============


def test_usuario_atualizar_grava_diff(client, admin_headers):
    criado = client.post(
        "/api/admin/usuarios",
        json={"username": "auditoria.diff.teste", "senha": "senhaforte123", "nome": "Antes"},
        headers=admin_headers,
    ).json()
    r = client.patch(
        f"/api/admin/usuarios/{criado['id']}", json={"nome": "Depois"}, headers=admin_headers
    )
    assert r.status_code == 200
    with db() as session:
        evento = _ultimo_evento(session, categoria="admin", acao="usuario.atualizar")
    assert evento is not None
    assert '"de": "Antes"' in evento["detalhes"]
    assert '"para": "Depois"' in evento["detalhes"]


def test_role_atualizar_grava_adicionados_e_removidos(client, admin_headers):
    criada = client.post(
        "/api/admin/roles",
        json={"slug": "role-auditoria-teste", "nome": "Teste", "apps": ["faq-blueyonder"]},
        headers=admin_headers,
    ).json()
    r = client.patch(
        f"/api/admin/roles/{criada['id']}", json={"apps": ["faq-slin"]}, headers=admin_headers
    )
    assert r.status_code == 200
    with db() as session:
        evento = _ultimo_evento(session, categoria="admin", acao="role.atualizar")
    assert evento is not None
    assert '"adicionados": ["faq-slin"]' in evento["detalhes"]
    assert '"removidos": ["faq-blueyonder"]' in evento["detalhes"]


def test_falha_ao_registrar_evento_desfaz_a_mutacao(client, admin_headers, monkeypatch):
    """Prova a atomicidade: se `registrar()` estourar, a mutação inteira não
    commita — mesmo comportamento de qualquer outra falha dentro do `with db()`."""
    criado = client.post(
        "/api/admin/usuarios",
        json={"username": "auditoria.atomico.teste", "senha": "senhaforte123", "nome": "Original"},
        headers=admin_headers,
    ).json()

    def _estoura(*args, **kwargs):
        raise RuntimeError("falha proposital de auditoria")

    monkeypatch.setattr(auditoria_service, "registrar", _estoura)
    # TestClient (raise_server_exceptions=True, o padrão) repropaga a exceção
    # do servidor em vez de virar resposta 500 — é o comportamento documentado
    # do cliente de teste, não da aplicação real.
    with pytest.raises(RuntimeError, match="falha proposital de auditoria"):
        client.patch(
            f"/api/admin/usuarios/{criado['id']}", json={"nome": "Não Deveria Persistir"}, headers=admin_headers
        )
    monkeypatch.undo()

    with db() as session:
        from backend.usuarios.models import Usuario
        nome = session.execute(select(Usuario.nome).where(Usuario.id == criado["id"])).scalar_one()
    assert nome == "Original"


# ============ Leitura e exportação ============


def test_listar_exige_admin(client, operador_headers):
    r = client.get("/api/admin/auditoria", headers=operador_headers)
    assert r.status_code == 403


def test_listar_pagina_e_filtra(client, admin_headers):
    client.post("/api/auth/logout", headers=admin_headers)
    r = client.get("/api/admin/auditoria", params={"categoria": "auth", "acao": "logout", "por_pagina": 5}, headers=admin_headers)
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["total"] >= 1
    assert all(item["categoria"] == "auth" and item["acao"] == "logout" for item in corpo["itens"])


def test_exportar_gera_csv_e_grava_evento(client, admin_headers):
    r = client.get("/api/admin/auditoria/exportar", headers=admin_headers)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    conteudo = r.content.decode("utf-8-sig")
    assert conteudo.startswith("ocorrido_em;")
    with db() as session:
        evento = _ultimo_evento(session, categoria="auditoria", acao="auditoria.exportar")
    assert evento is not None


# ============ Catálogo fechado, de verdade usado no código ============

_ARQUIVOS_INSTRUMENTADOS = (
    "backend/main.py",
    "backend/auth/router.py",
    "backend/auth/dependencies.py",
    "backend/portal/router.py",
    "backend/usuarios/router.py",
    "backend/projetos_ia/router.py",
    "backend/processos_abertos/router.py",
    "backend/integracao_in_out/router.py",
    "backend/auditoria/router.py",
)
_PADRAO_EVENTO = re.compile(r'categoria="([a-z]+)",\s*acao="([a-z0-9\-\.]+)"')


def test_todo_evento_usado_no_codigo_esta_no_catalogo():
    raiz = Path(__file__).resolve().parent.parent
    usados = set()
    for relativo in _ARQUIVOS_INSTRUMENTADOS:
        texto = (raiz / relativo).read_text(encoding="utf-8")
        usados.update(_PADRAO_EVENTO.findall(texto))
    assert len(usados) >= 15, "poucos eventos encontrados — a regex ficou desatualizada?"
    for categoria, acao in usados:
        catalogo.validar(categoria, acao)  # levanta ValueError se não existir


def test_registrar_com_evento_fora_do_catalogo_estoura():
    with pytest.raises(ValueError):
        auditoria_service.registrar(categoria="auth", acao="nao-existe", resultado="ok")


# ============ Correlação ============


def test_x_request_id_presente_e_ligado_ao_evento(client, admin_headers):
    r = client.post("/api/auth/logout", headers=admin_headers)
    assert "X-Request-ID" in r.headers
    with db() as session:
        evento = _ultimo_evento(session, categoria="auth", acao="logout")
    assert evento["correlacao_id"] == r.headers["X-Request-ID"]
