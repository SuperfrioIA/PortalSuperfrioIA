"""Rotas do módulo Projetos IA.

Leitura exige só login (`ver` é o objetivo da tela — não se restringe por
role). Escrita exige a permissão `projetos-ia:editar` da matriz de acesso.

Catálogo de filiais (cadastro raro, feito por quem administra o portal) vive
em `router_admin`, mesmo padrão de `backend/portal/router.py` (App/Secao).
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from backend.auditoria import service as auditoria_service
from backend.auth.dependencies import get_current_user, require_admin, require_permissao
from backend.core.database import db
from backend.core.http import ensure_slug
from backend.projetos_ia import service
from backend.projetos_ia.permissoes import EDITAR

router = APIRouter(prefix="/api/projetos-ia", tags=["projetos-ia"])
router_admin = APIRouter(prefix="/api/admin", tags=["admin"])


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _iso(d: Optional[date]) -> Optional[str]:
    return d.isoformat() if d else None


class FaseJanela(BaseModel):
    previsto_inicio: date
    previsto_fim: Optional[date] = None


class ProjetoCreate(BaseModel):
    slug: str
    nome: str
    area: str
    objetivo: str
    problema: str
    beneficio: str
    publico: str
    acelerador: str
    responsavel_ti: Optional[str] = None
    key_user: Optional[str] = None
    proximo_marco_texto: Optional[str] = None
    proximo_marco_data: Optional[date] = None
    plano: list[FaseJanela] = Field(min_length=service.N_FASES, max_length=service.N_FASES)


class ProjetoUpdate(BaseModel):
    nome: Optional[str] = None
    area: Optional[str] = None
    objetivo: Optional[str] = None
    problema: Optional[str] = None
    beneficio: Optional[str] = None
    publico: Optional[str] = None
    acelerador: Optional[str] = None
    responsavel_ti: Optional[str] = None
    key_user: Optional[str] = None
    proximo_marco_texto: Optional[str] = None
    proximo_marco_data: Optional[date] = None


class FaseUpdate(BaseModel):
    previsto_inicio: Optional[date] = None
    previsto_fim: Optional[date] = None
    concluido_em: Optional[date] = None
    observacao: Optional[str] = None


class RolloutCreate(BaseModel):
    filial_id: int


class RolloutUpdate(BaseModel):
    data: Optional[date] = None
    publico_treinado: Optional[str] = None
    key_user_local: Optional[str] = None
    nao_se_aplica: Optional[bool] = None


class FilialCreate(BaseModel):
    # `codigo` é a chave de negócio (mesmo código do ERP, como no Conciliador):
    # obrigatório aqui e ausente do Update de propósito — não muda depois de criado.
    codigo: str = Field(min_length=1, max_length=20)
    nome: str = Field(min_length=1)
    cidade: Optional[str] = None
    uf: Optional[str] = Field(default=None, max_length=4)
    regiao: str
    responsavel: Optional[str] = None
    unidade_negocio_id: Optional[int] = None


class FilialUpdate(BaseModel):
    nome: Optional[str] = Field(default=None, min_length=1)
    cidade: Optional[str] = None
    uf: Optional[str] = Field(default=None, max_length=4)
    regiao: Optional[str] = None
    responsavel: Optional[str] = None
    unidade_negocio_id: Optional[int] = None


class UnidadeNegocioCreate(BaseModel):
    nome: str = Field(min_length=1, max_length=120)
    responsavel: Optional[str] = Field(default=None, max_length=120)


class UnidadeNegocioUpdate(BaseModel):
    # O nome PODE mudar: a filial liga por id, não por nome.
    nome: Optional[str] = Field(default=None, min_length=1, max_length=120)
    responsavel: Optional[str] = Field(default=None, max_length=120)


# ============ Projetos ============

@router.get("")
def listar(_: dict = Depends(get_current_user)):
    with db() as session:
        return service.listar_projetos(session)


@router.get("/filiais")
def listar_filiais_disponiveis(_: dict = Depends(get_current_user)):
    """Catálogo de filiais ativas — usado pra escolher quem entra no rollout.

    Registrada antes de `/{slug}` de propósito: rota estática tem prioridade
    sobre o path param na ordem de matching do FastAPI.
    """
    with db() as session:
        return service.listar_filiais(session, apenas_ativas=True)


@router.get("/{slug}")
def detalhe(slug: str, _: dict = Depends(get_current_user)):
    with db() as session:
        return service.detalhe_projeto(session, slug)


@router.post("", status_code=201)
def criar(body: ProjetoCreate, request: Request, user: dict = Depends(require_permissao(EDITAR))):
    ensure_slug(body.slug)
    dados = body.model_dump(exclude={"plano", "proximo_marco_data"})
    dados["proximo_marco_data"] = _iso(body.proximo_marco_data)
    plano = [
        {"previsto_inicio": _iso(f.previsto_inicio), "previsto_fim": _iso(f.previsto_fim)}
        for f in body.plano
    ]
    with db() as session:
        criado = service.criar_projeto(session, dados, plano)
        auditoria_service.registrar(
            session, categoria="projeto", acao="projeto.criar", resultado="ok",
            ator=user, ator_ip=_ip(request),
            alvo_tipo="projeto", alvo_id=criado["id"], alvo_rotulo=body.slug,
            detalhes={"nome": body.nome, "area": body.area},
        )
        return criado


@router.patch("/{slug}")
def atualizar(slug: str, body: ProjetoUpdate, request: Request, user: dict = Depends(require_permissao(EDITAR))):
    fields = body.model_dump(exclude_unset=True)
    if "proximo_marco_data" in fields:
        fields["proximo_marco_data"] = _iso(body.proximo_marco_data)
    with db() as session:
        atual = service.projeto_por_slug_or_404(session, slug)
        atualizado = service.atualizar_projeto(session, slug, fields)
        auditoria_service.registrar(
            session, categoria="projeto", acao="projeto.atualizar", resultado="ok",
            ator=user, ator_ip=_ip(request),
            alvo_tipo="projeto", alvo_id=atual["id"], alvo_rotulo=slug,
            detalhes=auditoria_service.diff(atual, fields),
        )
        return atualizado


@router.patch("/{slug}/fases/{ordem}")
def atualizar_fase(slug: str, ordem: int, body: FaseUpdate, request: Request, user: dict = Depends(require_permissao(EDITAR))):
    fields = body.model_dump(exclude_unset=True)
    for campo in ("previsto_inicio", "previsto_fim", "concluido_em"):
        if campo in fields:
            fields[campo] = _iso(getattr(body, campo))
    with db() as session:
        resultado = service.atualizar_fase(session, slug, ordem, fields, user.get("nome") or user["username"])
        auditoria_service.registrar(
            session, categoria="projeto", acao="projeto.fase", resultado="ok",
            ator=user, ator_ip=_ip(request),
            alvo_tipo="projeto", alvo_id=resultado["id"], alvo_rotulo=f"{slug} fase {ordem}",
            detalhes=fields,
        )
        return resultado


# ============ Rollout ============

@router.post("/{slug}/rollout", status_code=201)
def incluir_rollout(slug: str, body: RolloutCreate, request: Request, user: dict = Depends(require_permissao(EDITAR))):
    with db() as session:
        resultado = service.incluir_rollout(session, slug, body.filial_id)
        auditoria_service.registrar(
            session, categoria="projeto", acao="projeto.rollout.incluir", resultado="ok",
            ator=user, ator_ip=_ip(request),
            alvo_tipo="projeto", alvo_id=resultado["id"], alvo_rotulo=slug,
            detalhes={"filial_id": body.filial_id},
        )
        return resultado


@router.patch("/{slug}/rollout/{filial_id}")
def atualizar_rollout(slug: str, filial_id: int, body: RolloutUpdate, request: Request, user: dict = Depends(require_permissao(EDITAR))):
    fields = body.model_dump(exclude_unset=True)
    if "data" in fields:
        fields["data"] = _iso(body.data)
    if "nao_se_aplica" in fields:
        # Coluna é Integer (0/1), não Boolean — mesma convenção de `ativo`/`is_admin`
        # no resto da casa. Converter aqui evita depender de o driver do banco
        # aceitar bool Python num bind de Integer (SQLite aceita, Postgres não).
        fields["nao_se_aplica"] = int(fields["nao_se_aplica"])
    with db() as session:
        resultado = service.atualizar_rollout(session, slug, filial_id, fields)
        auditoria_service.registrar(
            session, categoria="projeto", acao="projeto.rollout.atualizar", resultado="ok",
            ator=user, ator_ip=_ip(request),
            alvo_tipo="projeto", alvo_id=resultado["id"], alvo_rotulo=f"{slug} filial {filial_id}",
            detalhes=fields,
        )
        return resultado


@router.delete("/{slug}/rollout/{filial_id}")
def remover_rollout(slug: str, filial_id: int, request: Request, user: dict = Depends(require_permissao(EDITAR))):
    with db() as session:
        resultado = service.remover_rollout(session, slug, filial_id)
        auditoria_service.registrar(
            session, categoria="projeto", acao="projeto.rollout.remover", resultado="ok",
            ator=user, ator_ip=_ip(request),
            alvo_tipo="projeto", alvo_id=resultado["id"], alvo_rotulo=f"{slug} filial {filial_id}",
        )
        return resultado


# ============ Filiais (catálogo, admin) ============

@router_admin.get("/filiais")
def admin_listar_filiais(_: dict = Depends(require_admin)):
    with db() as session:
        return service.listar_filiais(session)


@router_admin.post("/filiais", status_code=201)
def admin_criar_filial(body: FilialCreate, request: Request, admin: dict = Depends(require_admin)):
    with db() as session:
        criada = service.criar_filial(session, body.model_dump())
        auditoria_service.registrar(
            session, categoria="admin", acao="filial.criar", resultado="ok",
            ator=admin, ator_ip=_ip(request),
            alvo_tipo="filial", alvo_id=criada["id"], alvo_rotulo=body.codigo,
            detalhes={"nome": body.nome, "codigo": body.codigo, "regiao": body.regiao},
        )
        return criada


@router_admin.patch("/filiais/{filial_id}")
def admin_atualizar_filial(filial_id: int, body: FilialUpdate, request: Request, admin: dict = Depends(require_admin)):
    with db() as session:
        atual = service.filial_por_id(session, filial_id)
        fields = body.model_dump(exclude_unset=True)
        atualizada = service.atualizar_filial(session, filial_id, fields)
        auditoria_service.registrar(
            session, categoria="admin", acao="filial.atualizar", resultado="ok",
            ator=admin, ator_ip=_ip(request),
            alvo_tipo="filial", alvo_id=filial_id, alvo_rotulo=(atual or {}).get("codigo"),
            detalhes=auditoria_service.diff(atual or {}, fields),
        )
        return atualizada


@router_admin.post("/filiais/{filial_id}/toggle")
def admin_toggle_filial(filial_id: int, request: Request, admin: dict = Depends(require_admin)):
    with db() as session:
        atual = service.filial_por_id(session, filial_id)
        toggled = service.toggle_filial(session, filial_id)
        auditoria_service.registrar(
            session, categoria="admin", acao="filial.toggle", resultado="ok",
            ator=admin, ator_ip=_ip(request),
            alvo_tipo="filial", alvo_id=filial_id, alvo_rotulo=(atual or {}).get("codigo"),
            detalhes={"ativo": {"de": bool((atual or {}).get("ativo")), "para": bool(toggled.get("ativo"))}},
        )
        return toggled


# ============ Unidades de negócio (B.U — catálogo, admin) ============

@router_admin.get("/unidades-negocio")
def admin_listar_unidades_negocio(_: dict = Depends(require_admin)):
    with db() as session:
        return service.listar_unidades_negocio(session)


def _unidade_negocio_atual(session, unidade_id: int) -> dict:
    """Sem getter público por id no service (catálogo pequeno) — filtra a
    listagem, barato o bastante para uma tabela de dezenas de linhas."""
    return next(
        (u for u in service.listar_unidades_negocio(session) if u["id"] == unidade_id), {}
    )


@router_admin.post("/unidades-negocio", status_code=201)
def admin_criar_unidade_negocio(body: UnidadeNegocioCreate, request: Request, admin: dict = Depends(require_admin)):
    with db() as session:
        criada = service.criar_unidade_negocio(session, body.model_dump())
        auditoria_service.registrar(
            session, categoria="admin", acao="unidade.criar", resultado="ok",
            ator=admin, ator_ip=_ip(request),
            alvo_tipo="unidade_negocio", alvo_id=criada["id"], alvo_rotulo=body.nome,
            detalhes={"nome": body.nome, "responsavel": body.responsavel},
        )
        return criada


@router_admin.patch("/unidades-negocio/{unidade_id}")
def admin_atualizar_unidade_negocio(
    unidade_id: int, body: UnidadeNegocioUpdate, request: Request, admin: dict = Depends(require_admin)
):
    with db() as session:
        atual = _unidade_negocio_atual(session, unidade_id)
        fields = body.model_dump(exclude_unset=True)
        atualizada = service.atualizar_unidade_negocio(session, unidade_id, fields)
        auditoria_service.registrar(
            session, categoria="admin", acao="unidade.atualizar", resultado="ok",
            ator=admin, ator_ip=_ip(request),
            alvo_tipo="unidade_negocio", alvo_id=unidade_id, alvo_rotulo=atual.get("nome"),
            detalhes=auditoria_service.diff(atual, fields),
        )
        return atualizada


@router_admin.post("/unidades-negocio/{unidade_id}/toggle")
def admin_toggle_unidade_negocio(unidade_id: int, request: Request, admin: dict = Depends(require_admin)):
    with db() as session:
        atual = _unidade_negocio_atual(session, unidade_id)
        toggled = service.toggle_unidade_negocio(session, unidade_id)
        auditoria_service.registrar(
            session, categoria="admin", acao="unidade.toggle", resultado="ok",
            ator=admin, ator_ip=_ip(request),
            alvo_tipo="unidade_negocio", alvo_id=unidade_id, alvo_rotulo=atual.get("nome"),
            detalhes={"ativo": {"de": bool(atual.get("ativo")), "para": bool(toggled.get("ativo"))}},
        )
        return toggled
