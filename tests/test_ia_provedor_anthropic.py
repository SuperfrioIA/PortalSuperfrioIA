"""ProvedorAnthropic (Lote 3), provado SEM rede: SDK real sobre transporte simulado.

Não prova que a API real aceita cada campo, nem como o modelo se comporta: isso é a
rodada de avaliação com chave (pendente). Prova o que é do Hub: o formato da requisição,
o laço de ferramentas, o uso e o custo medidos, o mapeamento de falhas e que nada sensível
vaza em erro ou log.
"""
import json
import logging
from datetime import date

import httpx2
import pytest

pytest.importorskip("anthropic")

from anthropic_falso import (  # noqa: E402
    CHAVE_DE_TESTE, ModeloFalso, erro_http, mensagem, pedido, resultados_da_ultima_mensagem, texto,
)
from backend.ia import config, ferramentas, prompt  # noqa: E402
from backend.ia.politicas import ErroDoProvedor  # noqa: E402
from backend.ia.provedor import ContextoDoModelo  # noqa: E402
from backend.ia.provedor_anthropic import ProvedorAnthropic, _mensagens  # noqa: E402

HOJE = date(2026, 10, 2)


def _contexto(pergunta="Quanto entrou em agosto?", historico=None, verificar=None):
    return ContextoDoModelo(
        sistema=prompt.sistema(), historico=historico or [], pergunta=pergunta,
        ferramentas=ferramentas.ESQUEMAS, hoje=HOJE, dominio="volumetria-catering", verificar=verificar)


def _rodar(modelo, executar=None, **contexto):
    provedor = ProvedorAnthropic(cliente=modelo.cliente())
    return provedor, provedor.responder(_contexto(**contexto), executar or (lambda n, a: {"ok": True}))


@pytest.fixture(autouse=True)
def _cliente_compartilhado_limpo():
    """O cliente do SDK é um por processo; um teste não pode herdar o de outro. (O ambiente `IA_*` e
    `ANTHROPIC_*` já vem limpo do `conftest.py`.)"""
    from backend.ia import provedor_anthropic

    provedor_anthropic._reiniciar_cliente_compartilhado()
    yield
    provedor_anthropic._reiniciar_cliente_compartilhado()


# ================================================================= requisição
def test_a_primeira_requisicao_tem_o_formato_combinado():
    modelo = ModeloFalso([mensagem([texto("Pronto.")])])
    _rodar(modelo)
    corpo = modelo.requisicoes[0]
    assert corpo["model"] == "claude-sonnet-5-5" and corpo["max_tokens"] == 1024
    # instruções cacheadas; data e domínio num bloco à parte, FORA do trecho cacheado
    assert corpo["system"][0]["text"] == prompt.sistema()
    assert corpo["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "02/10/2026" in corpo["system"][1]["text"] and "cache_control" not in corpo["system"][1]
    # ferramentas: as quatro do contrato, no formato da API, só a última marcada para cache
    assert [t["name"] for t in corpo["tools"]] == [e["nome"] for e in ferramentas.ESQUEMAS]
    assert all(t["input_schema"]["type"] == "object" for t in corpo["tools"])
    assert corpo["tools"][-1]["cache_control"] == {"type": "ephemeral"}
    assert all("cache_control" not in t for t in corpo["tools"][:-1])
    assert corpo["messages"] == [{"role": "user", "content": "Quanto entrou em agosto?"}]
    # parâmetros opcionais só vão se configurados
    assert "output_config" not in corpo and "inference_geo" not in corpo and "temperature" not in corpo


def test_a_chave_vai_no_cabecalho_e_nunca_no_corpo():
    modelo = ModeloFalso([mensagem([texto("Pronto.")])])
    _rodar(modelo)
    assert modelo.cabecalhos[0]["x-api-key"] == CHAVE_DE_TESTE
    assert CHAVE_DE_TESTE not in json.dumps(modelo.requisicoes[0])


def test_esforco_e_regiao_so_vao_quando_configurados(monkeypatch):
    monkeypatch.setenv("IA_ESFORCO", "medium")
    monkeypatch.setenv("IA_INFERENCE_GEO", "us")
    modelo = ModeloFalso([mensagem([texto("Pronto.")])])
    _rodar(modelo)
    assert modelo.requisicoes[0]["output_config"] == {"effort": "medium"}
    assert modelo.requisicoes[0]["inference_geo"] == "us"


def test_valor_invalido_de_esforco_nao_e_enviado(monkeypatch):
    monkeypatch.setenv("IA_ESFORCO", "altissimo")
    assert config.esforco() is None


def test_modelo_e_configuravel(monkeypatch):
    assert config.modelo() == "claude-sonnet-5-5"
    monkeypatch.setenv("IA_MODELO", "claude-opus-5-5")
    modelo = ModeloFalso([mensagem([texto("Pronto.")])])
    _rodar(modelo)
    assert modelo.requisicoes[0]["model"] == "claude-opus-5-5"


# ===================================================================== laço
def test_laco_executa_a_ferramenta_e_devolve_o_resultado_ao_modelo():
    chamadas = []

    def executar(nome, argumentos):
        chamadas.append((nome, argumentos))
        return {"valor": "1.234,6"}

    modelo = ModeloFalso([
        mensagem([texto("Vou consultar."), pedido("descrever", {"dominio": "volumetria-catering"}, "toolu_A")], "tool_use"),
        mensagem([texto("Foram **1.234,6** t.")]),
    ])
    provedor, resposta = _rodar(modelo, executar)
    assert chamadas == [("descrever", {"dominio": "volumetria-catering"})]
    assert resposta.texto == "Foram **1.234,6** t."
    segunda = modelo.requisicoes[1]["messages"]
    assert [m["role"] for m in segunda] == ["user", "assistant", "user"]
    assert segunda[1]["content"] == [
        {"type": "text", "text": "Vou consultar."},
        {"type": "tool_use", "id": "toolu_A", "name": "descrever", "input": {"dominio": "volumetria-catering"}}]
    resultado, = resultados_da_ultima_mensagem(modelo.requisicoes[1])
    assert resultado["tool_use_id"] == "toolu_A" and resultado["conteudo"] == {"valor": "1.234,6"}
    assert resultado["is_error"] is False


def test_resultado_de_erro_da_ferramenta_volta_marcado_como_erro():
    modelo = ModeloFalso([mensagem([pedido("amostrar_valores", {})], "tool_use"), mensagem([texto("Ok.")])])
    _rodar(modelo, lambda n, a: {"erro": "dimensao_invalida", "mensagem": "x"})
    assert resultados_da_ultima_mensagem(modelo.requisicoes[1])[0]["is_error"] is True


def test_varias_ferramentas_na_mesma_rodada_voltam_juntas_na_mesma_ordem():
    ordem = []
    modelo = ModeloFalso([
        mensagem([pedido("descrever", {"dominio": "d"}, "t1"), pedido("listar_capacidades", {}, "t2")], "tool_use"),
        mensagem([texto("Feito.")]),
    ])
    _rodar(modelo, lambda n, a: ordem.append(n) or {"n": n})
    assert ordem == ["descrever", "listar_capacidades"]
    assert [r["tool_use_id"] for r in resultados_da_ultima_mensagem(modelo.requisicoes[1])] == ["t1", "t2"]


def test_argumentos_que_nao_sao_objeto_chegam_como_objeto_vazio():
    visto = []
    modelo = ModeloFalso([mensagem([pedido("descrever", [1, 2])], "tool_use"), mensagem([texto("Ok.")])])
    _rodar(modelo, lambda n, a: visto.append(a) or {})
    assert visto == [{}]


def test_encerrar_pergunta_do_executor_sobe_e_o_uso_parcial_fica_disponivel():
    from backend.ia.politicas import EncerrarPergunta

    def executar(nome, argumentos):
        raise EncerrarPergunta("limite_consultas", "acabou")

    modelo = ModeloFalso([mensagem([pedido("descrever", {})], "tool_use", entrada=700, saida=30)])
    provedor = ProvedorAnthropic(cliente=modelo.cliente())
    with pytest.raises(EncerrarPergunta):
        provedor.responder(_contexto(), executar)
    assert provedor.uso_da_pergunta.entrada == 700 and provedor.uso_da_pergunta.saida == 30


# ===================================================================== medição
def test_uso_soma_as_rodadas_e_nao_inventa_custo_sem_preco():
    modelo = ModeloFalso([
        mensagem([pedido("descrever", {})], "tool_use", entrada=1000, saida=40, cache_escrita=500),
        mensagem([texto("Ok.")], entrada=1200, saida=60, cache_leitura=2000, geo="us"),
    ])
    _, resposta = _rodar(modelo)
    uso = resposta.uso
    assert (uso["tokens_entrada"], uso["tokens_saida"]) == (2200, 100)
    assert (uso["tokens_cache_leitura"], uso["tokens_cache_escrita"]) == (2000, 500)
    assert uso["rodadas"] == 2 and uso["reparos"] == 0 and uso["modelo"] == "claude-sonnet-5-5"
    assert uso["prompt"] == prompt.VERSAO and uso["inference_geo"] == "us"
    assert uso["custo_usd"] is None and uso["custo_brl"] is None       # sem preço configurado: não calculado


def test_custo_por_pergunta_com_preco_configurado(monkeypatch):
    monkeypatch.setenv("IA_PRECO_ENTRADA_USD_MTOK", "3")
    monkeypatch.setenv("IA_PRECO_SAIDA_USD_MTOK", "15")
    monkeypatch.setenv("IA_CAMBIO_USD_BRL", "5")
    modelo = ModeloFalso([mensagem([texto("Ok.")], entrada=1000, saida=100, cache_leitura=2000, cache_escrita=500)])
    _, resposta = _rodar(modelo)
    # (1000*3 + 100*15 + 2000*0,3 + 500*3,75) / 1e6 = 0,006975 (cache: 0,1x e 1,25x da entrada)
    assert resposta.uso["custo_usd"] == "0.006975"
    assert resposta.uso["custo_brl"] == "0.034875"


def test_preco_do_cache_configurado_vale_mais_que_o_multiplicador(monkeypatch):
    monkeypatch.setenv("IA_PRECO_ENTRADA_USD_MTOK", "3")
    monkeypatch.setenv("IA_PRECO_SAIDA_USD_MTOK", "15")
    monkeypatch.setenv("IA_PRECO_CACHE_LEITURA_USD_MTOK", "1")
    modelo = ModeloFalso([mensagem([texto("Ok.")], entrada=0, saida=0, cache_leitura=1_000_000)])
    _, resposta = _rodar(modelo)
    assert resposta.uso["custo_usd"] == "1.000000"


def test_latencia_do_modelo_e_medida_por_rodada():
    # chamadas ao relógio: início da pergunta; por rodada, a checagem do prazo e o início e o fim da chamada
    # (valores exatos em binário, para o teste não depender de arredondamento de float)
    tempos = iter([0.0, 0.0, 0.0, 0.25, 0.25, 1.0, 1.5])
    modelo = ModeloFalso([mensagem([pedido("descrever", {})], "tool_use"), mensagem([texto("Ok.")])])
    provedor = ProvedorAnthropic(cliente=modelo.cliente(), relogio=lambda: next(tempos))
    resposta = provedor.responder(_contexto(), lambda n, a: {})
    assert resposta.uso["latencia_modelo_ms"] == 250 + 500


# ================================================================ cliente e chave
def test_sem_chave_a_pergunta_falha_e_nenhum_cliente_e_criado(monkeypatch):
    import anthropic

    def _nao_deve_criar(*a, **k):
        raise AssertionError("não pode criar cliente sem chave")

    monkeypatch.setattr(anthropic, "Anthropic", _nao_deve_criar)
    with pytest.raises(ErroDoProvedor) as erro:
        ProvedorAnthropic().responder(_contexto(), lambda n, a: {})
    assert erro.value.tipo == "sem_chave"


def test_cliente_nasce_com_chave_timeout_e_tentativas_da_configuracao(monkeypatch):
    import anthropic

    visto = {}
    # criado ANTES de trocar a classe: o cliente falso só empresta o `messages` dele
    real = ModeloFalso([mensagem([texto("Ok.")]), mensagem([texto("Ok.")])]).cliente()

    class Cliente:
        def __init__(self, **kwargs):
            visto.update(kwargs)
            self.messages = real.messages

    monkeypatch.setattr(anthropic, "Anthropic", Cliente)
    monkeypatch.setenv("ANTHROPIC_API_KEY", CHAVE_DE_TESTE)
    ProvedorAnthropic().responder(_contexto(), lambda n, a: {})
    assert visto == {"api_key": CHAVE_DE_TESTE, "timeout": 30.0, "max_retries": 2}

    monkeypatch.setenv("IA_TIMEOUT_S", "10")
    monkeypatch.setenv("IA_TENTATIVAS", "0")
    ProvedorAnthropic().responder(_contexto(), lambda n, a: {})
    assert visto["timeout"] == 10.0 and visto["max_retries"] == 0


def test_o_cliente_do_sdk_e_um_por_processo_e_so_recriado_se_a_configuracao_mudar(monkeypatch):
    """Cada pergunta cria um provedor novo, mas o pool de conexões (e o TLS) é reaproveitado."""
    import anthropic

    criados = []
    real = ModeloFalso([mensagem([texto("Ok.")]) for _ in range(4)]).cliente()

    class Cliente:
        def __init__(self, **kwargs):
            criados.append(kwargs)
            self.messages = real.messages
            self.fechado = False

        def close(self):
            self.fechado = True

    monkeypatch.setattr(anthropic, "Anthropic", Cliente)
    monkeypatch.setenv("ANTHROPIC_API_KEY", CHAVE_DE_TESTE)
    for _ in range(3):
        ProvedorAnthropic().responder(_contexto(), lambda n, a: {})
    assert len(criados) == 1, "três perguntas, um cliente"
    monkeypatch.setenv("IA_TENTATIVAS", "0")                       # configuração mudou: cliente novo
    ProvedorAnthropic().responder(_contexto(), lambda n, a: {})
    assert len(criados) == 2


def test_cada_chamada_pede_no_maximo_o_que_resta_do_prazo(monkeypatch):
    monkeypatch.setenv("IA_PRAZO_PERGUNTA_S", "10")
    vistos = []
    modelo = ModeloFalso([mensagem([texto("Ok.")])])
    cliente = modelo.cliente()
    original = cliente.messages.create
    cliente.messages.create = lambda **kw: (vistos.append(kw.get("timeout")), original(**kw))[1]
    ProvedorAnthropic(cliente=cliente, relogio=lambda: 0.0).responder(_contexto(), lambda n, a: {})
    assert vistos == [10.0]                                         # min(30 de IA_TIMEOUT_S, 10 que restam)

    monkeypatch.setenv("IA_PRAZO_PERGUNTA_S", "100")
    vistos.clear()
    modelo.respostas.append(mensagem([texto("Ok.")]))
    ProvedorAnthropic(cliente=cliente, relogio=lambda: 0.0).responder(_contexto(), lambda n, a: {})
    assert vistos == [30.0]


def test_os_padroes_de_tempo_ficam_abaixo_do_tempo_ocioso_do_balanceador(monkeypatch):
    assert config.timeout_do_provedor_s() == 30.0 and config.prazo_da_pergunta_s() == 55.0
    assert config.prazo_da_pergunta_s() < 60.0


# ============================================================ log do SDK
def test_o_log_do_sdk_volta_a_ser_travado_depois_de_o_sdk_religa_lo():
    import logging

    from backend.ia import provedor_anthropic

    for nome in ("anthropic", "httpx2", "httpcore2"):
        logging.getLogger(nome).setLevel(logging.DEBUG)             # o que ANTHROPIC_LOG=debug faz ao importar o SDK
    provedor_anthropic._travar_logs()
    assert all(logging.getLogger(n).level == logging.WARNING for n in ("anthropic", "httpx2", "httpcore2"))


def test_com_anthropic_log_debug_no_ambiente_o_sdk_nao_registra_a_requisicao():
    """Processo NOVO, na ordem de produção (o SDK só é importado na primeira pergunta): o
    `ANTHROPIC_LOG=debug` religaria o log DEBUG do SDK e desfaria a trava feita antes."""
    import os
    import pathlib
    import subprocess
    import sys

    codigo = (
        "import os, logging; os.environ['ANTHROPIC_LOG']='debug'; os.environ['ANTHROPIC_API_KEY']='valor-so-de-teste';"
        "import backend.ia.provedor_anthropic as p;"
        "assert 'anthropic' not in __import__('sys').modules, 'o SDK foi importado antes da hora';"
        "p.ProvedorAnthropic()._cliente_do_sdk();"
        "print('NIVEIS', logging.getLogger('anthropic').level, logging.getLogger('httpx2').level, logging.getLogger('httpcore2').level)")
    r = subprocess.run([sys.executable, "-c", codigo], cwd=pathlib.Path(__file__).resolve().parent.parent,
                       env={k: v for k, v in os.environ.items() if not k.startswith(("IA_", "ANTHROPIC_"))},
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-800:]
    assert "NIVEIS 30 30 30" in r.stdout, r.stdout + r.stderr[-400:]


def test_criar_o_provedor_e_listar_dominios_nao_exige_chave_nem_toca_a_rede(monkeypatch, usuario_ia, client):
    monkeypatch.setenv("IA_PROVEDOR", "anthropic")
    r = client.get("/api/ia/dominios", headers=usuario_ia["headers"])
    assert r.status_code == 200, r.text
    assert r.json()[0]["provedor"] == {"nome": "anthropic", "rotulo": "Claude"}


# ====================================================================== falhas
@pytest.mark.parametrize("resposta, tipo", [
    (erro_http(401, "authentication_error"), "autenticacao"),
    (erro_http(403, "permission_error"), "permissao"),
    (erro_http(429, "rate_limit_error"), "limite_de_taxa"),
    (erro_http(400, "invalid_request_error"), "requisicao_invalida"),
    (erro_http(404, "not_found_error"), "modelo_ou_rota_inexistente"),
    (erro_http(500), "servico_do_provedor"),
    (erro_http(529, "overloaded_error"), "sobrecarga"),
    (httpx2.ConnectError("falhou"), "conexao"),
    (httpx2.ReadTimeout("demorou"), "timeout"),
])
def test_falha_do_sdk_vira_uma_palavra_sem_o_texto_do_erro(resposta, tipo):
    with pytest.raises(ErroDoProvedor) as erro:
        _rodar(ModeloFalso([resposta]))
    assert erro.value.tipo == tipo
    assert "SEGREDO-DO-CORPO-DE-ERRO" not in repr(erro.value) and erro.value.__cause__ is None
    assert erro.value.__suppress_context__ is True


def test_erro_http_leva_o_status_e_o_tipo_da_api_para_diagnosticar_o_primeiro_400_sem_a_mensagem():
    with pytest.raises(ErroDoProvedor) as erro:
        _rodar(ModeloFalso([erro_http(400, "invalid_request_error")]))
    assert erro.value.tipo == "requisicao_invalida"
    assert erro.value.status == 400 and erro.value.tipo_api == "invalid_request_error"
    assert "SEGREDO-DO-CORPO-DE-ERRO" not in repr(vars(erro.value))


def test_falha_de_conexao_nao_tem_status_nem_tipo_da_api():
    with pytest.raises(ErroDoProvedor) as erro:
        _rodar(ModeloFalso([httpx2.ConnectError("falhou")]))
    assert erro.value.status is None and erro.value.tipo_api is None


def test_tipo_da_api_fora_do_formato_esperado_e_descartado():
    from backend.ia.provedor_anthropic import _diagnostico

    class Falso(Exception):
        status_code = 400
        body = {"error": {"type": "Texto livre com a pergunta do usuário!"}}

    assert _diagnostico(Falso()) == (400, None)


def test_blocos_de_texto_da_resposta_sao_juntados_com_quebra_de_linha():
    modelo = ModeloFalso([mensagem([texto("Entrou 1.234,6"), texto("5 mil")])])
    _, resposta = _rodar(modelo)
    assert resposta.texto == "Entrou 1.234,6\n5 mil"                   # sem "1.234,65 mil" fabricado pela colagem


@pytest.mark.parametrize("parada, tipo", [
    ("max_tokens", "resposta_truncada"), ("refusal", "recusa_do_modelo"), ("pause_turn", "parada_inesperada")])
def test_parada_anormal_do_modelo_e_erro_e_nao_texto_pela_metade(parada, tipo):
    with pytest.raises(ErroDoProvedor) as erro:
        _rodar(ModeloFalso([mensagem([texto("meio de frase")], parada)]))
    assert erro.value.tipo == tipo


def test_resposta_sem_texto_e_erro():
    with pytest.raises(ErroDoProvedor) as erro:
        _rodar(ModeloFalso([mensagem([texto("   ")])]))
    assert erro.value.tipo == "resposta_vazia"


def test_modelo_que_pede_ferramenta_sem_parar_e_cortado_por_rodadas(monkeypatch):
    monkeypatch.setenv("IA_MAX_PASSOS", "2")
    monkeypatch.setenv("IA_REPAROS", "0")
    sempre = lambda corpo: mensagem([pedido("descrever", {})], "tool_use")      # noqa: E731
    modelo = ModeloFalso([sempre] * 10)
    provedor = ProvedorAnthropic(cliente=modelo.cliente())
    with pytest.raises(ErroDoProvedor) as erro:
        provedor.responder(_contexto(), lambda n, a: {})
    assert erro.value.tipo == "rodadas" and len(modelo.requisicoes) == 4   # passos + reparos + 2


def test_prazo_da_pergunta_corta_antes_de_nova_chamada(monkeypatch):
    monkeypatch.setenv("IA_PRAZO_PERGUNTA_S", "30")
    agora = {"t": 0.0}

    def relogio():
        agora["t"] += 20.0
        return agora["t"]

    modelo = ModeloFalso([mensagem([pedido("descrever", {})], "tool_use"), mensagem([texto("Ok.")])])
    provedor = ProvedorAnthropic(cliente=modelo.cliente(), relogio=relogio)
    with pytest.raises(ErroDoProvedor) as erro:
        provedor.responder(_contexto(), lambda n, a: {})
    assert erro.value.tipo == "prazo" and len(modelo.requisicoes) == 1


# ============================================================== histórico
def test_historico_vira_mensagens_que_comecam_e_terminam_em_usuario():
    historico = [{"papel": "ia", "texto": "resposta órfã"}, {"papel": "usuario", "texto": "oi"},
                 {"papel": "ia", "texto": "olá"}]
    assert _mensagens(historico, "e agora?") == [
        {"role": "user", "content": "oi"}, {"role": "assistant", "content": "olá"},
        {"role": "user", "content": "e agora?"}]


def test_papeis_repetidos_sao_juntados_e_texto_vazio_some():
    historico = [{"papel": "usuario", "texto": "a"}, {"papel": "usuario", "texto": "b"},
                 {"papel": "ia", "texto": "   "}, {"papel": "ia", "texto": "c"}]
    assert _mensagens(historico, "d") == [
        {"role": "user", "content": "a\nb"}, {"role": "assistant", "content": "c"}, {"role": "user", "content": "d"}]


# ================================================================ reescrita
def test_texto_reprovado_pelo_verificador_volta_ao_modelo_uma_vez():
    def verificar(t):
        return ["9.999,9"] if "9.999,9" in t else []

    modelo = ModeloFalso([mensagem([texto("Foram 9.999,9 t.")]), mensagem([texto("Foram 1.234,6 t.")])])
    provedor, resposta = _rodar(modelo, verificar=verificar)
    assert resposta.texto == "Foram 1.234,6 t." and resposta.uso["reparos"] == 1
    pedido_de_reescrita = modelo.requisicoes[1]["messages"][-1]
    assert pedido_de_reescrita["role"] == "user" and "9.999,9" in pedido_de_reescrita["content"]
    assert modelo.requisicoes[1]["messages"][-2]["role"] == "assistant"


def test_sem_reparo_configurado_o_texto_reprovado_segue_para_o_servico_conferir(monkeypatch):
    monkeypatch.setenv("IA_REPAROS", "0")
    modelo = ModeloFalso([mensagem([texto("Foram 9.999,9 t.")])])
    _, resposta = _rodar(modelo, verificar=lambda t: ["9.999,9"])
    assert resposta.texto == "Foram 9.999,9 t." and len(modelo.requisicoes) == 1


def test_a_reescrita_acontece_no_maximo_o_numero_configurado_de_vezes():
    modelo = ModeloFalso([mensagem([texto("Foram 9.999,9 t.")]), mensagem([texto("Foram 8.888,8 t.")])])
    _, resposta = _rodar(modelo, verificar=lambda t: ["x"])      # sempre reprova
    assert len(modelo.requisicoes) == 2 and resposta.uso["reparos"] == 1


# ======================================================== o que NÃO existe
def test_o_modulo_nao_tem_chave_nem_segredo_embutidos():
    fonte = open(ProvedorAnthropic.__init__.__code__.co_filename, encoding="utf-8").read()
    assert ("sk-" + "ant") not in fonte and "api_key=" not in fonte.replace("api_key=chave", "")
    assert "logger." not in fonte and "getLogger(__name__)" not in fonte   # o provedor não escreve log próprio


def test_nenhum_log_do_provedor_carrega_a_chave(caplog):
    caplog.set_level(logging.DEBUG)
    with pytest.raises(ErroDoProvedor):
        _rodar(ModeloFalso([erro_http(401, "authentication_error")]))
    assert CHAVE_DE_TESTE not in caplog.text and "SEGREDO-DO-CORPO-DE-ERRO" not in caplog.text
