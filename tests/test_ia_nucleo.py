"""SuperfrioIA — o fluxo completo com o provedor de teste (Lote 2).

Pergunta -> portas -> provedor falso -> ferramentas -> adaptador -> serviço da
volumetria -> DW de mentira -> resposta gravada. Cada número da resposta é
conferido contra o **oráculo independente** de `tests/dw_falso.py` (soma por laço,
sem nenhuma função do Hub). Sem rede e sem chave: o provedor é o falso.
"""
import json

import dw_falso
import pytest
from sqlalchemy import select

from backend.core.database import db
from backend.ia.models import IaConsulta, IaConversa, IaMensagem

DOMINIO = "volumetria-catering"
AGOSTO = ["2026-08"]


@pytest.fixture
def usuario(ia_ligada, ia_dw, criar_usuario_ia, client, admin_headers):
    """Usuário comum com `ver` do app, `ver` do card e concessão ativa."""
    ia_dw()
    u = criar_usuario_ia("analista")
    r = client.post("/api/ia/concessoes/pedidos", headers=u["headers"],
                    json={"dominio": DOMINIO, "motivo": "análise de volumetria"})
    assert r.status_code == 201, r.text
    r = client.post(f"/api/ia/administracao/concessoes/{r.json()['id']}/aprovar", headers=admin_headers, json={})
    assert r.status_code == 200, r.text
    return u


def perguntar(client, usuario, texto, conversa_id=None):
    r = client.post("/api/ia/perguntas", headers=usuario["headers"],
                    json={"dominio": DOMINIO, "pergunta": texto, "conversa_id": conversa_id})
    assert r.status_code == 200, r.text
    return r.json()


def blocos(resposta, tipo):
    return [b for b in resposta["mensagem"]["blocos"] if b["tipo"] == tipo]


def t(valor):
    """O número exibido de uma soma em toneladas, escrito pelo teste (1 casa)."""
    return f"{dw_falso.pt_br(valor, 1)} t"


# =================================================================== respostas
def test_total_de_um_mes_e_o_numero_da_ferramenta(client, usuario, ia_dw):
    banco = ia_dw()
    r = perguntar(client, usuario, "Quanto de peso líquido entrou em agosto de 2026?")
    esperado = t(dw_falso.soma_t(AGOSTO))
    assert r["estado"] == "ok"
    assert esperado in r["mensagem"]["texto"]
    assert blocos(r, "tiles")[0]["itens"][0]["n"] == esperado   # a tela mostra o que a ferramenta devolveu
    assert r["mensagem"]["meta"]["rotulo_do_provedor"] == "provedor de teste"
    assert "dado do DW atualizado até" in r["mensagem"]["texto"]
    assert all(c.fechada for c in banco.conexoes)
    assert all(sql.lstrip().upper().startswith("SELECT") for sql, _ in banco.executados)


def test_filtro_de_unidade_chega_ao_dw_e_o_numero_bate(client, usuario, ia_dw):
    banco = ia_dw()
    r = perguntar(client, usuario, "Quanto de peso líquido entrou na unidade CPS em agosto?")
    assert t(dw_falso.soma_t(AGOSTO, unidades=["CPS"])) in r["mensagem"]["texto"]
    _, binds = banco.consultas[-1]
    assert binds["uni0"] == "CPS"


def test_saida_sem_faixa_usa_atendido_e_diz_que_nao_e_embarque(client, usuario, ia_dw):
    """DD-15: "expedido" sem faixa é atendido, dito como "atendido pelo estoque",
    e nunca apresentado como confirmação de embarque."""
    banco = ia_dw()
    r = perguntar(client, usuario, "Quanto de peso líquido foi expedido em agosto?")
    texto = r["mensagem"]["texto"]
    assert t(dw_falso.soma_t(AGOSTO, k=1)) in texto            # a coluna ATENDIDO
    assert "atendido pelo estoque" in texto
    assert "não confirmação de embarque" in texto
    assert "QTDE_PESO_ATENDIDO" in banco.consultas[-1][0]


def test_faixa_explicita_vence_o_padrao(client, usuario, ia_dw):
    banco = ia_dw()
    r = perguntar(client, usuario, "Quanto de peso líquido foi expedido (solicitado) em agosto?")
    assert t(dw_falso.soma_t(AGOSTO, k=0)) in r["mensagem"]["texto"]
    assert "QTDE_PESO_SOLICITADO" in banco.consultas[-1][0]


def test_periodo_de_varios_meses_traz_o_total_do_periodo_calculado_pelo_hub(client, usuario):
    meses = ["2026-01", "2026-02", "2026-03"]
    r = perguntar(client, usuario, "Quanto de peso líquido entrou de janeiro a março de 2026?")
    texto = r["mensagem"]["texto"]
    assert f"Total do período: **{t(dw_falso.soma_t(meses))}**" in texto
    for mes in meses:
        assert f"{mes}: {t(dw_falso.soma_t([mes]))}" in texto


def test_qual_unidade_mais_recebeu_ordena_no_hub(client, usuario):
    r = perguntar(client, usuario, "Qual unidade mais recebeu em agosto?")
    por_unidade = {u: dw_falso.soma_t(AGOSTO, unidades=[u]) for u in dw_falso.unidades_exibidas()}
    ordem = sorted(por_unidade, key=lambda u: (-por_unidade[u], u))
    tabela = blocos(r, "tabela")[0]["linhas"]
    assert [linha[1] for linha in tabela] == ordem
    assert tabela[0][2] == t(por_unidade[ordem[0]])
    assert f"1º **{ordem[0]}**" in r["mensagem"]["texto"]


def test_ranking_de_unidades_le_todas_as_paginas_com_mais_de_12(client, usuario, ia_dw):
    """DD-20: 14 unidades da fonte (13 exibidas, RMSPV e RMSPIV colidem) são 2 páginas.
    O maior total está na segunda; ranquear só a primeira erraria."""
    banco = ia_dw(n_unidades=14)
    r = perguntar(client, usuario, "Qual unidade mais recebeu em agosto?")
    assert len(banco.consultas) == 2                      # uma consulta por página
    topo = blocos(r, "tabela")[0]["linhas"][0]
    assert topo[1] == "U13"
    assert topo[2] == t(dw_falso.soma_t(AGOSTO, n_unidades=14, unidades=["U13"]))
    consulta = [c for c in registros_de_consulta() if c["situacao"] == "ok"][-1]
    assert consulta["paginas_lidas"] == 2
    assert consulta["chamadas_logicas"] == 1              # uma chamada lógica, várias páginas


def test_maiores_clientes_de_uma_unidade(client, usuario):
    r = perguntar(client, usuario, "Quais os maiores clientes de entrada da unidade CPS em agosto?")
    por_cliente = {rotulo: dw_falso.soma_t(AGOSTO, unidades=["CPS"], clientes=[rotulo])
                   for _, rotulo in dw_falso.CLIENTES}
    ordem = sorted(por_cliente, key=lambda c: (-por_cliente[c], c))
    assert [linha[1] for linha in blocos(r, "tabela")[0]["linhas"]] == ordem


def test_ranking_de_cliente_entre_unidades_e_recusado(client, usuario):
    """DD-21: somar o mesmo cliente entre unidades é agrupamento fora da árvore."""
    r = perguntar(client, usuario, "Quais os maiores clientes de entrada em agosto?")
    assert "fora do que este domínio responde" in r["mensagem"]["texto"]
    assert registros_de_consulta() == []


def test_total_do_ano_de_um_cliente_usa_o_nome_e_o_hub_resolve_a_chave(client, usuario, ia_dw):
    banco = ia_dw()
    r = perguntar(client, usuario, "Quanto o cliente SAPORE recebeu no ano?")
    meses = [f"2026-{m:02d}" for m in range(1, 10)]
    assert f"Total do período: **{t(dw_falso.soma_t(meses, clientes=['SAPORE']))}**" in r["mensagem"]["texto"]
    assert banco.consultas[-1][1]["cli0"] == "12345678"      # a chave foi ao DW...
    assert "12345678" not in json.dumps(r)                    # ...e não voltou na resposta


def test_nome_ambiguo_pede_esclarecimento_com_candidatos_por_rotulo(client, usuario):
    r = perguntar(client, usuario, "Quanto o cliente CONVIDA recebeu em agosto?")
    texto = r["mensagem"]["texto"]
    assert "CONVIDA BRASIL" in texto and "CONVIDA SUL" in texto
    assert "67945071" not in json.dumps(r) and "67945072" not in json.dumps(r)


def test_pallet_na_saida_repete_o_aviso_da_matriz(client, usuario):
    r = perguntar(client, usuario, "Quantos pallets saíram em agosto?")
    texto = r["mensagem"]["texto"]
    assert "só existe na entrada" in texto
    assert "Não há valor" in texto


def test_entrada_e_saida_sao_duas_consultas_sem_soma(client, usuario):
    r = perguntar(client, usuario, "Quanto entrou e quanto saiu em agosto?")
    texto = r["mensagem"]["texto"]
    assert t(dw_falso.soma_t(AGOSTO, k=0)) in texto and t(dw_falso.soma_t(AGOSTO, k=1)) in texto
    assert t(dw_falso.soma_t(AGOSTO, k=0) + dw_falso.soma_t(AGOSTO, k=1)) not in texto
    assert [c["chamadas_logicas"] for c in registros_de_consulta()] == [1, 1]


def test_pergunta_fora_do_contrato_e_recusada_com_explicacao(client, usuario):
    for pergunta in ("Qual o peso por dia da semana?", "Quem baixou o relatório?",
                     "Qual a previsão para outubro?", "Estamos acima da meta?",
                     "Quanto a unidade CPS representa % do total?", "Qual a média mensal de entrada no ano?"):
        r = perguntar(client, usuario, pergunta)
        assert "fora do que este domínio responde" in r["mensagem"]["texto"], pergunta
    assert registros_de_consulta() == []   # recusa não consulta nada


def test_dado_atualizado_e_periodo_vem_do_frescor_do_dw(client, usuario):
    r = perguntar(client, usuario, "O dado está atualizado?")
    assert "05/09/2026 07:05" in r["mensagem"]["texto"]
    assert "03/09/2026 07:10" in r["mensagem"]["texto"]


def test_listar_unidades_vem_do_dado(client, usuario):
    r = perguntar(client, usuario, "Quais unidades existem?")
    for unidade in dw_falso.unidades_exibidas():
        assert unidade in r["mensagem"]["texto"]


# ================================================================== variação %
def test_variacao_entre_dois_meses_completos_e_conta_do_hub(client, usuario):
    r = perguntar(client, usuario, "Qual foi a variação percentual da entrada entre julho e agosto?")
    julho, agosto = dw_falso.soma_t(["2026-07"]), dw_falso.soma_t(AGOSTO)
    from decimal import ROUND_HALF_UP, Decimal
    pct = ((Decimal(agosto) - julho) / julho * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    assert f"**{dw_falso.pt_br(pct, 1)}%**" in r["mensagem"]["texto"]
    assert t(julho) in r["mensagem"]["texto"] and t(agosto) in r["mensagem"]["texto"]


def test_variacao_com_mes_parcial_pergunta_a_base_e_nao_da_numero(client, usuario):
    """Trava da DD-11: com mês incompleto e sem base explícita não existe número."""
    r = perguntar(client, usuario, "Qual foi a variação percentual da entrada entre agosto e setembro?")
    texto = r["mensagem"]["texto"]
    assert "Qual base você quer?" in texto and "2026-09" in texto
    assert "%" not in texto.replace("Qual base", "")
    consulta = registros_de_consulta()[0]
    assert consulta["chamadas_servico"] == 1          # só as opções: nem leu a Matriz
    assert consulta["paginas_lidas"] == 0


def test_a_base_escolhida_na_conversa_fecha_a_conta(client, usuario, ia_dw):
    banco = ia_dw()
    primeira = perguntar(client, usuario, "Qual foi a variação percentual da entrada entre agosto e setembro?")
    r = perguntar(client, usuario, "mesmos dias", conversa_id=primeira["conversa_id"])
    assert "os mesmos dias (1 a 5) nos dois meses" in r["mensagem"]["texto"]
    dias = sorted(v for k, v in banco.consultas[-1][1].items() if k.startswith("dia"))
    assert dias == [1, 2, 3, 4, 5]                    # o filtro `dias` da própria Matriz, sem fórmula nova


# ================================================================= conversas
def test_conversa_guarda_as_mensagens_e_so_o_dono_le(client, usuario, criar_usuario_ia):
    r = perguntar(client, usuario, "Quanto de peso líquido entrou em agosto de 2026?")
    cid = r["conversa_id"]
    lida = client.get(f"/api/ia/conversas/{cid}", headers=usuario["headers"]).json()
    assert [m["papel"] for m in lida["mensagens"]] == ["usuario", "ia"]
    assert lida["mensagens"][1]["blocos"]
    outro = criar_usuario_ia("outro")
    assert client.get(f"/api/ia/conversas/{cid}", headers=outro["headers"]).status_code == 404


def test_o_texto_gravado_da_pergunta_ja_vai_mascarado(client, usuario):
    r = perguntar(client, usuario, "Quanto entrou em agosto? meu email é ana@empresa.com e o CPF 123.456.789-09")
    assert sorted(r["dados_pessoais_mascarados"]) == ["CPF", "EMAIL"]
    with db() as session:
        textos = [m for (m,) in session.execute(select(IaMensagem.texto).where(IaMensagem.papel == "usuario"))]
    assert all("ana@empresa.com" not in x and "123.456.789-09" not in x for x in textos)
    assert any("[EMAIL]" in x and "[CPF]" in x for x in textos)


def test_feedback_so_do_dono_e_so_em_mensagem_da_ia(client, usuario, criar_usuario_ia):
    r = perguntar(client, usuario, "Quanto entrou em agosto?")
    mid = r["mensagem"]["id"]
    assert client.post(f"/api/ia/mensagens/{mid}/feedback", headers=usuario["headers"], json={"valor": 1}).status_code == 200
    assert client.post(f"/api/ia/mensagens/{mid}/feedback", headers=usuario["headers"], json={"valor": 7}).status_code == 400
    outro = criar_usuario_ia("curioso")
    assert client.post(f"/api/ia/mensagens/{mid}/feedback", headers=outro["headers"], json={"valor": 1}).status_code == 404


def test_dominios_lista_estado_limites_e_provedor(client, usuario):
    d = client.get("/api/ia/dominios", headers=usuario["headers"]).json()[0]
    assert d["slug"] == DOMINIO and d["acesso"]["estado"] == "liberado"
    assert d["provedor"]["rotulo"] == "provedor de teste"
    assert d["limites"]["perguntas_por_dia"] == 30 and d["limites"]["consultas_por_pergunta"] == 3
    assert d["pode_administrar"] is False


def registros_de_consulta() -> list[dict]:
    with db() as session:
        rows = session.execute(select(IaConsulta.__table__).order_by(IaConsulta.id)).mappings().all()
    return [dict(r) for r in rows]


def test_a_conversa_nova_tem_titulo_e_dominio(client, usuario):
    perguntar(client, usuario, "Quanto entrou em agosto?")
    with db() as session:
        conversa = session.execute(select(IaConversa.__table__)).mappings().first()
    assert conversa["dominio"] == DOMINIO and conversa["titulo"].startswith("Quanto entrou")


def test_a_resposta_devolve_a_pergunta_ja_mascarada_para_a_tela_trocar_a_bolha(client, usuario):
    r = perguntar(client, usuario, "Quanto entrou em agosto? meu CPF é 123.456.789-09")
    assert r["pergunta"] == "Quanto entrou em agosto? meu CPF é [CPF]" and "123.456.789-09" not in json.dumps(r)


def test_a_mensagem_de_ambiguidade_e_para_o_usuario_nao_para_o_modelo(client, usuario):
    texto = perguntar(client, usuario, "Quanto o cliente CONVIDA recebeu em agosto?")["mensagem"]["texto"]
    assert "Qual delas?" in texto and "Peça ao usuário" not in texto
