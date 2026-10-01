"""SuperfrioIA — correções dos achados da revisão independente do Lote 2.

Cada teste leva o nome do defeito que a revisão achou, para o histórico dizer por que ele
existe. Todos falham sem a correção correspondente (conferido por mutação).
"""
import json

import dw_falso
import pytest
from ia_ajuda import (
    DOMINIO, Roteiro, consulta, eventos, marco_da_trilha, perguntar_http,
    registros_de_consulta, usar_roteiro,
)
from sqlalchemy import insert, select, update

from backend.core.database import db
from backend.ia import permissoes
from backend.ia.adaptadores import volumetria_catering as adaptador
from backend.ia.models import IaConcessao, IaConsulta, IaConversa, IaMensagem

T = IaConcessao.__table__
BASE = "/api/ia"


def tudo_que_foi_gravado() -> str:
    with db() as session:
        partes = [dict(r) for tabela in (IaMensagem, IaConsulta, IaConversa)
                  for r in session.execute(select(tabela.__table__)).mappings()]
    return json.dumps(partes, default=str, ensure_ascii=False)


# ===================== 1. a raiz do CNPJ nunca vira "rótulo" (DD-17) =====================
@pytest.fixture
def com_cliente_sem_nome(monkeypatch):
    """Um cliente cuja razão social o DW não tem: `rotulo_cliente` cai para a PRÓPRIA raiz."""
    monkeypatch.setattr(dw_falso, "CLIENTES", dw_falso.CLIENTES + [("99999999", "")])


def test_cliente_sem_razao_social_nao_vaza_a_raiz_pelo_ranking_nem_pela_amostra(
    client, usuario_ia, ia_dw, monkeypatch, com_cliente_sem_nome
):
    ia_dw()
    roteiro = usar_roteiro(monkeypatch, Roteiro([
        ("amostrar_valores", {"dominio": DOMINIO, "dimensao": "cliente", "termo": ""}),
        consulta(detalhe="cliente", unidades=["CPS"]),
    ]))
    marco = marco_da_trilha()
    r = perguntar_http(client, usuario_ia, "x")
    amostra, ranking = roteiro.resultados
    assert adaptador.SEM_NOME in amostra["valores"]
    assert adaptador.SEM_NOME in [i["rotulo"] for i in ranking["itens"]]
    onde = {"modelo": roteiro.tudo_que_o_modelo_viu(), "resposta": json.dumps(r, ensure_ascii=False),
            "gravado": tudo_que_foi_gravado(), "trilha": json.dumps([e["detalhes"] for e in eventos(marco)])}
    for lugar, conteudo in onde.items():
        assert "99999999" not in conteudo, lugar


def test_cliente_sem_nome_nao_pode_ser_consultado_por_nome(client, usuario_ia, ia_dw, monkeypatch, com_cliente_sem_nome):
    banco = ia_dw()
    roteiro = usar_roteiro(monkeypatch, Roteiro([consulta(clientes=[adaptador.SEM_NOME])]))
    perguntar_http(client, usuario_ia, "x")
    assert roteiro.resultados[0]["erro"] == "cliente_sem_nome" and banco.consultas == []


def test_rotulo_seguro_cobre_chave_digitos_e_vazio():
    assert adaptador._rotulo_seguro("12345678", "12345678") == adaptador.SEM_NOME
    assert adaptador._rotulo_seguro("12.345.678/0001-90", "x") == adaptador.SEM_NOME
    assert adaptador._rotulo_seguro("", "x") == adaptador.SEM_NOME and adaptador._rotulo_seguro(None, "x") == adaptador.SEM_NOME
    assert adaptador._rotulo_seguro("SAPORE", "12345678") == "SAPORE"
    assert adaptador._rotulo_seguro("3M DO BRASIL", "12345678") == "3M DO BRASIL"      # nome com número é nome


def test_dois_cadastros_com_o_mesmo_nome_sao_ambiguos_nao_unidos(client, usuario_ia, ia_dw, monkeypatch):
    """Unir os dois seria unir clientes, decisão de negócio que o Hub ainda não tomou."""
    monkeypatch.setattr(dw_falso, "CLIENTES", dw_falso.CLIENTES + [("77777777", "SAPORE")])
    banco = ia_dw()
    roteiro = usar_roteiro(monkeypatch, Roteiro([consulta(clientes=["SAPORE"])]))
    perguntar_http(client, usuario_ia, "x")
    erro = roteiro.resultados[0]
    assert erro["erro"] == "ambiguo" and "2 cadastros" in erro["mensagem"]
    assert banco.consultas == [] and "77777777" not in json.dumps(erro) and "12345678" not in json.dumps(erro)


# ============ 2. aprovar/negar/revogar não podem ser decididos duas vezes (corrida) ============
def _pedido_pendente(client, criar_usuario_ia):
    u = criar_usuario_ia("corrida")
    pid = client.post(f"{BASE}/concessoes/pedidos", headers=u["headers"], json={"dominio": DOMINIO, "motivo": "x"}).json()["id"]
    return u, pid


def _com_leitura_velha(monkeypatch, velha):
    """A 1ª leitura do pedido devolve `velha` (como se fosse lida antes de outro aprovador gravar)."""
    original, chamadas = permissoes._carregar, []

    def _carregar(session, concessao_id):
        chamadas.append(1)
        return dict(velha) if len(chamadas) == 1 else original(session, concessao_id)

    monkeypatch.setattr(permissoes, "_carregar", _carregar)


def test_dois_aprovadores_ao_mesmo_tempo_o_ultimo_nao_vence(client, ia_ligada, criar_usuario_ia, admin_headers, monkeypatch):
    u, pid = _pedido_pendente(client, criar_usuario_ia)
    with db() as s:
        lida_antes = dict(s.execute(select(T).where(T.c.id == pid)).mappings().one())      # pendente
    r = client.post(f"{BASE}/administracao/concessoes/{pid}/negar", headers=admin_headers, json={"motivo": "não"})
    assert r.status_code == 200

    marco = marco_da_trilha()
    _com_leitura_velha(monkeypatch, lida_antes)              # o 2º aprovador ainda enxergava "pendente"
    r = client.post(f"{BASE}/administracao/concessoes/{pid}/aprovar", headers=admin_headers, json={})
    assert r.status_code == 409 and "já foi decidido" in r.json()["detail"]
    with db() as s:
        assert s.execute(select(T.c.status).where(T.c.id == pid)).scalar_one() == "negada"      # a negativa ficou
    assert eventos(marco, "ia.concessao.aprovada") == []        # e não sobrou evento contraditório


def test_negar_e_revogar_tambem_conferem_o_status_na_escrita(client, usuario_ia, ia_ligada, criar_usuario_ia, admin_headers, monkeypatch):
    outro, pid = _pedido_pendente(client, criar_usuario_ia)
    with db() as s:
        pendente = dict(s.execute(select(T).where(T.c.id == pid)).mappings().one())
        s.execute(update(T).where(T.c.id == pid).values(status="negada"))         # alguém decidiu antes
    _com_leitura_velha(monkeypatch, pendente)
    r = client.post(f"{BASE}/administracao/concessoes/{pid}/negar", headers=admin_headers, json={"motivo": "x"})
    assert r.status_code == 409

    ativa_id = usuario_ia["concessao_id"]
    with db() as s:
        ativa = dict(s.execute(select(T).where(T.c.id == ativa_id)).mappings().one())
        s.execute(update(T).where(T.c.id == ativa_id).values(status="revogada"))
    _com_leitura_velha(monkeypatch, ativa)
    r = client.post(f"{BASE}/administracao/concessoes/{ativa_id}/revogar", headers=admin_headers, json={"motivo": "x"})
    assert r.status_code == 409


def test_a_aprovacao_recusada_pela_corrida_nao_revoga_a_concessao_anterior(client, usuario_ia, criar_usuario_ia, admin_headers, monkeypatch):
    """A renovação revoga a ativa anterior ANTES de ativar a nova; se a nova perde a corrida,
    a transação inteira é desfeita e a pessoa não fica sem acesso."""
    pid = client.post(f"{BASE}/concessoes/pedidos", headers=usuario_ia["headers"], json={"dominio": DOMINIO, "motivo": "x"})
    # a concessão vigente impede novo pedido; sem ela criamos o pendente direto no banco
    with db() as s:
        pid = s.execute(insert(IaConcessao).values(
            usuario_id=usuario_ia["id"], username=usuario_ia["username"], dominio=DOMINIO, status="negada",
            motivo_pedido="x", autoaprovacao=0)).inserted_primary_key[0]
        velha = dict(s.execute(select(T).where(T.c.id == pid)).mappings().one()) | {"status": "pendente"}
    _com_leitura_velha(monkeypatch, velha)
    r = client.post(f"{BASE}/administracao/concessoes/{pid}/aprovar", headers=admin_headers, json={})
    assert r.status_code == 409
    with db() as s:
        assert s.execute(select(T.c.status).where(T.c.id == usuario_ia["concessao_id"])).scalar_one() == "ativa"


def test_duplo_clique_no_pedido_vira_409_e_nao_500(client, ia_ligada, criar_usuario_ia, monkeypatch):
    u = criar_usuario_ia("duplo")
    with db() as s:
        s.execute(insert(IaConcessao).values(usuario_id=u["id"], username=u["username"], dominio=DOMINIO,
                                             status="pendente", motivo_pedido="primeiro", autoaprovacao=0))
    monkeypatch.setattr(permissoes, "_tem_pendente", lambda *_a: False)       # o 2º clique não via o 1º
    r = client.post(f"{BASE}/concessoes/pedidos", headers=u["headers"], json={"dominio": DOMINIO, "motivo": "segundo"})
    assert r.status_code == 409 and "em análise" in r.json()["detail"]


# ====================== 3. o motivo tem teto no servidor, não só na tela ======================
@pytest.mark.parametrize("acao", ["aprovar", "negar", "revogar"])
def test_motivo_acima_de_500_e_recusado_pelo_servidor(client, usuario_ia, admin_headers, acao):
    r = client.post(f"{BASE}/administracao/concessoes/{usuario_ia['concessao_id']}/{acao}",
                    headers=admin_headers, json={"motivo": "x" * 501})
    assert r.status_code == 422


def test_motivo_de_500_cabe_e_a_auditoria_mantem_os_campos_estruturados(client, ia_ligada, criar_usuario_ia, admin_headers):
    u, pid = _pedido_pendente(client, criar_usuario_ia)
    marco = marco_da_trilha()
    r = client.post(f"{BASE}/administracao/concessoes/{pid}/aprovar", headers=admin_headers, json={"motivo": "ç" * 500})
    assert r.status_code == 200
    d = eventos(marco, "ia.concessao.aprovada")[0]["detalhes"]
    assert "_truncado" not in d and d["aprovador"] == "admin" and d["validade_ate"] and d["autoaprovacao"] is False


# =========== 4. a matriz de acesso enxerga o app com a chave desligada (revogação silenciosa) ===========
def test_com_a_chave_desligada_a_matriz_e_as_permissoes_do_admin_ainda_mostram_o_app(client, ia_ligada, admin_headers, monkeypatch):
    monkeypatch.setenv("IA_HABILITADO", "false")
    matriz = client.get("/api/admin/matriz", headers=admin_headers).json()
    assert "superfrioia" in {a["slug"] for s in matriz["secoes"] for a in s["apps"]}
    permissoes_do_admin = client.get("/api/auth/me/permissoes", headers=admin_headers).json()["permissoes"]
    assert "superfrioia:ver" in permissoes_do_admin


def test_salvar_uma_role_com_a_chave_desligada_nao_revoga_o_ver_do_card(client, ia_ligada, criar_usuario_ia, admin_headers, monkeypatch):
    """O cenário real do achado: desligar a IA numa emergência e, no mesmo dia, editar uma role."""
    u = criar_usuario_ia("role")
    monkeypatch.setenv("IA_HABILITADO", "false")
    matriz = client.get("/api/admin/matriz", headers=admin_headers).json()
    app_ids_da_grade = {a["slug"] for s in matriz["secoes"] for a in s["apps"]}
    role = next(x for x in client.get("/api/admin/roles", headers=admin_headers).json() if x["slug"] == u["role"])
    apps_da_role = set(role["apps"])
    assert "superfrioia" in apps_da_role and "superfrioia" in app_ids_da_grade   # a grade tem a célula marcada
    # o formulário reenvia as células que a grade mostra e estão marcadas
    reenviadas = sorted(apps_da_role & app_ids_da_grade)
    r = client.patch(f"/api/admin/roles/{role['id']}", headers=admin_headers, json={"apps": reenviadas})
    assert r.status_code == 200, r.text
    monkeypatch.setenv("IA_HABILITADO", "true")
    depois = next(x for x in client.get("/api/admin/roles", headers=admin_headers).json() if x["slug"] == u["role"])
    assert "superfrioia" in depois["apps"]


# ============ 5. nada denuncia o módulo com a chave desligada: método errado e schema ============
@pytest.mark.parametrize("metodo, rota", [("DELETE", "/api/ia/dominios"), ("GET", "/api/ia/perguntas"),
                                           ("PUT", "/api/ia/conversas"), ("GET", "/api/ia/nao-existe"),
                                           ("PATCH", "/api/ia/administracao/concessoes/1/aprovar")])
def test_metodo_errado_ou_rota_inexistente_e_404_com_a_chave_desligada(client, admin_headers, monkeypatch, metodo, rota):
    monkeypatch.setenv("IA_HABILITADO", "false")
    assert client.request(metodo, rota, headers=admin_headers).status_code == 404       # nunca 405


def test_metodo_errado_tambem_e_404_com_a_chave_ligada(client, ia_ligada, admin_headers):
    assert client.get("/api/ia/perguntas", headers=admin_headers).status_code == 404


def test_o_schema_do_openapi_nao_lista_as_rotas_da_ia(client, ia_ligada, admin_headers):
    caminhos = client.get("/openapi.json").json().get("paths", {})
    assert [c for c in caminhos if c.startswith("/api/ia")] == []
    assert any(c.startswith("/api/portal") for c in caminhos)          # o schema em si segue funcionando


# ============ 6. a trava do mês parcial vale contra o MODELO, não só contra o parâmetro ausente ============
def variacao(base=None, de="2026-08", para="2026-09"):
    d = {"tipo": "variacao_percentual", "mes_base": de, "mes_atual": para}
    if base:
        d["base"] = base
    return consulta(derivacao=d, de=None, ate=None) if False else (
        "consultar_indicador", {"dominio": DOMINIO, "parametros": {"movimento": "rec", "derivacao": d}})


def test_o_modelo_nao_pode_mandar_a_base_na_primeira_chamada(client, usuario_ia, ia_dw, monkeypatch):
    banco = ia_dw()
    roteiro = usar_roteiro(monkeypatch, Roteiro([variacao(base="mesmos_dias")]))
    perguntar_http(client, usuario_ia, "Qual a variação entre agosto e setembro?")        # a pergunta NÃO diz a base
    assert roteiro.resultados[0]["erro"] == "base_nao_autorizada"
    assert banco.consultas == []                                  # não leu a Matriz, não calculou nada


def test_pergunta_que_ja_diz_a_base_e_calculada_direto(client, usuario_ia, ia_dw, monkeypatch):
    ia_dw()
    roteiro = usar_roteiro(monkeypatch, Roteiro([variacao(base="mesmos_dias")]))
    perguntar_http(client, usuario_ia, "Qual a variação entre agosto e setembro nos mesmos dias?")
    assert roteiro.resultados[0]["derivacao"]["situacao"] == "ok"
    assert "os mesmos dias (1 a 5)" in roteiro.resultados[0]["derivacao"]["base_usada"]


def test_a_escolha_vale_so_para_a_pergunta_seguinte_e_nao_para_sempre(client, usuario_ia, ia_dw, monkeypatch):
    ia_dw()
    usar_roteiro(monkeypatch, Roteiro([variacao()]))                       # sem base: o Hub pede a escolha
    primeira = perguntar_http(client, usuario_ia, "Qual a variação entre agosto e setembro?")
    assert primeira["mensagem"]["meta"]["aguardando_base"] is True
    cid = primeira["conversa_id"]

    roteiro = usar_roteiro(monkeypatch, Roteiro([variacao(base="so_meses_completos")]))
    segunda = perguntar_http(client, usuario_ia, "pode ser", conversa_id=cid)      # o usuário respondeu à pergunta
    assert roteiro.resultados[0]["derivacao"]["situacao"] == "ok"
    assert segunda["mensagem"]["meta"]["aguardando_base"] is False

    roteiro = usar_roteiro(monkeypatch, Roteiro([variacao(base="so_meses_completos")]))
    perguntar_http(client, usuario_ia, "e agora?", conversa_id=cid)               # já não há pergunta pendente
    assert roteiro.resultados[0]["erro"] == "base_nao_autorizada"


def test_a_base_inexistente_continua_recusada_mesmo_autorizada(client, usuario_ia, ia_dw, monkeypatch):
    ia_dw()
    roteiro = usar_roteiro(monkeypatch, Roteiro([variacao(base="qualquer")]))
    perguntar_http(client, usuario_ia, "variação nos mesmos dias entre agosto e setembro")
    assert roteiro.resultados[0]["erro"] == "parametro_invalido"


@pytest.mark.parametrize("texto, esperado", [
    ("compare nos mesmos dias", True), ("só meses completos", True), ("o mês incompleto contra o mês inteiro", True),
    ("do dia 1 a 15", True), ("1 a 15 de setembro contra 1 a 15 de agosto", True), ("até o dia 5", True),
    ("variação entre agosto e setembro", False), ("quanto entrou em agosto?", False), ("pode ser", False),
])
def test_deteccao_da_base_na_pergunta(texto, esperado):
    from backend.ia.politicas import mencionou_a_base
    assert mencionou_a_base(texto) is esperado


def test_comparacao_de_meses_muito_distantes_e_recusada_antes_de_montar_as_colunas(client, usuario_ia, ia_dw, monkeypatch):
    banco = ia_dw()
    roteiro = usar_roteiro(monkeypatch, Roteiro([variacao(de="0001-01", para="2026-08"), variacao(de="2020-01", para="2026-08")]))
    perguntar_http(client, usuario_ia, "x")
    assert [r["erro"] for r in roteiro.resultados] == ["periodo_longo", "periodo_longo"]
    assert banco.consultas == []


# ===================== 7. o aprovador precisa do card; a retenção apaga de verdade =====================
def test_o_aprovador_precisa_de_ver_do_card_alem_de_administrar(client, ia_ligada, criar_usuario_ia):
    sem_card = criar_usuario_ia("sem-card", administrar=True, ver_sistema=False, ver_ia=False)
    com_card = criar_usuario_ia("com-card", administrar=True, ver_sistema=False, ver_ia=True)
    fila = lambda u: client.get(f"{BASE}/administracao/concessoes", headers=u["headers"], params={"dominio": DOMINIO})  # noqa: E731
    assert fila(sem_card).status_code == 403
    assert fila(com_card).status_code == 200


def test_a_retencao_apaga_de_verdade_mesmo_com_a_chave_desligada(ia_ligada, monkeypatch):
    from datetime import datetime, timedelta, timezone

    from backend.ia import retencao
    agora = datetime(2026, 10, 1, tzinfo=timezone.utc)
    velho = (agora - timedelta(days=200)).strftime("%Y-%m-%d %H:%M:%S")
    with db() as s:
        c = s.execute(insert(IaConversa).values(usuario_id=1, username="u", dominio=DOMINIO, titulo="t",
                                                criado_em=velho, atualizado_em=velho)).inserted_primary_key[0]
        s.execute(insert(IaMensagem).values(conversa_id=c, papel="usuario", texto="t", criado_em=velho))
    monkeypatch.setenv("IA_HABILITADO", "false")
    assert retencao.executar(agora)["mensagens"] == 1
    with db() as s:
        assert s.execute(select(IaMensagem.id)).first() is None
