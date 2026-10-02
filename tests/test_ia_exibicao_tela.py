"""A-4 (DD-28): a exibição da tela e a da IA, medidas e travadas.

`scripts/comparar_exibicao.py` roda a `fmt` REAL do app.js (extraída do arquivo) e o `exibir` da
IA sobre uma grade enorme (2,7 milhões de valores no Node; Chrome 154 e Edge 154 em 209 mil) e
achou ZERO divergência. Por isso a tela não foi alterada. Estes testes são a trava de regressão:
se alguém mudar o arredondamento de um lado e não do outro, a suíte quebra aqui.

Limite honesto: só testa os motores que existem na máquina. Firefox e Safari (outros motores de
formatação) não foram testados; a tela formata com `toLocaleString`, que depende do ICU do navegador.
"""
import importlib.util
import os
import pathlib
import shutil
import subprocess
import sys

import pytest

RAIZ = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = RAIZ / "scripts" / "comparar_exibicao.py"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node não está no PATH")


@pytest.fixture(scope="module")
def comparar():
    spec = importlib.util.spec_from_file_location("comparar_exibicao", SCRIPT)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_a_fmt_extraida_e_a_do_app_js_e_nao_uma_copia(comparar):
    fonte = comparar.fonte_do_fmt()
    assert fonte in (RAIZ / "frontend" / "volumetria-catering" / "app.js").read_text(encoding="utf-8")
    assert "toLocaleString('pt-BR'" in fonte and "n / 1000" in fonte


def test_nenhuma_divergencia_na_grade_pequena_entre_a_tela_e_a_ia(comparar):
    entradas = comparar.grade("pequena")[::3]                         # ~46 mil valores: pesos, R$, UA e cx
    tela = comparar.rodar_no_node(entradas)
    ia = comparar.da_ia(entradas)
    assert len(tela) == len(ia) == len(entradas) > 40_000
    assert comparar.divergencias(entradas, tela, ia) == []


@pytest.mark.parametrize("kg, esperado", [
    ("50", "0,1"),          # 0,05 t: o meio sobe
    ("150", "0,2"),         # 0,15 t: o empate que um float arredondado para baixo daria como 0,1
    ("250", "0,3"),
    ("1050", "1,1"),
    ("999950", "1.000,0"),  # o arredondamento passa para o milhar
    ("12345650", "12.345,7"),
    ("49", "0,0"),
    ("0", "0,0"),
    ("-1050", "-1,1"),      # negativo: o meio se afasta de zero nos dois lados
])
def test_empates_de_peso_dao_o_mesmo_texto_na_tela_e_na_ia(comparar, kg, esperado):
    tela, = comparar.rodar_no_node([("t", kg)])
    ia, = comparar.da_ia([("t", kg)])
    assert tela == ia == esperado


@pytest.mark.parametrize("unidade", ["R$", "UA", "cx"])
def test_empates_sem_casa_decimal_dao_o_mesmo_texto(comparar, unidade):
    valores = ["0.5", "1.5", "2.5", "1234.5", "999999.5", "0.499", "-2.5", "1234567"]
    entradas = [(unidade, v) for v in valores]
    assert comparar.rodar_no_node(entradas) == comparar.da_ia(entradas)
    assert comparar.da_ia([(unidade, "2.5")]) == ["3"]


def test_as_casas_da_tela_sao_as_da_ia(comparar):
    from backend.ia import derivacoes

    assert derivacoes.CASAS == {"t": 1, "R$": 0, "UA": 0, "cx": 0}
    entradas = [(u, "1234.567") for u in derivacoes.CASAS]
    assert comparar.rodar_no_node(entradas) == comparar.da_ia(entradas)


def test_o_comparador_pega_uma_divergencia_de_verdade(comparar):
    """Sem isto, 'zero divergência' poderia ser um comparador que nunca compara."""
    entradas = [("t", "150"), ("R$", "2.5")]
    ia_adulterada = ["0,1", "3"]                      # a IA "arredondando para baixo" o primeiro
    tela = comparar.rodar_no_node(entradas)
    assert comparar.divergencias(entradas, tela, ia_adulterada) == [("t", "150", "0,2", "0,1")]


def test_o_script_roda_inteiro_na_grade_rapida_so_com_node():
    ambiente = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    r = subprocess.run([sys.executable, str(SCRIPT), "--rapido", "--sem-navegador"], cwd=RAIZ, env=ambiente,
                       capture_output=True, text=True, encoding="utf-8", timeout=300)
    assert r.returncode == 0, r.stdout[-600:] + r.stderr[-600:]
    assert "TOTAL: 0 divergência(s)" in r.stdout
