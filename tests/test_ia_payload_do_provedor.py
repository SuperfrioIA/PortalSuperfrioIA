"""O que EXATAMENTE vai para o provedor (Lote 4: base factual do dossiê do piloto).

Roda perguntas reais pela pilha inteira com o provedor Claude sobre transporte simulado e
inspeciona TUDO que o SDK enviaria. A lista do que vai e do que nunca vai, no dossiê, é a
descrição destes testes. Sem rede.
"""
import json

import pytest

pytest.importorskip("anthropic")

import dw_falso  # noqa: E402
from anthropic_falso import CHAVE_DE_TESTE, ModeloFalso, mensagem, pedido, texto  # noqa: E402
from ia_ajuda import DOMINIO, perguntar_http, usar_roteiro  # noqa: E402
from backend.ia.provedor_anthropic import ProvedorAnthropic  # noqa: E402

CHAVES_DE_CLIENTE = [c for c, _ in dw_falso.CLIENTES]
CAMPOS_DA_REQUISICAO = {"model", "max_tokens", "system", "tools", "messages"}
NOMES_PROIBIDOS = {"chave", "cnpj", "cpf", "email", "e_mail", "telefone", "username", "usuario", "usuario_id", "ip",
                   "senha", "token", "metadata", "user_profile_id", "workspace_id", "ator", "ator_ip"}


def _todas_as_chaves(objeto, achadas=None):
    achadas = set() if achadas is None else achadas
    if isinstance(objeto, dict):
        for k, v in objeto.items():
            achadas.add(str(k).lower())
            _todas_as_chaves(v, achadas)
    elif isinstance(objeto, list):
        for v in objeto:
            _todas_as_chaves(v, achadas)
    return achadas


def _roteiro_de_cliente():
    """Uma conversa que toca clientes: procura o nome, ranqueia clientes de uma unidade e consulta um cliente."""
    consulta = {"de": "2026-08-01", "ate": "2026-08-31", "movimento": "rec"}
    return ModeloFalso([
        mensagem([pedido("amostrar_valores", {"dominio": DOMINIO, "dimensao": "cliente", "termo": "SAPORE"}, "a")], "tool_use"),
        mensagem([pedido("consultar_indicador", {"dominio": DOMINIO, "parametros": {
            **consulta, "unidades": ["CPS"], "detalhe": "cliente"}}, "b")], "tool_use"),
        mensagem([pedido("consultar_indicador", {"dominio": DOMINIO, "parametros": {
            **consulta, "clientes": ["SAPORE"]}}, "c")], "tool_use"),
        mensagem([texto("Feito.")]),
    ])


@pytest.fixture
def requisicoes(client, usuario_ia, monkeypatch):
    modelo = _roteiro_de_cliente()
    usar_roteiro(monkeypatch, ProvedorAnthropic(cliente=modelo.cliente()))
    pergunta = ("Quanto o cliente SAPORE recebeu? Meu CPF é 123.456.789-09, o CNPJ 12.345.678/0001-90, "
                "o e-mail é maria.silva@exemplo.com.br e o telefone (11) 91234-5678.")
    perguntar_http(client, usuario_ia, pergunta)
    return modelo.requisicoes, usuario_ia


def test_a_requisicao_so_tem_os_campos_combinados_e_nenhum_identificador_do_usuario(requisicoes):
    corpos, _ = requisicoes
    assert len(corpos) == 4
    for corpo in corpos:
        assert set(corpo) == CAMPOS_DA_REQUISICAO
        assert not (_todas_as_chaves(corpo) & NOMES_PROIBIDOS), _todas_as_chaves(corpo) & NOMES_PROIBIDOS


def test_dado_pessoal_da_pergunta_e_mascarado_antes_de_sair(requisicoes):
    corpos, _ = requisicoes
    tudo = json.dumps(corpos, ensure_ascii=False)
    for pessoal in ("123.456.789-09", "12.345.678/0001-90", "maria.silva@exemplo.com.br", "91234-5678", "12345678000190"):
        assert pessoal not in tudo, pessoal
    primeira = corpos[0]["messages"][0]["content"]
    assert "[CPF]" in primeira and "[CNPJ]" in primeira and "[EMAIL]" in primeira and "[TELEFONE]" in primeira


def test_a_chave_do_cliente_nunca_sai_nem_em_ranking_nem_em_consulta_por_nome(requisicoes):
    corpos, _ = requisicoes
    tudo = json.dumps(corpos, ensure_ascii=False)
    for chave in CHAVES_DE_CLIENTE:
        assert chave not in tudo, f"a raiz do CNPJ {chave} saiu para o provedor"
    assert "SAPORE" in tudo, "o nome do cliente (razão social) vai: é o que torna a resposta útil (D-L4a)"


def test_o_login_o_ip_e_o_nome_do_usuario_nao_saem(requisicoes):
    corpos, usuario = requisicoes
    tudo = json.dumps(corpos, ensure_ascii=False).lower()
    assert usuario["username"].lower() not in tudo and "testclient" not in tudo and "127.0.0.1" not in tudo


def test_a_chave_da_api_nunca_esta_no_corpo(requisicoes):
    corpos, _ = requisicoes
    assert CHAVE_DE_TESTE not in json.dumps(corpos)


def test_o_resultado_enviado_so_tem_agregados_e_rotulos_sem_linha_crua(requisicoes):
    corpos, _ = requisicoes
    # a última requisição carrega as três rodadas de ferramenta (as anteriores são prefixos dela)
    resultados = [json.loads(b["content"]) for m in corpos[-1]["messages"]
                  if isinstance(m["content"], list) for b in m["content"] if b.get("type") == "tool_result"]
    assert len(resultados) == 3
    for r in resultados:
        chaves = _todas_as_chaves(r)
        assert not (chaves & {"guia", "linhas", "linha", "registro", "registros", "nf", "nota_fiscal", "placa"}), chaves
    consulta = resultados[1]
    assert {"posicao", "rotulo", "total_do_periodo"} <= set(consulta["itens"][0])


def test_o_historico_enviado_e_so_texto_e_no_maximo_o_combinado(client, usuario_ia, monkeypatch):
    from backend.ia.service import HISTORICO_PARA_O_MODELO

    modelo = ModeloFalso([mensagem([texto(f"Resposta {i}.")]) for i in range(8)])
    usar_roteiro(monkeypatch, ProvedorAnthropic(cliente=modelo.cliente()))
    conversa = None
    for i in range(8):
        conversa = perguntar_http(client, usuario_ia, f"Pergunta {i}?", conversa_id=conversa)["conversa_id"]
    ultima = modelo.requisicoes[-1]["messages"]
    assert len(ultima) == HISTORICO_PARA_O_MODELO + 1                       # histórico limitado + a pergunta nova
    assert all(isinstance(m["content"], str) for m in ultima)               # só texto: nenhum bloco de dado antigo
    assert ultima[-1]["content"] == "Pergunta 7?"


def test_ferramentas_e_instrucoes_nao_carregam_dado_algum():
    from backend.ia import ferramentas, prompt

    fixo = json.dumps([prompt.sistema(), ferramentas.ESQUEMAS], ensure_ascii=False)
    for chave in CHAVES_DE_CLIENTE:
        assert chave not in fixo
    for nome in ("CONVIDA", "SAPORE", "NOVO CLIENTE"):
        assert nome not in fixo, "nome de cliente no texto fixo"
