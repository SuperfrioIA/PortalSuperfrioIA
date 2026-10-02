"""O `docker-compose.yml` leva as variáveis do SuperfrioIA ao container, com padrões seguros.

O compose usa lista EXPLÍCITA de variáveis (não `env_file`): o que não está nela nunca chega ao
container, e o `.env` da VM com a chave da Anthropic não valeria nada. Achado da revisão do Lote 3.
"""
import pathlib
import re

import pytest
import yaml

from backend.ia import config

RAIZ = pathlib.Path(__file__).resolve().parent.parent
AMBIENTE = yaml.safe_load((RAIZ / "docker-compose.yml").read_text(encoding="utf-8"))["services"]["hub"]["environment"]


def test_o_compose_repassa_as_variaveis_do_superfrioia():
    esperadas = {"IA_HABILITADO", "IA_PROVEDOR", "IA_AUTOAPROVACAO", "ANTHROPIC_API_KEY", "IA_MODELO", "IA_ESFORCO",
                 "IA_INFERENCE_GEO", "IA_COTA_DIA", "IA_TIMEOUT_S", "IA_PRAZO_PERGUNTA_S", "IA_TENTATIVAS", "IA_REPAROS",
                 "IA_PRECO_ENTRADA_USD_MTOK", "IA_PRECO_SAIDA_USD_MTOK", "IA_PRECO_CACHE_LEITURA_USD_MTOK",
                 "IA_PRECO_CACHE_ESCRITA_USD_MTOK", "IA_CAMBIO_USD_BRL"}
    assert esperadas <= set(AMBIENTE), esperadas - set(AMBIENTE)


def test_os_padroes_do_compose_sao_os_seguros():
    assert AMBIENTE["IA_HABILITADO"] == "${IA_HABILITADO:-false}"            # desligado
    assert AMBIENTE["IA_PROVEDOR"] == "${IA_PROVEDOR:-falso}"                # sem chave, sem rede
    assert AMBIENTE["IA_AUTOAPROVACAO"] == "${IA_AUTOAPROVACAO:-false}"      # DD-13: desligada fora da PoC
    assert AMBIENTE["ANTHROPIC_API_KEY"] == "${ANTHROPIC_API_KEY:-}"         # chave vazia por padrão


def test_o_compose_nao_traz_valor_literal_para_chave_nem_preco():
    for nome in [n for n in AMBIENTE if n.startswith("IA_PRECO") or n in ("ANTHROPIC_API_KEY", "IA_CAMBIO_USD_BRL")]:
        assert re.fullmatch(r"\$\{[A-Z_]+:-\}", str(AMBIENTE[nome])), (nome, AMBIENTE[nome])


@pytest.mark.parametrize("nome, leitura", [
    ("IA_MODELO", config.modelo), ("IA_ESFORCO", config.esforco), ("IA_INFERENCE_GEO", config.inference_geo),
    ("IA_COTA_DIA", config.cota_diaria), ("IA_TIMEOUT_S", config.timeout_do_provedor_s),
    ("IA_PRAZO_PERGUNTA_S", config.prazo_da_pergunta_s), ("IA_TENTATIVAS", config.tentativas_do_provedor),
    ("IA_REPAROS", config.reparos_do_verificador), ("IA_CAMBIO_USD_BRL", lambda: config.precos()["cambio_brl"]),
    ("IA_PRECO_ENTRADA_USD_MTOK", lambda: config.precos()["entrada"]),
])
def test_variavel_vazia_que_o_compose_repassa_cai_no_padrao_do_codigo(monkeypatch, nome, leitura):
    """O compose repassa `IA_X=` (vazio) quando o .env não define: tem que valer o padrão, não quebrar."""
    sem = leitura()
    monkeypatch.setenv(nome, "")
    assert leitura() == sem
