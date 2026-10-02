"""Verificador de números (Lote 3): todo número do texto tem que existir nas fontes."""
from decimal import Decimal

import pytest

from backend.ia import verificador as v


def _ok(texto, *fontes):
    r = v.verificar(texto, v.permitidos(*fontes))
    return r.ok, r.nao_verificados


# ================================================================ leitura
@pytest.mark.parametrize("escrito", ["1.234,6", "1234,6", "1234.6"])
def test_a_grafia_do_numero_nao_importa(escrito):
    assert _ok(f"foram {escrito} t", "valor 1.234,6") == (True, [])
    assert _ok(f"foram {escrito} t", {"valor": "1234.6"}) == (True, [])


def test_numero_que_nao_esta_nas_fontes_e_reprovado_e_listado_sem_repeticao():
    ok, ruins = _ok("Entraram 9.999,9 t e depois 9.999,9 t de novo, contra 12,5", "só 12,5 aqui")
    assert not ok and ruins == ["9.999,9"]


def test_arredondar_converter_ou_reescrever_o_numero_e_barrado():
    fonte = {"exibido": "1.234,6", "original": "1234567.000"}
    assert _ok("foram 1.234,6 t", fonte)[0]
    assert not _ok("foram 1.234,7 t", fonte)[0]          # arredondou de outro jeito
    assert not _ok("cerca de 1,2 mil t", fonte)[0]       # reescreveu em "mil"
    assert not _ok("foram 1.235 t", fonte)[0]            # tirou a casa
    assert _ok("foram 1.234.567 kg", fonte)[0]           # o original em kg também é citável


def test_somar_dois_resultados_produz_numero_que_nao_existe():
    entrada, saida = {"valor": "100,5"}, {"valor": "200,5"}
    assert not _ok("No total foram 301,0 t", entrada, saida)[0]
    assert _ok("Entrada 100,5 t e saída 200,5 t", entrada, saida)[0]


def test_milhar_ambiguo_vale_pelas_duas_leituras():
    assert _ok("foram 1.234 caixas", "volume 1234")[0]            # pt-BR no texto, inteiro no JSON
    assert _ok("foram 1234 caixas", "volume 1.234")[0]
    assert _ok("peso 1.234", {"x": 1.234})[0]                      # decimal no JSON
    assert not _ok("foram 1.234 caixas", "volume 1235")[0]
    assert _ok("foram 1.234.567 caixas", "1234567")[0]             # dois grupos: só pode ser milhar
    assert not _ok("foram 1.234.567 caixas", "1.234567")[0]


def test_sinal_nao_e_conferido_so_o_valor_absoluto():
    # limite declarado no módulo: "-12,3%" e "12,3%" são o mesmo número aqui
    assert _ok("queda de -12,3%", {"percentual": "12,3%"})[0]


def test_marcador_de_lista_nao_e_numero_mas_o_numero_do_item_e():
    texto = "1. primeiro item\n2) segundo item\n• 3. terceiro item\nvalor 55,5"
    assert _ok(texto, "só 55,5")[0]
    assert not _ok("1. primeiro\n77,7 t", "só 55,5")[0]


def test_letra_colada_antes_do_digito_e_identificador_nao_numero():
    assert _ok("unidade U01 e OP2 e RMSPII", "nada")[0]
    assert not _ok("unidade U01 com 321 pallets", "nada")[0]


def test_datas_viram_numeros_comparaveis_nos_dois_lados():
    fonte = {"atualizado_ate": {"rec": "05/09/2026 07:05"}, "hoje": "2026-10-02"}
    assert _ok("atualizado até 05/09/2026 às 07:05", fonte)[0]
    assert _ok("em 2026-09-05", "05/09/2026")[0]
    assert not _ok("atualizado até 06/09/2026", fonte)[0]


def test_percentual_e_moeda_sao_lidos_sem_o_simbolo():
    assert _ok("variação de 12,3% e R$ 1.234", "12,3 e 1.234")[0]
    assert _ok("R$1.234", "1.234")[0]


def test_texto_sem_numero_passa_e_conta_zero():
    r = v.verificar("Não há dado para esse recorte.", set())
    assert r.ok and r.verificados == 0


def test_fontes_aceitam_texto_e_estrutura_e_somam():
    liberados = v.permitidos("pergunta 2026", {"a": ["10,5", 7]}, ["histórico 33"])
    assert {Decimal("2026"), Decimal("10.5"), Decimal(7), Decimal(33)} <= liberados


# ===================================== furos de regex achados na revisão do Lote 3
def test_numero_depois_de_virgula_colada_tambem_e_conferido():
    ok, ruins = _ok("valores 10,5,9999", "só 10,5")
    assert not ok and ruins == ["9999"]
    ok, ruins = _ok("100,200,300", "só 100,2")
    assert not ok and "300" in ruins


def test_numero_entre_sublinhados_do_markdown_tambem_e_conferido():
    assert _ok("o total foi _9999_ t", "nada")[1] == ["9999"]
    assert _ok("o total foi _1.234,6_ t", "1.234,6")[0]


def test_formatos_que_nao_sao_pt_br_barram_a_resposta_legitima_e_isso_e_declarado():
    """Falso positivo (o lado seguro): o prompt manda copiar como a ferramenta devolveu."""
    assert not _ok("em 05.09.2026", "05/09/2026")[0]              # data com ponto vira 5,09 e 2026
    assert not _ok("foram 1,234.56 t", "1.234,56 t")[0]           # formato inglês
    assert not _ok("foram 1 234 t", "1.234 t")[0]                 # milhar com espaço: dois tokens, nenhum dos dois na fonte


def test_letra_ou_digito_colado_antes_continua_sendo_identificador():
    assert _ok("unidades U01, OP2 e A1B2", "nada")[0]


# ============================================== números que a pessoa escreveu
@pytest.mark.parametrize("escrito, vale", [
    ("2026", True), ("1900", True), ("2100", True), ("15", True), ("31", True), ("0", True),
    ("32", False), ("100", False), ("1899", False), ("2101", False), ("5.000", False), ("3,5", False),
    ("18.408,0", False),
])
def test_so_data_e_calendario_da_pergunta_viram_fonte(escrito, vale):
    assert bool(v.permitidos_da_pessoa(f"Confirma {escrito} t?")) is vale


def test_varios_textos_da_pessoa_se_somam():
    assert v.permitidos_da_pessoa("dia 15", "ano 2026 e 5.000") == {Decimal(15), Decimal(2026)}


def test_limite_conhecido_inteiro_pequeno_coincide_com_data_ou_posicao():
    """Documenta o que o verificador NÃO pega: 3 aparece na data, então "3 unidades" passa.
    Se isto deixar de ser verdade, o docstring do módulo tem que mudar junto."""
    assert _ok("foram 3 unidades", {"atualizado_ate": "2026-09-03"})[0]


def test_numero_grande_nao_coincide_por_acaso():
    assert not _ok("foram 4.321,0 t", {"atualizado_ate": "2026-09-03", "posicao": 4})[0]
