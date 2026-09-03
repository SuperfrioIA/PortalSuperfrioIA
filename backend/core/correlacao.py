"""ID de correlação por requisição — liga o log técnico ao evento de auditoria.

Sem isto, o log de acesso (`backend.acesso`) e a trilha de auditoria não têm
como se juntar além de bater horário — foi um diagnóstico inteiro em produção
que os proxy headers já custaram (ver `Dockerfile`); correlação evita repetir
o problema para quem for investigar um evento.

Gerado como `uuid4`, ou reaproveitado do `X-Amzn-Trace-Id` do ALB quando ele
vier — mais barato que gerar um segundo id para a mesma requisição, e o
suficiente porque nada aqui depende do formato interno do trace da AWS, só
usa como string opaca.

Guardado em `ContextVar` (não em `request.state`) porque quem grava o evento
de auditoria costuma estar vários níveis abaixo do handler HTTP (dentro de um
`service.py` de outro módulo), sem acesso fácil ao `Request`.
"""
import uuid
from contextvars import ContextVar

from fastapi import Request
from fastapi.responses import Response

_correlacao_atual: ContextVar[str | None] = ContextVar("correlacao_atual", default=None)

HEADER_RESPOSTA = "X-Request-ID"
_HEADER_ALB = "x-amzn-trace-id"


def correlacao_id() -> str | None:
    """O id da requisição em curso, ou `None` fora de um request (ex.: job agendado)."""
    return _correlacao_atual.get()


async def middleware_correlacao(request: Request, call_next) -> Response:
    """Registra o id da requisição atual no ContextVar e devolve no header de resposta.

    Precisa rodar ANTES de `log_de_acesso` (`backend/main.py`) para o log
    técnico já sair com o id."""
    valor = request.headers.get(_HEADER_ALB) or str(uuid.uuid4())
    token = _correlacao_atual.set(valor)
    try:
        response = await call_next(request)
    finally:
        _correlacao_atual.reset(token)
    response.headers[HEADER_RESPOSTA] = valor
    return response
