"""SuperfrioIA — a chave `IA_HABILITADO` (DD-27).

Desligada: rotas 404 e o card some **mesmo que o registro exista no banco com
`ativo = 1`**. Provado ligando e desligando no MESMO processo, sem reiniciar: é por
isso que a chave é lida a cada requisição e as rotas ficam sempre registradas.
"""
import pytest
from sqlalchemy import select

from backend.core.database import db
from backend.ia import retencao
from backend.portal import seed as portal_seed
from backend.portal.models import App

ROTAS = [
    ("GET", "/api/ia/dominios", None),
    ("POST", "/api/ia/perguntas", {"dominio": "volumetria-catering", "pergunta": "oi"}),
    ("GET", "/api/ia/conversas", None),
    ("GET", "/api/ia/conversas/1", None),
    ("POST", "/api/ia/mensagens/1/feedback", {"valor": 1}),
    ("POST", "/api/ia/concessoes/pedidos", {"dominio": "volumetria-catering", "motivo": "x"}),
    ("GET", "/api/ia/concessoes/minhas", None),
    ("GET", "/api/ia/administracao/concessoes?dominio=volumetria-catering", None),
    ("POST", "/api/ia/administracao/concessoes/1/aprovar", {}),
    ("POST", "/api/ia/administracao/concessoes/1/negar", {"motivo": "x"}),
    ("POST", "/api/ia/administracao/concessoes/1/revogar", {"motivo": "x"}),
]


def _slugs_da_home(client, headers) -> set[str]:
    home = client.get("/api/portal/home", headers=headers).json()
    return ({a["slug"] for a in home["indicadores"]}
            | {a["slug"] for s in home["secoes"] for a in s["apps"]})


def _slugs_dos_sistemas(client, headers) -> set[str]:
    return {a["slug"] for a in client.get("/api/portal/sistemas", headers=headers).json()}


def _app_no_banco():
    with db() as session:
        return session.execute(select(App.__table__).where(App.slug == "superfrioia")).mappings().first()


def test_ligar_desligar_e_ligar_de_novo_no_mesmo_processo(client, ia_ligada, admin_headers, monkeypatch):
    # 1) ligada: rotas respondem, o card aparece e abre
    assert client.get("/api/ia/dominios", headers=admin_headers).status_code == 200
    assert "superfrioia" in _slugs_da_home(client, admin_headers)
    assert "superfrioia" in _slugs_dos_sistemas(client, admin_headers)
    assert client.post("/api/portal/abrir/superfrioia", headers=admin_headers).status_code == 200

    # 2) desligada, com o registro do app AINDA ativo no banco
    monkeypatch.setenv("IA_HABILITADO", "false")
    assert _app_no_banco()["ativo"] == 1
    for metodo, rota, corpo in ROTAS:
        r = client.request(metodo, rota, headers=admin_headers, json=corpo) if corpo is not None \
            else client.request(metodo, rota, headers=admin_headers)
        assert r.status_code == 404, f"{metodo} {rota}"
    assert "superfrioia" not in _slugs_da_home(client, admin_headers)
    assert "superfrioia" not in _slugs_dos_sistemas(client, admin_headers)
    assert client.post("/api/portal/abrir/superfrioia", headers=admin_headers).status_code == 404

    # 3) ligada de novo: tudo volta, sem reiniciar
    monkeypatch.setenv("IA_HABILITADO", "true")
    assert client.get("/api/ia/dominios", headers=admin_headers).status_code == 200
    assert "superfrioia" in _slugs_da_home(client, admin_headers)
    assert client.post("/api/portal/abrir/superfrioia", headers=admin_headers).status_code == 200


def test_desligada_o_card_some_para_usuario_comum_tambem(client, usuario_ia, monkeypatch):
    assert "superfrioia" in _slugs_da_home(client, usuario_ia["headers"])
    monkeypatch.setenv("IA_HABILITADO", "false")
    assert "superfrioia" not in _slugs_da_home(client, usuario_ia["headers"])
    assert client.post("/api/portal/abrir/superfrioia", headers=usuario_ia["headers"]).status_code == 404


def test_desligada_a_rota_responde_404_antes_da_autenticacao(client, monkeypatch):
    """Nada vaza que o módulo existe: sem token, 404 (e não 401)."""
    monkeypatch.setenv("IA_HABILITADO", "false")
    assert client.get("/api/ia/dominios").status_code == 404
    monkeypatch.setenv("IA_HABILITADO", "true")
    assert client.get("/api/ia/dominios").status_code == 401


@pytest.mark.parametrize("valor", [None, "", "false", "0", "nao", "FALSE"])
def test_o_padrao_e_desligada(client, admin_headers, monkeypatch, valor):
    if valor is None:
        monkeypatch.delenv("IA_HABILITADO", raising=False)
    else:
        monkeypatch.setenv("IA_HABILITADO", valor)
    assert client.get("/api/ia/dominios", headers=admin_headers).status_code == 404


def test_seed_com_a_chave_desligada_nao_cria_o_card(monkeypatch):
    monkeypatch.setenv("IA_HABILITADO", "false")
    assert _app_no_banco() is None
    with db() as session:
        criados = portal_seed.seed(session)
    assert "superfrioia" not in criados
    assert _app_no_banco() is None


def test_seed_com_a_chave_desligada_nao_apaga_um_card_existente(ia_ligada, monkeypatch):
    assert _app_no_banco() is not None
    monkeypatch.setenv("IA_HABILITADO", "false")
    with db() as session:
        portal_seed.seed(session)
    assert _app_no_banco() is not None                     # o registro continua; só fica escondido


def test_seed_com_a_chave_ligada_cria_o_card_uma_vez(ia_ligada):
    with db() as session:
        assert "superfrioia" not in portal_seed.seed(session)   # segunda vez: idempotente
    app = _app_no_banco()
    assert app["tipo_acesso"] == "interno" and app["url"] == "/superfrioia"


def test_a_listagem_administrativa_continua_mostrando_o_registro(client, ia_ligada, admin_headers, monkeypatch):
    """Decisão: o admin gerencia o cadastro mesmo com a chave desligada; esconder
    é da porta de entrada (home, sistemas, abrir), não do cadastro."""
    monkeypatch.setenv("IA_HABILITADO", "false")
    slugs = {a["slug"] for a in client.get("/api/admin/apps", headers=admin_headers).json()}
    assert "superfrioia" in slugs


def test_a_retencao_continua_rodando_com_a_chave_desligada(monkeypatch):
    monkeypatch.setenv("IA_HABILITADO", "false")
    contagens = retencao.executar()
    assert set(contagens) >= {"mensagens", "conversas", "consultas"}
