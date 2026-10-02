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
import re
import threading
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

def _travar_logs() -> None:
    """O SDK escreve a requisição INTEIRA (a pergunta e os dados que o modelo recebe) em log
    DEBUG. Se alguém ligar DEBUG no processo, a pergunta e o dado iriam para o log do servidor:
    um nível explícito nos loggers do SDK impede isso, qualquer que seja o nível do raiz.

    Tem que valer DEPOIS do `import anthropic`: ao ser importado, o SDK lê `ANTHROPIC_LOG`
    (`debug`/`info`) e reconfigura os próprios loggers, desfazendo uma trava feita antes. Por
    isso é chamada no import deste módulo e de novo logo depois de cada `import anthropic`."""
    for nome in ("anthropic", "httpx2", "httpcore2"):
        logging.getLogger(nome).setLevel(logging.WARNING)


_travar_logs()

# Um cliente do SDK por processo (pool de conexões e TLS reaproveitados entre perguntas), recriado
# só se a configuração mudar. O provedor é criado a cada pergunta; o cliente não.
_COMPARTILHADO: dict = {"assinatura": None, "cliente": None}
_TRAVA_DO_CLIENTE = threading.Lock()


def _reiniciar_cliente_compartilhado() -> None:
    with _TRAVA_DO_CLIENTE:
        _COMPARTILHADO.update({"assinatura": None, "cliente": None})


def _diagnostico(erro: Exception) -> tuple[int | None, str | None]:
    """O status HTTP e o `error.type` da API (uma palavra de um conjunto fixo), para o primeiro
    erro real dizer o que foi (400? 401? 404?) sem expor a mensagem."""
    status = getattr(erro, "status_code", None)
    corpo = getattr(erro, "body", None)
    tipo_api = corpo.get("error", {}).get("type") if isinstance(corpo, dict) and isinstance(corpo.get("error"), dict) else None
    ok = isinstance(tipo_api, str) and re.fullmatch(r"[a-z_]{3,40}", tipo_api) is not None
    return (status if isinstance(status, int) else None), (tipo_api if ok else None)


def _tipo_do_erro(erro: Exception) -> str:
    """Uma palavra para a trilha. Olha só a CLASSE do erro do SDK (e o status HTTP), nunca
    a mensagem, que pode trazer trecho da requisição."""
    try:
        import anthropic
    except ImportError:  # pragma: no cover  (se o SDK não existe, não houve erro dele)
        return "provedor"
    _travar_logs()

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
    # "\n" entre blocos de texto: sem separador, o fim de um bloco colaria no número do seguinte
    return "\n".join(b.text for b in conteudo if b.type == "text").strip()


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
            _travar_logs()                      # o import acima pode ter religado o log (ANTHROPIC_LOG)
            assinatura = (chave, config.timeout_do_provedor_s(), config.tentativas_do_provedor())
            with _TRAVA_DO_CLIENTE:
                if _COMPARTILHADO["assinatura"] != assinatura:
                    antigo = _COMPARTILHADO["cliente"]
                    _COMPARTILHADO["cliente"] = anthropic.Anthropic(
                        api_key=chave, timeout=assinatura[1], max_retries=assinatura[2])
                    _COMPARTILHADO["assinatura"] = assinatura
                    if antigo is not None and hasattr(antigo, "close"):
                        antigo.close()
                self._cliente = _COMPARTILHADO["cliente"]
        return self._cliente

    def _chamar(self, requisicao: dict, uso: UsoDaPergunta):
        cliente = self._cliente_do_sdk()
        inicio = self._relogio()
        try:
            resposta = cliente.messages.create(**requisicao)
        except ErroDoProvedor:
            raise
        except Exception as erro:
            status, tipo_api = _diagnostico(erro)
            # `from None`: sem a mensagem do SDK, que pode trazer trecho da requisição
            raise ErroDoProvedor(_tipo_do_erro(erro), status=status, tipo_api=tipo_api) from None
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
            restante = prazo - (self._relogio() - inicio)
            if restante <= 0:
                raise ErroDoProvedor("prazo")
            # cada tentativa nunca pede mais tempo do que o que resta do prazo (mínimo de 1 s)
            tempo = max(1.0, min(config.timeout_do_provedor_s(), restante))
            resposta = self._chamar({**requisicao, "messages": mensagens, "timeout": tempo}, uso)
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
