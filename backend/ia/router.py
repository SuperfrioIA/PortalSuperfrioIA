"""Rotas do SuperfrioIA (`/api/ia`).

## A chave `IA_HABILITADO` (DD-27)

Todas as rotas passam por `_so_habilitado`, a **primeira** dependência do router:
com a chave desligada devolvem **404**, igual a uma rota que não existe, e isso
acontece antes da autenticação (nada vaza que o módulo existe). A chave é lida a
cada requisição; as rotas ficam sempre registradas. É isso que deixa o teste ligar
e desligar no mesmo processo.

## Guardas

- toda rota: login + `superfrioia:ver` (visibilidade do card);
- perguntar, ler conversa: as portas do domínio, **revalidadas agora**
  (`permissoes.exigir_acesso`: `<app_hub>:ver` e concessão vigente);
- fila e decisões de concessão: `<app_hub>:administrar` **do domínio do pedido**.
  Um aprovador da volumetria não decide pedido de outro domínio, e o admin do Hub
  passa pelo bypass de `usuario_pode` (aceito, DD-13).

`Recusa` vira `HTTPException` com o status e a mensagem dela; mensagens de acesso
negado são neutras (sem dizer qual porta falhou).
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from backend.auditoria import service as trilha
from backend.auth.dependencies import get_current_user, usuario_pode
from backend.ia import config, dominios, permissoes, service
from backend.ia.politicas import Recusa

VER = f"{config.SLUG_APP}:ver"


def _so_habilitado() -> None:
    if not config.habilitado():
        raise HTTPException(status_code=404, detail="Not Found")


# `include_in_schema=False`: o /docs e o /openapi.json do FastAPI listariam /api/ia/* mesmo com a
# chave desligada, e nada pode revelar que o módulo existe enquanto ela estiver assim.
router = APIRouter(prefix="/api/ia", tags=["superfrioia"], dependencies=[Depends(_so_habilitado)],
                   include_in_schema=False)


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def require_ver_ia(request: Request, user: dict = Depends(get_current_user)) -> dict:
    if not usuario_pode(user, VER):
        trilha.registrar(
            categoria="acesso", acao="acesso.negado", resultado="negado", ator=user, ator_ip=_ip(request),
            app_slug=config.SLUG_APP, detalhes={"rota": request.url.path, "exigia": VER})
        raise HTTPException(status_code=403, detail="Você não tem acesso ao SuperfrioIA.")
    return user


def _http(recusa: Recusa) -> HTTPException:
    return HTTPException(status_code=recusa.status, detail=recusa.mensagem)


def _dominio(slug: str):
    dominio = dominios.obter(slug)
    if dominio is None:
        raise HTTPException(status_code=404, detail="Domínio não encontrado.")
    return dominio


def _exigir_administrar(user: dict, slug: str, request: Request):
    dominio = _dominio(slug)
    if not permissoes.pode_administrar(user, dominio):
        trilha.registrar(
            categoria="acesso", acao="acesso.negado", resultado="negado", ator=user, ator_ip=_ip(request),
            app_slug=config.SLUG_APP,
            detalhes={"rota": request.url.path, "exigia": dominio.permissao_de_aprovacao})
        raise HTTPException(
            status_code=403,
            detail=f"Requer a permissão de administrar este domínio ({dominio.permissao_de_aprovacao}).")
    return dominio


# --------------------------------------------------------------- modelos
class PerguntaIn(BaseModel):
    dominio: str
    pergunta: str
    conversa_id: int | None = None


class PedidoIn(BaseModel):
    dominio: str = Field(max_length=80)
    motivo: str = Field(max_length=2000)   # o limite de negócio (500) vale depois da máscara


# O teto no servidor, não só no `maxlength` da tela: a trilha trunca `detalhes` acima de 4 KB e
# trocaria o evento inteiro (aprovador, validade, autoaprovação) por `{"_truncado": true}`.
MOTIVO_MAXIMO = 500


class AprovacaoIn(BaseModel):
    motivo: str | None = Field(default=None, max_length=MOTIVO_MAXIMO)
    validade_dias: int | None = None


class MotivoIn(BaseModel):
    motivo: str = Field(max_length=MOTIVO_MAXIMO)


class FeedbackIn(BaseModel):
    valor: int


# ------------------------------------------------------------------ rotas
@router.get("/dominios")
def listar_dominios(user: dict = Depends(require_ver_ia)):
    return service.listar_dominios(user)


@router.post("/perguntas")
def perguntar(corpo: PerguntaIn, request: Request, user: dict = Depends(require_ver_ia)):
    try:
        return service.perguntar(
            user, dominio_slug=corpo.dominio, pergunta=corpo.pergunta,
            conversa_id=corpo.conversa_id, ip=_ip(request))
    except Recusa as recusa:
        raise _http(recusa) from None


@router.get("/conversas")
def listar_conversas(user: dict = Depends(require_ver_ia)):
    return service.listar_conversas(user)


@router.get("/conversas/{conversa_id}")
def obter_conversa(conversa_id: int, user: dict = Depends(require_ver_ia)):
    try:
        return service.obter_conversa(user, conversa_id)
    except Recusa as recusa:
        raise _http(recusa) from None


@router.post("/mensagens/{mensagem_id}/feedback")
def feedback(mensagem_id: int, corpo: FeedbackIn, user: dict = Depends(require_ver_ia)):
    try:
        service.dar_feedback(user, mensagem_id, corpo.valor)
    except Recusa as recusa:
        raise _http(recusa) from None
    return {"ok": True}


# -- pedido de acesso (o próprio usuário)
@router.post("/concessoes/pedidos", status_code=201)
def pedir_acesso(corpo: PedidoIn, request: Request, user: dict = Depends(require_ver_ia)):
    dominio = _dominio(corpo.dominio)
    try:
        return permissoes.pedir_acesso(user, dominio, corpo.motivo, _ip(request))
    except Recusa as recusa:
        raise _http(recusa) from None


@router.get("/concessoes/minhas")
def minhas_concessoes(user: dict = Depends(require_ver_ia)):
    return permissoes.minhas_concessoes(user)


# -- administração (quem tem <app_hub>:administrar do domínio)
@router.get("/administracao/concessoes")
def listar_concessoes(dominio: str, request: Request, status: str | None = None,
                      user: dict = Depends(require_ver_ia)):
    dom = _exigir_administrar(user, dominio, request)
    return permissoes.listar(dom, status)


def _decidir(concessao_id: int, request: Request, user: dict):
    slug = permissoes.dominio_da_concessao(concessao_id)
    if slug is None:
        raise HTTPException(status_code=404, detail="Pedido não encontrado.")
    _exigir_administrar(user, slug, request)


@router.post("/administracao/concessoes/{concessao_id}/aprovar")
def aprovar(concessao_id: int, corpo: AprovacaoIn, request: Request, user: dict = Depends(require_ver_ia)):
    _decidir(concessao_id, request, user)
    try:
        return permissoes.aprovar(user, concessao_id, motivo=corpo.motivo,
                                  validade_dias=corpo.validade_dias, ip=_ip(request))
    except Recusa as recusa:
        raise _http(recusa) from None


@router.post("/administracao/concessoes/{concessao_id}/negar")
def negar(concessao_id: int, corpo: MotivoIn, request: Request, user: dict = Depends(require_ver_ia)):
    _decidir(concessao_id, request, user)
    try:
        return permissoes.negar(user, concessao_id, motivo=corpo.motivo, ip=_ip(request))
    except Recusa as recusa:
        raise _http(recusa) from None


@router.post("/administracao/concessoes/{concessao_id}/revogar")
def revogar(concessao_id: int, corpo: MotivoIn, request: Request, user: dict = Depends(require_ver_ia)):
    _decidir(concessao_id, request, user)
    try:
        return permissoes.revogar(user, concessao_id, motivo=corpo.motivo, ip=_ip(request))
    except Recusa as recusa:
        raise _http(recusa) from None


# Qualquer outro caminho ou método sob /api/ia responde 404, igual a uma rota que não existe.
# Sem isto, método errado numa rota real devolveria 405 antes das dependências do router (o
# roteamento vem primeiro) e denunciaria que o módulo existe com a chave desligada.
@router.api_route("/{caminho:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
                  include_in_schema=False)
def inexistente(caminho: str):
    raise HTTPException(status_code=404, detail="Not Found")
