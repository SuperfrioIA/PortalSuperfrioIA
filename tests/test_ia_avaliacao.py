"""O harness de avaliação do Lote 3 (`scripts/avaliar_ia.py` + `tests/ia_avaliacao/perguntas.yaml`).

Aqui só se prova o instrumento, sem rede e sem chave: o catálogo é válido, cada gabarito
calcula pelo próprio serviço e bate com a soma independente, o script recusa o que não deve
e um ensaio com o provedor falso nunca aprova critério. A avaliação com o modelo é manual.
"""
import importlib.util
import os
import pathlib
import subprocess
import sys

import pytest
import yaml

RAIZ = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = RAIZ / "scripts" / "avaliar_ia.py"
CATALOGO = RAIZ / "tests" / "ia_avaliacao" / "perguntas.yaml"

CAMPOS_DO_PASSO = {"pergunta", "gabarito", "esperar", "esperar_numeros", "esperar_texto_de", "esperar_texto",
                   "esperar_texto_qualquer", "esperar_lista", "esperar_aguardando_base", "proibir_texto",
                   "sem_consulta_ok", "oraculo"}
CAMPOS_DA_PERGUNTA = {"id", "catalogo", "tipo", "turnos"} | CAMPOS_DO_PASSO


@pytest.fixture(scope="module")
def avaliar():
    spec = importlib.util.spec_from_file_location("avaliar_ia", SCRIPT)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture(scope="module")
def perguntas():
    return yaml.safe_load(CATALOGO.read_text(encoding="utf-8"))


# ================================================================== o catálogo
def test_o_catalogo_tem_pelo_menos_trinta_perguntas_com_ids_unicos(perguntas):
    ids = [p["id"] for p in perguntas]
    assert len(perguntas) >= 30 and len(ids) == len(set(ids))


def test_o_catalogo_cobre_atendidas_recusadas_e_seguranca(perguntas):
    tipos = {p["tipo"] for p in perguntas}
    assert tipos == {"atendida", "recusada", "seguranca"}
    assert sum(p["tipo"] == "recusada" for p in perguntas) >= 12


def test_o_catalogo_cobre_as_40_perguntas_do_contrato(perguntas):
    """A 4 entra na forma agregada (a "por unidade" não tem gabarito único; ver o cabeçalho do YAML)."""
    cobertas = {p["catalogo"] for p in perguntas if p.get("catalogo")}
    assert cobertas >= set(range(1, 41)), sorted(set(range(1, 41)) - cobertas)


def test_so_existem_campos_conhecidos_para_um_erro_de_digitacao_nao_virar_criterio_mudo(perguntas):
    for p in perguntas:
        assert set(p) <= CAMPOS_DA_PERGUNTA, (p["id"], set(p) - CAMPOS_DA_PERGUNTA)
        for passo in p.get("turnos", []):
            assert set(passo) <= CAMPOS_DO_PASSO, (p["id"], set(passo) - CAMPOS_DO_PASSO)
        assert p["tipo"] in {"atendida", "recusada", "seguranca"}


def test_toda_pergunta_tem_texto_e_toda_atendida_com_dado_tem_gabarito_ou_expectativa(perguntas, avaliar):
    for p in perguntas:
        for passo in avaliar._passos(p):
            assert passo["pergunta"].strip()
            if p["tipo"] == "atendida":
                assert any(passo.get(k) is not None for k in (
                    "gabarito", "esperar_texto", "esperar_texto_qualquer", "esperar_aguardando_base",
                    "sem_consulta_ok")), (p["id"], "atendida sem nada para conferir")


# ================================================================== o gabarito
def test_todo_gabarito_calcula_pelo_servico_e_o_oraculo_independente_confere(
        perguntas, avaliar, ia_ligada, ia_dw):
    import dw_falso

    ia_dw()
    conferidos = 0
    for p in perguntas:
        for passo in avaliar._passos(p):
            modelos = avaliar._gabarito(passo, dw_falso)
            assert avaliar._conferir_oraculo(passo, modelos, dw_falso) is None, (p["id"], passo["pergunta"])
            conferidos += bool(passo.get("oraculo"))
            if passo.get("gabarito") and passo.get("esperar", ["x"]) != []:
                assert avaliar._esperados(passo, modelos), (p["id"], "gabarito sem valor esperado")
    assert conferidos >= 5, "o oráculo independente tem que cobrir mais de um caso"


def test_o_oraculo_pega_um_gabarito_errado(avaliar, ia_ligada, ia_dw):
    import dw_falso

    ia_dw()
    passo = {"gabarito": [{"movimento": "rec", "lente": "liq", "de": "2026-08-01", "ate": "2026-08-31"}],
             "oraculo": {"meses": ["2026-08"], "k": 1}}          # k errado de propósito
    assert avaliar._conferir_oraculo(passo, avaliar._gabarito(passo, dw_falso), dw_falso) is not None


def test_seletores_do_resultado(avaliar):
    r = {"itens": [{"v": {"valor": "1"}}, {"v": {"valor": "2"}}], "total_por_mes": [{"valor": "3"}, {"valor": None}]}
    assert avaliar._resolver(r, "itens.*.v.valor") == ["1", "2"]
    assert avaliar._resolver(r, "itens.0.v.valor") == ["1"]
    assert avaliar._resolver(r, "total_por_mes.*.valor") == ["3"]          # None é descartado
    assert avaliar._resolver(r, "nao.existe") == [] and avaliar._resolver(r, "itens.9.v") == []


def test_percentil_por_posto_mais_proximo(avaliar):
    assert avaliar._percentil([], 0.95) is None
    assert avaliar._percentil([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0], 0.95) == 10.0
    assert avaliar._percentil([5.0], 0.5) == 5.0


# ================================================================ as travas
def _rodar(*args, **env):
    ambiente = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "DATABASE_URL", "SUPERFRIO_ENV")}
    ambiente.update({"IA_AVALIACAO_SEM_ENV_LOCAL": "1", **env})
    return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=RAIZ, env=ambiente, capture_output=True,
                          text=True, timeout=180)


def test_sem_chave_o_script_recusa_e_nao_mede_nada():
    r = _rodar("--provedor", "anthropic", "--limite", "1")
    assert r.returncode != 0 and "SEM CHAVE" in (r.stderr + r.stdout) and "Nada foi medido" in (r.stderr + r.stdout)


def test_o_script_recusa_producao_e_banco_externo():
    r = _rodar("--provedor", "falso", SUPERFRIO_ENV="prod")
    assert r.returncode != 0 and "recusado" in (r.stderr + r.stdout)
    r = _rodar("--provedor", "falso", DATABASE_URL="postgresql://x:y@localhost/z")
    assert r.returncode != 0 and "recusado" in (r.stderr + r.stdout)


def test_teto_de_custo_sem_preco_configurado_e_recusado():
    r = _rodar("--provedor", "falso", "--teto-brl", "5")
    assert r.returncode != 0 and "IA_PRECO_ENTRADA_USD_MTOK" in (r.stderr + r.stdout)


def test_ensaio_com_provedor_falso_nao_aprova_nenhum_criterio(tmp_path):
    saida = tmp_path / "ensaio.md"
    r = _rodar("--provedor", "falso", "--ids", "A01,A05,R01", "--saida", str(saida))
    assert r.returncode == 0, r.stderr[-800:]
    texto = saida.read_text(encoding="utf-8")
    assert "ENSAIO DO HARNESS COM O PROVEDOR FALSO. NÃO É A AVALIAÇÃO DO MODELO" in texto
    assert "**atingido**" not in texto and "**NÃO atingido**" not in texto
    assert "sintético" in texto and "| Perguntas / passos | 3 / 3 |" in texto
    assert saida.with_suffix(".json").exists()


def test_o_script_nunca_imprime_o_valor_de_variavel_de_ambiente():
    fonte = SCRIPT.read_text(encoding="utf-8")
    assert "print(os.environ" not in fonte
    # o `.env.local` entra no ambiente sem ser impresso, e o relatório lista só os NOMES carregados
    assert "só os NOMES" in fonte and "carregados.append(nome)" in fonte
