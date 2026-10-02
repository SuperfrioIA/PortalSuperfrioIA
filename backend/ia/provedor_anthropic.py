"""Provedor Claude (Lote 3): o laço de ferramentas sobre a API de Mensagens da Anthropic.

O Hub é o cliente (D-3, opção C): o modelo pede uma ferramenta, o **Hub** executa pelo
`executar` que recebeu (é ele quem aplica passos, teto de consultas, limite de trabalho e
concessão) e devolve o resultado. Este módulo só conversa com o modelo.

## O que ele garante

- **Sem rede até a primeira pergunta real**: construir o provedor (e listar domínios) não
  cria cliente, não lê a chave e nem importa o SDK. O cliente nasce na primeira
  `responder`. Sem `ANTHROPIC_API_KEY` a pergunta termina com `ErroDoProvedor("sem_chave")`.
- **Nada sensível em erro ou log**: toda falha do SDK vira `ErroDoProvedor(tipo)` com uma
  palavra (`timeout`, `conexao`, `limite_de_taxa`, `autenticacao`...). O texto do erro, o
  corpo da requisição (pergunta e dados) e o da resposta nunca são registrados.
- **Prazo**: cada chamada HTTP tem timeout; a pergunta inteira tem prazo
  (`IA_PRAZO_PERGUNTA_S`) e número máximo de rodadas, mesmo que o modelo fique pedindo
  ferramenta.
- **Medição**: tokens (entrada, saída, cache), latência do modelo e custo estimado por
  pergunta ficam em `uso_da_pergunta`, que o serviço lê também quando a pergunta termina
  por limite ou por erro.
- **Cache de prompt**: ferramentas e instruções (idênticas em toda pergunta) são marcadas
  para cache; a data e o domínio vão num bloco à parte, depois do trecho cacheado. O cache
  só vale se o trecho passar do mínimo do modelo; a medição (`tokens_cache_leitura`) diz
  se de fato acertou.
- **Reescrita**: se o texto final tem número que o verificador reprova, o modelo recebe a
  lista e pode reescrever (`IA_REPAROS`, padrão 1). O serviço confere de novo no fim.
"""
import json
import logging
import time
from decimal import Decimal

from backend.ia import config, prompt
from backend.ia.politicas import ErroDoProvedor
from backend.ia.provedor import ContextoDoModelo, RespostaDoModelo

# multiplicadores publicados do cache de prompt (cache de 5 minutos): leitura 0,1x e
# escrita 1,25x o preço de entrada. Só se aplicam quando o preço de entrada foi
# configurado e o do cache não; confira no contrato da conta (D-1).
_MULT_CACHE_LEITURA = Decimal("0.1")
_MULT_CACHE_ESCRITA = Decimal("1.25")
_MILHAO = Decimal(1_000_000)

_PARADAS_OK = {"end_turn", "stop_sequence"}

# O SDK escreve a requisição INTEIRA (a pergunta e os dados que o modelo recebe) em log de
# nível DEBUG. Se alguém ligar DEBUG no processo para investigar outra coisa, a pergunta
# e o dado iriam para o log do servidor: um nível explícito no logger do SDK impede isso,
# qualquer que seja o nível do logger raiz. Os de transporte ficam em WARNING também.
for _nome in ("anthropic", "httpx2", "httpcore2"):
    logging.getLogger(_nome).setLevel(logging.WARNING)


def _tipo_do_erro(erro: Exception) -> str:
    """Uma palavra para a trilha. Olha só a CLASSE do erro do SDK (e o status HTTP), nunca
    a mensagem, que pode trazer trecho da requisição."""
    try:
        import anthropic
    except ImportError:  # pragma: no cover  (se o SDK não existe, não houve erro dele)
        return "provedor"

    # a ordem importa: o timeout é um caso da conexão, e a sobrecarga (529) um caso do 5xx
    for classe, tipo in (
        (anthropic.APITimeoutError, "timeout"),
        (anthropic.APIConnectionError, "conexao"),
        (anthropic.AuthenticationError, "autenticacao"),
        (anthropic.PermissionDeniedError, "permissao"),
        (anthropic.RateLimitError, "limite_de_taxa"),
        (anthropic.BadRequestError, "requisicao_invalida"),
        (anthropic.NotFoundError, "modelo_ou_rota_inexistente"),
        (anthropic.OverloadedError, "sobrecarga"),
        (anthropic.InternalServerError, "servico_do_provedor"),
    ):
        if isinstance(erro, classe):
            return tipo
    return "erro"


class UsoDaPergunta:
    """Soma do que a pergunta gastou no modelo, em todas as rodadas."""

    def __init__(self, modelo: str):
        self.modelo = modelo
        self.rodadas = 0
        self.reparos = 0
        self.entrada = self.saida = self.cache_leitura = self.cache_escrita = 0
        self.latencia_ms = 0
        self.inference_geo: str | None = None

    def somar(self, usage, duracao_ms: int) -> None:
        self.rodadas += 1
        self.latencia_ms += duracao_ms
        self.entrada += getattr(usage, "input_tokens", 0) or 0
        self.saida += getattr(usage, "output_tokens", 0) or 0
        self.cache_leitura += getattr(usage, "cache_read_input_tokens", 0) or 0
        self.cache_escrita += getattr(usage, "cache_creation_input_tokens", 0) or 0
        self.inference_geo = getattr(usage, "inference_geo", None) or self.inference_geo

    def custo_usd(self) -> Decimal | None:
        p = config.precos()
        if p["entrada"] is None or p["saida"] is None:
            return None
        entrada, saida = Decimal(str(p["entrada"])), Decimal(str(p["saida"]))
        leitura = Decimal(str(p["cache_leitura"])) if p["cache_leitura"] is not None else entrada * _MULT_CACHE_LEITURA
        escrita = Decimal(str(p["cache_escrita"])) if p["cache_escrita"] is not None else entrada * _MULT_CACHE_ESCRITA
        return (self.entrada * entrada + self.saida * saida
                + self.cache_leitura * leitura + self.cache_escrita * escrita) / _MILHAO

    def como_dict(self) -> dict:
        usd = self.custo_usd()
        cambio = config.precos()["cambio_brl"]
        brl = usd * Decimal(str(cambio)) if usd is not None and cambio is not None else None
        return {
            "modelo": self.modelo, "prompt": prompt.VERSAO, "rodadas": self.rodadas, "reparos": self.reparos,
            "tokens_entrada": self.entrada, "tokens_saida": self.saida,
            "tokens_cache_leitura": self.cache_leitura, "tokens_cache_escrita": self.cache_escrita,
            "latencia_modelo_ms": self.latencia_ms, "inference_geo": self.inference_geo,
            # texto, não float: o custo é dinheiro e vai para JSON sem perder casas
            "custo_usd": f"{usd:.6f}" if usd is not None else None,
            "custo_brl": f"{brl:.6f}" if brl is not None else None,
        }


# ================================================================ mensagens
def _ferramentas(esquemas: list[dict]) -> list[dict]:
    saida = [{"name": e["nome"], "description": e["descricao"], "input_schema": e["parametros"]} for e in esquemas]
    if saida:
        saida[-1] = {**saida[-1], "cache_control": {"type": "ephemeral"}}
    return saida


def _mensagens(historico: list[dict], pergunta: str) -> list[dict]:
    """Histórico + pergunta no formato da API: começa e termina em `user`, e papéis iguais
    em sequência são juntados (a API exige alternância)."""
    bruto = [{"role": "assistant" if h["papel"] == "ia" else "user", "content": h["texto"]}
             for h in historico if (h.get("texto") or "").strip()]
    bruto.append({"role": "user", "content": pergunta})
    saida: list[dict] = []
    for m in bruto:
        if not saida and m["role"] == "assistant":
            continue
        if saida and saida[-1]["role"] == m["role"]:
            saida[-1] = {"role": m["role"], "content": saida[-1]["content"] + "\n" + m["content"]}
        else:
            saida.append(m)
    return saida


def _bloco_de_volta(bloco) -> dict:
    """O bloco da resposta do modelo, no formato que a API aceita de volta. Texto e
    pedido de ferramenta ficam mínimos (campos extras do SDK seriam recusados); qualquer
    outro tipo (ex.: raciocínio) volta intacto, porque a API exige isso entre rodadas."""
    if bloco.type == "text":
        return {"type": "text", "text": bloco.text}
    if bloco.type == "tool_use":
        return {"type": "tool_use", "id": bloco.id, "name": bloco.name, "input": bloco.input}
    return bloco.model_dump(exclude_none=True)


def _texto_final(conteudo) -> str:
    return "".join(b.text for b in conteudo if b.type == "text").strip()


class ProvedorAnthropic:
    nome = "anthropic"
    rotulo = "Claude"

    def __init__(self, cliente=None, *, relogio=time.perf_counter):
        self._cliente = cliente        # injetável: os testes usam o SDK real sobre transporte simulado
        self._relogio = relogio
        self.uso_da_pergunta: UsoDaPergunta | None = None

    # -------------------------------------------------------------- cliente
    def _cliente_do_sdk(self):
        if self._cliente is None:
            chave = config.anthropic_api_key()
            if not chave:
                raise ErroDoProvedor("sem_chave")
            try:
                import anthropic
            except ImportError:
                raise ErroDoProvedor("sdk_ausente") from None
            self._cliente = anthropic.Anthropic(
                api_key=chave, timeout=config.timeout_do_provedor_s(),
                max_retries=config.tentativas_do_provedor())
        return self._cliente

    def _chamar(self, requisicao: dict, uso: UsoDaPergunta):
        cliente = self._cliente_do_sdk()
        inicio = self._relogio()
        try:
            resposta = cliente.messages.create(**requisicao)
        except ErroDoProvedor:
            raise
        except Exception as erro:
            raise ErroDoProvedor(_tipo_do_erro(erro)) from None   # `from None`: sem a mensagem do SDK
        uso.somar(resposta.usage, int((self._relogio() - inicio) * 1000))
        return resposta

    # --------------------------------------------------------------- laço
    def responder(self, c: ContextoDoModelo, executar) -> RespostaDoModelo:
        uso = self.uso_da_pergunta = UsoDaPergunta(config.modelo())
        inicio = self._relogio()
        prazo = config.prazo_da_pergunta_s()
        reparos = config.reparos_do_verificador()
        max_rodadas = config.max_passos_do_provedor() + reparos + 2

        requisicao = {
            "model": uso.modelo,
            "max_tokens": config.max_tokens_de_saida(),
            "system": [
                {"type": "text", "text": c.sistema, "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": prompt.cabecalho_da_pergunta(c.hoje, c.dominio)},
            ],
            "tools": _ferramentas(c.ferramentas),
        }
        if config.esforco():
            requisicao["output_config"] = {"effort": config.esforco()}
        if config.inference_geo():
            requisicao["inference_geo"] = config.inference_geo()
        mensagens = _mensagens(c.historico, c.pergunta)

        while True:
            if uso.rodadas >= max_rodadas:
                raise ErroDoProvedor("rodadas")
            if self._relogio() - inicio > prazo:
                raise ErroDoProvedor("prazo")
            resposta = self._chamar({**requisicao, "messages": mensagens}, uso)
            parada = resposta.stop_reason

            if parada == "tool_use":
                mensagens.append({"role": "assistant", "content": [_bloco_de_volta(b) for b in resposta.content]})
                resultados = []
                for bloco in resposta.content:
                    if bloco.type != "tool_use":
                        continue
                    saida = executar(bloco.name, bloco.input if isinstance(bloco.input, dict) else {})
                    resultados.append({
                        "type": "tool_result", "tool_use_id": bloco.id,
                        "content": json.dumps(saida, ensure_ascii=False, default=str),
                        "is_error": isinstance(saida, dict) and "erro" in saida,
                    })
                mensagens.append({"role": "user", "content": resultados})
                continue

            if parada == "max_tokens":
                raise ErroDoProvedor("resposta_truncada")
            if parada == "refusal":
                raise ErroDoProvedor("recusa_do_modelo")
            if parada not in _PARADAS_OK:
                raise ErroDoProvedor("parada_inesperada")

            texto = _texto_final(resposta.content)
            if not texto:
                raise ErroDoProvedor("resposta_vazia")
            reprovados = c.verificar(texto) if c.verificar is not None else []
            if reprovados and uso.reparos < reparos:
                uso.reparos += 1
                mensagens.append({"role": "assistant", "content": [_bloco_de_volta(b) for b in resposta.content]})
                mensagens.append({"role": "user", "content": (
                    "O Hub conferiu o seu texto e estes números não vieram de nenhuma ferramenta nesta "
                    f"conversa: {', '.join(reprovados[:10])}. Reescreva a resposta usando somente números "
                    "devolvidos pelas ferramentas, copiados como vieram, sem calcular nada. Se a conta que "
                    "falta não existe nas ferramentas, diga que ela não está disponível.")})
                continue
            return RespostaDoModelo(texto, uso.como_dict())
