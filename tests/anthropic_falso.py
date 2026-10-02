"""A API da Anthropic de mentira, para provar o `ProvedorAnthropic` SEM rede.

Não é um mock do provedor: é o **SDK real** (`anthropic.Anthropic`) rodando sobre um
transporte HTTP simulado (`httpx2.MockTransport`). Assim o teste exercita de verdade a
serialização da requisição (campos aceitos pelo SDK, JSON do corpo, cabeçalhos) e a
leitura da resposta (tipos do SDK, `usage`, erros HTTP viram as exceções do SDK).

O que isto NÃO prova: que a API real aceita cada campo para o modelo configurado. Isso só a
rodada com chave prova (Lote 3, avaliação).

Uso:

    modelo = ModeloFalso([mensagem([pedido("descrever", {"dominio": "volumetria-catering"})], "tool_use"),
                          mensagem([texto("Pronto.")])])
    provedor = ProvedorAnthropic(cliente=modelo.cliente())
    ...
    modelo.requisicoes  # os corpos JSON que o SDK enviou, na ordem
"""
import json

import anthropic
import httpx2

CHAVE_DE_TESTE = "chave-de-teste-nao-e-segredo"


def texto(conteudo: str) -> dict:
    return {"type": "text", "text": conteudo}


def pedido(nome: str, argumentos: dict, id: str = "toolu_01") -> dict:
    return {"type": "tool_use", "id": id, "name": nome, "input": argumentos}


def mensagem(blocos, parada="end_turn", *, entrada=1000, saida=50, cache_leitura=0, cache_escrita=0, geo=None) -> dict:
    return {
        "id": "msg_01", "type": "message", "role": "assistant", "model": "claude-sonnet-5-5",
        "content": blocos, "stop_reason": parada, "stop_sequence": None,
        "usage": {"input_tokens": entrada, "output_tokens": saida,
                  "cache_read_input_tokens": cache_leitura, "cache_creation_input_tokens": cache_escrita,
                  "inference_geo": geo},
    }


def erro_http(status: int, tipo: str = "api_error") -> tuple[int, dict]:
    # o corpo de propósito carrega um texto reconhecível: o teste prova que ele NÃO vaza
    return status, {"type": "error", "error": {"type": tipo, "message": "SEGREDO-DO-CORPO-DE-ERRO"}}


def resultados_da_ultima_mensagem(corpo: dict) -> list[dict]:
    """Os `tool_result` da rodada mais recente de ferramentas na requisição (a última
    mensagem do usuário que os traz: numa reescrita, a última é um texto), com o conteúdo lido."""
    for m in reversed(corpo["messages"]):
        if isinstance(m["content"], list) and any(b.get("type") == "tool_result" for b in m["content"]):
            return [{**r, "conteudo": json.loads(r["content"])} for r in m["content"] if r.get("type") == "tool_result"]
    return []


class ModeloFalso:
    """Respostas roteirizadas, na ordem. Cada item é um dict de mensagem, um par
    `(status, corpo)` de `erro_http`, uma exceção para levantar no transporte
    (`httpx2.ConnectError`...) ou uma função `corpo_da_requisicao -> um dos anteriores`."""

    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.requisicoes: list[dict] = []
        self.cabecalhos: list[dict] = []

    def _tratar(self, request: httpx2.Request) -> httpx2.Response:
        corpo = json.loads(request.content)
        self.requisicoes.append(corpo)
        self.cabecalhos.append(dict(request.headers))
        if not self.respostas:
            raise AssertionError("o roteiro do modelo acabou, mas o provedor pediu outra rodada")
        item = self.respostas.pop(0)
        if callable(item):
            item = item(corpo)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, tuple):
            return httpx2.Response(item[0], json=item[1])
        return httpx2.Response(200, json=item)

    def cliente(self, **extra) -> "anthropic.Anthropic":
        parametros = {"max_retries": 0, **extra}
        return anthropic.Anthropic(
            api_key=CHAVE_DE_TESTE, http_client=httpx2.Client(transport=httpx2.MockTransport(self._tratar)),
            **parametros)
