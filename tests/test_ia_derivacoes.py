"""SuperfrioIA — derivações do Hub: total do período, ranking, variação % e mês parcial.

Funções puras, sem cursor. O modelo nunca faz estas contas (DD-9, DD-11, DD-22).
"""
import ast
import pathlib
from datetime import date
from decimal import Decimal as D

import pytest

from backend.ia import derivacoes as d

ARQUIVO = pathlib.Path(d.__file__)


# =========================================================== total do período
def test_total_do_periodo_soma_em_decimal_sem_float():
    r = d.total_do_periodo({"2026-01": D("0.1"), "2026-02": D("0.2"), "2026-03": D("0.3")},
                           ["2026-01", "2026-02", "2026-03"])
    assert r["total"] == D("0.6") and r["meses_com_dado"] == 3 and r["meses_sem_dado"] == []


def test_total_do_periodo_mes_ausente_nao_entra_e_e_dito():
    r = d.total_do_periodo({"2026-01": D("10"), "2026-03": None}, ["2026-01", "2026-02", "2026-03"])
    assert r["total"] == D("10") and r["meses_sem_dado"] == ["2026-02", "2026-03"]


def test_total_do_periodo_sem_nenhum_dado_e_none_e_nao_zero():
    assert d.total_do_periodo({}, ["2026-01"])["total"] is None


def test_total_do_periodo_com_muitas_casas_decimais():
    muito = D("123456789012345678.123456789")
    assert d.total_do_periodo({"2026-01": muito, "2026-02": muito}, ["2026-01", "2026-02"])["total"] == muito * 2


# ===================================================================== ranking
def _no(rotulo, **valores):
    return {"chave": f"chave-secreta-{rotulo}", "rotulo": rotulo, "valores": {k: D(v) for k, v in valores.items()}}


def test_ranking_ordena_pelo_total_do_periodo_e_corta_no_top_n():
    nos = [_no("A", m1="10", m2="5"), _no("B", m1="20"), _no("C", m1="1", m2="40")]
    r = d.ranking(nos, meses=["m1", "m2"], n=2, teto=20)
    assert [i["rotulo"] for i in r["itens"]] == ["C", "B"]      # 41, 20 (A = 15 fica de fora)
    assert [i["posicao"] for i in r["itens"]] == [1, 2]
    assert r["total_itens"] == 3 and r["truncado"] is True
    assert r["itens"][0]["total"] == D("41")


def test_ranking_nunca_devolve_a_chave_do_no():
    r = d.ranking([_no("A", m1="1")], meses=["m1"], n=5, teto=20)
    assert "chave" not in r["itens"][0] and "chave-secreta" not in str(r)


def test_ranking_desempata_pelo_rotulo_de_forma_estavel():
    nos = [_no("zeta", m1="5"), _no("alfa", m1="5"), _no("Beta", m1="5")]
    assert [i["rotulo"] for i in d.ranking(nos, meses=["m1"], n=3, teto=20)["itens"]] == ["alfa", "Beta", "zeta"]


def test_ranking_nao_muda_nenhum_valor_so_a_ordem_e_o_corte():
    nos = [_no("A", m1="1.5"), _no("B", m1="2.5")]
    r = d.ranking(nos, meses=["m1"], n=10, teto=20)
    assert {i["rotulo"]: i["valores"]["m1"] for i in r["itens"]} == {"A": D("1.5"), "B": D("2.5")}
    assert r["truncado"] is False


@pytest.mark.parametrize("n", [0, -1, 21])
def test_ranking_com_n_fora_do_teto_e_erro_e_nao_corte_silencioso(n):
    with pytest.raises(ValueError):
        d.ranking([_no("A", m1="1")], meses=["m1"], n=n, teto=20)


def test_ranking_de_no_sem_valor_vai_para_o_fim_e_nao_quebra():
    r = d.ranking([_no("vazio"), _no("cheio", m1="3")], meses=["m1"], n=5, teto=20)
    assert [i["rotulo"] for i in r["itens"]] == ["cheio", "vazio"] and r["itens"][1]["total"] is None


def test_ranking_acompanha_a_ordem_da_matriz_quando_nao_ha_empate():
    """A Matriz ordena por soma dos meses (matriz.py `_ordenar`); sem empate, o
    ranking do Hub sai na MESMA ordem — a ordem da tela."""
    from backend.volumetria_catering import matriz as matriz_mod
    nos = [{"nivel": "cliente", "chave": k, "rotulo": k, "filhos": [], "valores": {"m1": D(v1), "m2": D(v2)}}
           for k, v1, v2 in (("a", "5", "5"), ("b", "30", "1"), ("c", "2", "20"))]
    pai = [{"nivel": "unidade", "chave": "u", "rotulo": "u", "valores": {}, "filhos": list(nos)}]
    matriz_mod._ordenar(pai, ["m1", "m2"])
    ordem_da_tela = [f["rotulo"] for f in pai[0]["filhos"]]
    assert [i["rotulo"] for i in d.ranking(nos, meses=["m1", "m2"], n=3, teto=20)["itens"]] == ordem_da_tela


# ============================================================== variação %
def test_variacao_alta_queda_e_igual_com_valores_conhecidos():
    assert d.variacao_percentual(D("100"), D("150"))["percentual"] == "50,0"
    assert d.variacao_percentual(D("100"), D("150"))["sentido"] == "alta"
    queda = d.variacao_percentual(D("200"), D("150"))
    assert queda["percentual"] == "-25,0" and queda["sentido"] == "queda"
    igual = d.variacao_percentual(D("100"), D("100"))
    assert igual["percentual"] == "0,0" and igual["sentido"] == "igual"


def test_variacao_arredonda_na_exibicao_e_guarda_o_valor_exato():
    r = d.variacao_percentual(D("3"), D("4"))     # +33,333...%
    assert r["percentual"] == "33,3" and r["percentual_exato"].startswith("33.3333333")
    assert d.variacao_percentual(D("8"), D("9"))["percentual"] == "12,5"   # meio para cima
    assert d.variacao_percentual(D("16"), D("17"))["percentual"] == "6,3"  # 6,25 -> 6,3


def test_variacao_base_zero_nao_tem_percentual():
    sem_base = d.variacao_percentual(D("0"), D("10"))
    assert sem_base["situacao"] == "sem_base" and sem_base["percentual"] is None
    assert "o mês base teve zero" in sem_base["mensagem"]
    parado = d.variacao_percentual(D("0"), D("0"))
    assert parado["situacao"] == "sem_movimento" and "sem movimento nos dois meses" in parado["mensagem"]


def test_variacao_no_ausente_e_tratado_como_zero_com_o_motivo_explicito():
    r = d.variacao_percentual(None, D("10"))
    assert r["situacao"] == "sem_base" and r["ausente_base"] is True and r["ausente_atual"] is False
    r = d.variacao_percentual(D("10"), None)
    assert r["percentual"] == "-100,0" and r["ausente_atual"] is True


def test_variacao_com_muitas_casas_nao_passa_por_float():
    r = d.variacao_percentual(D("0.1"), D("0.3"))   # float daria 199.99999999999997
    assert r["percentual_exato"] == "200" or r["percentual_exato"].startswith("200")
    assert r["percentual"] == "200,0"


# ============================================================ mês parcial
def test_mes_corrente_e_parcial_ate_o_dia_do_dado():
    assert d.meses_parciais(["2026-08", "2026-09"], date(2026, 9, 5), date(2026, 9, 6)) == {"2026-09": 5}


def test_mes_cortado_pelo_atualizado_ate_e_parcial_mesmo_que_nao_seja_o_corrente():
    # o DW parou em 20/08 e hoje já é setembro: agosto está incompleto
    assert d.meses_parciais(["2026-07", "2026-08"], date(2026, 8, 20), date(2026, 9, 6)) == {"2026-08": 20}


def test_mes_depois_do_ultimo_dado_nao_tem_nenhum_dia():
    assert d.meses_parciais(["2026-09"], date(2026, 8, 31), date(2026, 9, 6)) == {"2026-09": 0}


def test_mes_completo_e_passado_nao_e_parcial():
    assert d.meses_parciais(["2026-06", "2026-07"], date(2026, 9, 5), date(2026, 9, 6)) == {}


def test_mes_corrente_sem_atualizado_ate_usa_o_dia_de_hoje():
    assert d.meses_parciais(["2026-09"], None, date(2026, 9, 6)) == {"2026-09": 6}


def test_ultimo_dia_do_mes_em_ano_bissexto():
    assert d.meses_parciais(["2028-02"], date(2028, 2, 28), date(2028, 3, 10)) == {"2028-02": 28}
    assert d.meses_parciais(["2028-02"], date(2028, 2, 29), date(2028, 3, 10)) == {}


# ============================================ a trava do mês parcial (DD-11)
def test_com_mes_parcial_e_sem_base_nao_existe_numero_so_requer_escolha():
    r = d.escolha_de_base("2026-08", "2026-09", {"2026-09": 5}, None)
    assert r["situacao"] == "requer_escolha" and r["meses_parciais"] == {"2026-09": 5}
    assert [o["base"] for o in r["opcoes"]] == list(d.OPCOES_DE_BASE)
    assert "percentual" not in r


@pytest.mark.parametrize("base", d.OPCOES_DE_BASE)
def test_cada_uma_das_tres_bases_destrava_a_conta(base):
    assert d.escolha_de_base("2026-08", "2026-09", {"2026-09": 5}, base) is None


def test_sem_mes_parcial_nao_pergunta_nada():
    assert d.escolha_de_base("2026-07", "2026-08", {}, None) is None
    assert d.escolha_de_base("2026-07", "2026-08", {"2026-09": 5}, None) is None   # parcial de outro mês


def test_base_desconhecida_e_erro():
    with pytest.raises(ValueError):
        d.escolha_de_base("2026-08", "2026-09", {"2026-09": 5}, "qualquer")


# ================================================================ pureza (AST)
def test_derivacoes_nao_abrem_cursor_nem_conhecem_o_servico_ou_o_banco():
    """A função recebe a Matriz pronta. Sem importar o serviço, o DW, o banco ou o
    FastAPI, não há como abrir um cursor."""
    arvore = ast.parse(ARQUIVO.read_text(encoding="utf-8"))
    importados = set()
    for no in ast.walk(arvore):
        if isinstance(no, ast.Import):
            importados.update(a.name.split(".")[0] for a in no.names)
        elif isinstance(no, ast.ImportFrom) and no.module:
            importados.add(no.module.split(".")[0])
            if no.module == "backend":
                importados.update(a.name for a in no.names)
    assert importados <= {"calendar", "datetime", "decimal"}, importados
    chamadas = {n.func.attr for n in ast.walk(arvore) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert not chamadas & {"cursor", "execute", "executemany", "commit", "connect", "matriz", "opcoes"}


def test_derivacoes_nao_usam_float_em_lugar_nenhum():
    arvore = ast.parse(ARQUIVO.read_text(encoding="utf-8"))
    nomes = {n.id for n in ast.walk(arvore) if isinstance(n, ast.Name)}
    assert "float" not in nomes
    constantes = [n.value for n in ast.walk(arvore) if isinstance(n, ast.Constant) and isinstance(n.value, float)]
    assert constantes == []
