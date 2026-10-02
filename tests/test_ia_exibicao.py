"""SuperfrioIA — a exibição dos números (DD-18, DD-28).

kg -> t em `Decimal`, com as casas da tela (peso em t com 1 casa; R$, UA e cx com 0),
sempre guardando o valor original. **Estes testes NÃO afirmam igualdade com a tela**
(DD-28): a tela arredonda no `float` do JavaScript e a IA no `Decimal`. Eles provam o
comportamento do `Decimal` nos empates e deixam, em `VETORES`, o campo `tela` para o
Lote 4 preencher com o resultado da função `fmt` real do `app.js`.
"""
from decimal import Decimal as D

import pytest

from backend.ia import derivacoes as d

# (kg que o DW devolve, unidade, o que o Decimal exibe, o que a tela exibe -- None = a medir no Lote 4)
VETORES = [
    # --- peso: kg -> t, 1 casa, meio para cima. `x,x5 t` exato é o empate que importa.
    ("1234550.000", "t", "1.234,6", None),
    ("1234650.000", "t", "1.234,7", None),
    ("2550.000", "t", "2,6", None),
    ("2450.000", "t", "2,5", None),
    ("10050.000", "t", "10,1", None),
    ("10150.000", "t", "10,2", None),
    ("49.999", "t", "0,0", None),
    ("50.000", "t", "0,1", None),
    ("0", "t", "0,0", None),
    ("1000.000", "t", "1,0", None),
    ("999999999999.999", "t", "1.000.000.000,0", None),
    # --- demais lentes: 0 casas, meio para cima
    ("0.5", "cx", "1", None),
    ("0.4", "cx", "0", None),
    ("1.5", "UA", "2", None),
    ("2.5", "UA", "3", None),
    ("1234567.499", "R$", "1.234.567", None),
    ("1234567.5", "R$", "1.234.568", None),
]


@pytest.mark.parametrize("original, unidade, esperado, _tela", VETORES)
def test_decimal_nos_empates_e_nas_bordas(original, unidade, esperado, _tela):
    assert d.exibir(D(original), unidade)["exibido"] == esperado


def test_o_valor_original_e_a_unidade_original_sempre_acompanham():
    e = d.exibir(D("1234550.000"), "t")
    assert (e["original"], e["unidade_original"]) == ("1234550.000", "kg")
    assert (e["exibido"], e["unidade_exibida"]) == ("1.234,6", "t")
    assert e["numero_exibido"] == "1234.6"
    outro = d.exibir(D("12.5"), "R$")
    assert (outro["original"], outro["unidade_original"], outro["unidade_exibida"]) == ("12.5", "R$", "R$")


def test_valor_ausente_nao_vira_zero():
    e = d.exibir(None, "t")
    assert e["exibido"] is None and e["original"] is None and e["unidade_original"] == "kg"


def test_nunca_exibe_zero_negativo():
    assert d.exibir(D("-0.0001"), "cx")["exibido"] == "0"
    assert d.exibir(D("-40"), "t")["exibido"] == "0,0"      # -0,04 t arredonda para zero, sem sinal


def test_a_conversao_para_t_nao_arredonda_antes_da_hora():
    """kg/1000 por deslocamento de expoente: exato. Arredonda uma vez, no fim."""
    assert d.exibir(D("1234549.999"), "t")["exibido"] == "1.234,5"
    assert d.exibir(D("1234550.000"), "t")["exibido"] == "1.234,6"


def test_muitas_casas_decimais_no_original_nao_se_perdem():
    e = d.exibir(D("1234567.123456789012345678"), "t")
    assert e["original"] == "1234567.123456789012345678" and e["exibido"] == "1.234,6"


def test_todas_as_lentes_do_contrato_tem_casas_definidas():
    """Lente nova no contrato do módulo sem regra de exibição falha aqui, não na tela."""
    from backend.volumetria_catering import contrato
    assert {l["unidade"] for l in contrato.LENTES.values()} <= set(d.CASAS)


def test_o_arquivo_de_vetores_marca_o_que_o_lote_4_ainda_precisa_medir():
    """Documenta a pendência: enquanto `tela` for None, a equivalência com o
    JavaScript NÃO está provada, e ninguém deve dizer que está."""
    pendentes = [v for v in VETORES if v[3] is None]
    assert len(pendentes) == len(VETORES)
