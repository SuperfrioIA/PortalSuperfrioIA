"""SuperfrioIA — pedido, aprovação, revogação e vencimento da concessão de uso.

O que `volumetria-catering:administrar` autoriza, e o que não autoriza (DD-13).
"""
import pytest
from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError

from backend.core.database import db
from backend.ia.models import IaConcessao
from ia_ajuda import DOMINIO, perguntar_http

BASE = "/api/ia"
T = IaConcessao.__table__


def pedir(client, u, motivo="preciso consultar a volumetria", esperado=201):
    r = client.post(f"{BASE}/concessoes/pedidos", headers=u["headers"], json={"dominio": DOMINIO, "motivo": motivo})
    assert r.status_code == esperado, r.text
    return r.json()


def decidir(client, quem, concessao_id, acao, corpo=None, esperado=200):
    r = client.post(f"{BASE}/administracao/concessoes/{concessao_id}/{acao}",
                    headers=quem["headers"] if "headers" in quem else quem, json=corpo or {})
    assert r.status_code == esperado, r.text
    return r.json()


@pytest.fixture
def aprovador(ia_ligada, criar_usuario_ia):
    """Quem tem SÓ `volumetria-catering:administrar` (e o card). Não é admin do Hub."""
    return criar_usuario_ia("aprovador", administrar=True, ver_sistema=False)


# =================================================================== o fluxo
def test_pedido_fica_pendente_e_a_pessoa_ainda_nao_pergunta(client, ia_ligada, ia_dw, criar_usuario_ia):
    ia_dw()
    u = criar_usuario_ia("pedinte")
    estado = client.get(f"{BASE}/dominios", headers=u["headers"]).json()[0]["acesso"]
    assert estado["estado"] == "sem_concessao"
    pedido = pedir(client, u)
    assert pedido["status"] == "pendente" and pedido["vigente"] is False
    assert client.get(f"{BASE}/dominios", headers=u["headers"]).json()[0]["acesso"]["estado"] == "pendente"
    perguntar_http(client, u, "Quanto entrou em agosto?", esperado=403)


def test_aprovacao_por_quem_tem_so_administrar_libera(client, ia_ligada, ia_dw, criar_usuario_ia, aprovador):
    """P4: aprovado por quem tem `<dominio>:administrar` e NÃO é admin do Hub."""
    ia_dw()
    u = criar_usuario_ia("pedinte")
    decisao = decidir(client, aprovador, pedir(client, u)["id"], "aprovar", {"motivo": "ok, time de catering"})
    assert decisao["status"] == "ativa" and decisao["vigente"] and decisao["autoaprovacao"] is False
    assert decisao["decidido_por"] == aprovador["username"]
    assert perguntar_http(client, u, "Quanto de peso líquido entrou em agosto?")["estado"] == "ok"


def test_validade_padrao_e_180_dias_e_pode_ser_definida(client, ia_ligada, criar_usuario_ia, aprovador):
    from datetime import datetime, timedelta, timezone
    a, b = criar_usuario_ia("a"), criar_usuario_ia("b")
    padrao = decidir(client, aprovador, pedir(client, a)["id"], "aprovar")
    curta = decidir(client, aprovador, pedir(client, b)["id"], "aprovar", {"validade_dias": 30})

    def dias(linha):
        validade = datetime.strptime(linha["validade_ate"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        return round((validade - datetime.now(timezone.utc)) / timedelta(days=1))

    assert dias(padrao) == 180 and dias(curta) == 30
    assert curta["vence_em_30_dias"] is True and padrao["vence_em_30_dias"] is False


def test_validade_invalida_e_recusada(client, ia_ligada, criar_usuario_ia, aprovador):
    u = criar_usuario_ia("v")
    pid = pedir(client, u)["id"]
    for dias in (0, 366, -5):
        decidir(client, aprovador, pid, "aprovar", {"validade_dias": dias}, esperado=400)


def test_negar_exige_motivo_e_fecha_o_pedido(client, ia_ligada, ia_dw, criar_usuario_ia, aprovador):
    ia_dw()
    u = criar_usuario_ia("negado")
    pid = pedir(client, u)["id"]
    decidir(client, aprovador, pid, "negar", {"motivo": "  "}, esperado=400)
    assert decidir(client, aprovador, pid, "negar", {"motivo": "fora do escopo"})["status"] == "negada"
    assert client.get(f"{BASE}/dominios", headers=u["headers"]).json()[0]["acesso"]["motivo"] == "fora do escopo"
    perguntar_http(client, u, "Quanto entrou em agosto?", esperado=403)
    decidir(client, aprovador, pid, "aprovar", esperado=409)          # já decidido
    pedir(client, u)                                                  # e pode pedir de novo


def test_pedido_duplicado_e_pedido_de_quem_ja_tem_acesso_dao_409(client, usuario_ia, criar_usuario_ia):
    pedir(client, usuario_ia, esperado=409)                           # já tem acesso vigente
    outro = criar_usuario_ia("duplo")
    pedir(client, outro)
    pedir(client, outro, esperado=409)                                # segundo pendente


def test_o_banco_garante_um_pendente_e_uma_ativa_por_usuario_e_dominio(usuario_ia):
    """Índice único parcial: vale mesmo se o código errar ou houver corrida."""
    base = dict(usuario_id=usuario_ia["id"], username=usuario_ia["username"], dominio=DOMINIO,
                motivo_pedido="x", autoaprovacao=0)
    with pytest.raises(IntegrityError):
        with db() as session:
            session.execute(insert(IaConcessao).values(status="ativa", validade_ate="2999-01-01 00:00:00", **base))
    with db() as session:
        session.execute(insert(IaConcessao).values(status="pendente", **base))
    with pytest.raises(IntegrityError):
        with db() as session:
            session.execute(insert(IaConcessao).values(status="pendente", **base))


def test_renovacao_revoga_a_anterior_e_so_uma_fica_ativa(client, usuario_ia, aprovador):
    antiga = usuario_ia["concessao_id"]
    # a concessão vigente impede novo pedido; vence a antiga para poder renovar
    with db() as session:
        session.execute(update(T).where(T.c.id == antiga).values(validade_ate="2000-01-01 00:00:00"))
    nova = decidir(client, aprovador, pedir(client, usuario_ia)["id"], "aprovar")
    with db() as session:
        status = dict(session.execute(select(T.c.id, T.c.status).where(T.c.usuario_id == usuario_ia["id"])).all())
    assert status[nova["id"]] == "ativa" and status[antiga] == "revogada"


# ================================================================= revogação
def test_revogar_vale_na_proxima_pergunta_e_fecha_o_historico(client, usuario_ia, aprovador):
    primeira = perguntar_http(client, usuario_ia, "Quanto de peso líquido entrou em agosto?")
    cid = primeira["conversa_id"]
    assert client.get(f"{BASE}/conversas/{cid}", headers=usuario_ia["headers"]).status_code == 200

    decidir(client, aprovador, usuario_ia["concessao_id"], "revogar", {"motivo": "mudou de área"})

    perguntar_http(client, usuario_ia, "Quanto entrou em setembro?", conversa_id=cid, esperado=403)
    r = client.get(f"{BASE}/conversas/{cid}", headers=usuario_ia["headers"])
    assert r.status_code == 403 and "revogado" in r.json()["detail"]
    lista = client.get(f"{BASE}/conversas", headers=usuario_ia["headers"]).json()
    assert lista[0]["acesso_revogado"] is True and lista[0]["titulo"] == "(acesso revogado)"
    assert client.get(f"{BASE}/dominios", headers=usuario_ia["headers"]).json()[0]["acesso"]["estado"] == "revogada"


def test_revogar_no_meio_da_conversa_nega_a_proxima_e_nao_a_anterior_ja_gravada(client, usuario_ia, aprovador):
    perguntar_http(client, usuario_ia, "Quanto entrou em agosto?")
    decidir(client, aprovador, usuario_ia["concessao_id"], "revogar", {"motivo": "x"})
    perguntar_http(client, usuario_ia, "Quanto entrou em agosto?", esperado=403)
    decidir(client, aprovador, usuario_ia["concessao_id"], "revogar", {"motivo": "x"}, esperado=409)  # só ativa se revoga


def test_concessao_vencida_nega_no_segundo_exato(client, usuario_ia):
    perguntar_http(client, usuario_ia, "Quanto entrou em agosto?")
    with db() as session:
        session.execute(update(T).where(T.c.id == usuario_ia["concessao_id"]).values(validade_ate="2000-01-01 00:00:00"))
    perguntar_http(client, usuario_ia, "Quanto entrou em agosto?", esperado=403)
    assert client.get(f"{BASE}/dominios", headers=usuario_ia["headers"]).json()[0]["acesso"]["estado"] == "vencida"


# ===================================================== o alcance de administrar
def test_administrar_nao_da_ver_nem_exportar_nem_pergunta(client, ia_ligada, ia_dw, aprovador):
    """DD-13: aprovar não é consultar, não é exportar."""
    ia_dw()
    assert aprovador["username"]
    perguntar_http(client, aprovador, "Quanto entrou em agosto?", esperado=403)           # sem ver + sem concessão
    r = client.get("/api/volumetria-catering/opcoes", headers=aprovador["headers"])
    assert r.status_code == 403                                                           # não ganhou `ver`
    r = client.post("/api/volumetria-catering/download/ticket", headers=aprovador["headers"],
                    params={"de": "2026-08-01", "ate": "2026-08-31"})
    assert r.status_code == 403                                                           # nem `exportar`


def test_quem_nao_administra_nao_ve_a_fila_nem_decide(client, usuario_ia, criar_usuario_ia):
    comum = criar_usuario_ia("comum")
    r = client.get(f"{BASE}/administracao/concessoes", headers=comum["headers"], params={"dominio": DOMINIO})
    assert r.status_code == 403
    pid = pedir(client, comum)["id"]
    for acao, corpo in (("aprovar", {}), ("negar", {"motivo": "x"}), ("revogar", {"motivo": "x"})):
        decidir(client, comum, pid, acao, corpo, esperado=403)


def test_o_aprovador_de_um_dominio_nao_decide_pedido_de_outro(client, ia_ligada, aprovador):
    """A permissão conferida é a do domínio DA CONCESSÃO, não uma genérica."""
    with db() as session:
        outro = session.execute(insert(IaConcessao).values(
            usuario_id=999999, username="fantasma", dominio="outro-dominio", status="pendente",
            motivo_pedido="x", autoaprovacao=0)).inserted_primary_key[0]
    decidir(client, aprovador, outro, "aprovar", esperado=404)   # domínio que não existe no catálogo
    with db() as session:
        assert session.execute(select(T.c.status).where(T.c.id == outro)).scalar_one() == "pendente"


def test_fila_lista_pendentes_vigentes_e_revogadas_do_dominio(client, ia_ligada, criar_usuario_ia, aprovador):
    a, b, c = criar_usuario_ia("a"), criar_usuario_ia("b"), criar_usuario_ia("c")
    pa, pb, _ = pedir(client, a)["id"], pedir(client, b)["id"], pedir(client, c)["id"]
    decidir(client, aprovador, pa, "aprovar")
    decidir(client, aprovador, pb, "aprovar")
    decidir(client, aprovador, pb, "revogar", {"motivo": "teste"})
    por_status = {}
    for linha in client.get(f"{BASE}/administracao/concessoes", headers=aprovador["headers"],
                            params={"dominio": DOMINIO}).json():
        por_status.setdefault(linha["status"], []).append(linha["username"])
    assert por_status["ativa"] == [a["username"]] and por_status["revogada"] == [b["username"]]
    assert por_status["pendente"] == [c["username"]]
    so_pendentes = client.get(f"{BASE}/administracao/concessoes", headers=aprovador["headers"],
                              params={"dominio": DOMINIO, "status": "pendente"}).json()
    assert [x["username"] for x in so_pendentes] == [c["username"]]


def test_admin_do_hub_aprova_pelo_bypass(client, ia_ligada, criar_usuario_ia, admin_headers):
    """Aceito na DD-13: todo admin do Hub também aprova."""
    u = criar_usuario_ia("pelo-admin")
    assert decidir(client, admin_headers, pedir(client, u)["id"], "aprovar")["status"] == "ativa"


# ===================================================== sem acesso ao sistema
def test_sem_ver_do_sistema_nao_pede_nem_pergunta(client, ia_ligada, ia_dw, criar_usuario_ia):
    ia_dw()
    u = criar_usuario_ia("sem-ver", ver_sistema=False)
    assert client.get(f"{BASE}/dominios", headers=u["headers"]).json()[0]["acesso"]["estado"] == "sem_ver_sistema"
    pedir(client, u, esperado=403)
    perguntar_http(client, u, "Quanto entrou em agosto?", esperado=403)


def test_concessao_sem_ver_do_sistema_e_negada(client, usuario_ia, admin_headers):
    """Tira o `ver` do app depois de aprovada a concessão: a pergunta é negada."""
    r = client.get("/api/admin/roles", headers=admin_headers)
    role = next(x for x in r.json() if x["slug"] == usuario_ia["role"])
    r = client.patch(f"/api/admin/roles/{role['id']}", headers=admin_headers, json={"apps": ["superfrioia"]})
    assert r.status_code == 200, r.text
    perguntar_http(client, usuario_ia, "Quanto entrou em agosto?", esperado=403)


def test_sem_ver_do_card_a_api_e_403(client, ia_ligada, criar_usuario_ia):
    u = criar_usuario_ia("sem-card", ver_ia=False)
    assert client.get(f"{BASE}/dominios", headers=u["headers"]).status_code == 403


# ============================================================ autoaprovação
def test_autoaprovacao_na_poc_e_marcada(client, ia_ligada, criar_usuario_ia, admin_headers):
    """DD-13: permitida durante a PoC, com o evento marcado."""
    from backend.auth.dependencies import usuario_pode  # noqa: F401  (o admin tem o bypass)
    me = client.get("/api/auth/me/permissoes", headers=admin_headers)
    assert me.status_code == 200
    r = client.post(f"{BASE}/concessoes/pedidos", headers=admin_headers, json={"dominio": DOMINIO, "motivo": "teste da PoC"})
    assert r.status_code == 201, r.text
    decisao = decidir(client, admin_headers, r.json()["id"], "aprovar")
    assert decisao["autoaprovacao"] is True


def test_autoaprovacao_proibida_antes_do_piloto(client, ia_ligada, admin_headers, monkeypatch):
    monkeypatch.setenv("IA_AUTOAPROVACAO", "false")
    r = client.post(f"{BASE}/concessoes/pedidos", headers=admin_headers, json={"dominio": DOMINIO, "motivo": "teste"})
    assert r.status_code == 201, r.text
    r2 = client.post(f"{BASE}/administracao/concessoes/{r.json()['id']}/aprovar", headers=admin_headers, json={})
    assert r2.status_code == 403 and "próprio pedido" in r2.json()["detail"]


def test_motivo_do_pedido_e_obrigatorio_limitado_e_mascarado(client, ia_ligada, criar_usuario_ia):
    u = criar_usuario_ia("motivo")
    pedir(client, u, motivo="   ", esperado=400)
    pedir(client, u, motivo="x" * 501, esperado=400)
    p = pedir(client, u, motivo="falar com ana@empresa.com sobre o CPF 123.456.789-09")
    assert "ana@empresa.com" not in p["motivo_pedido"] and "123.456.789-09" not in p["motivo_pedido"]
