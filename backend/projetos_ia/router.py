"""Rotas do módulo Projetos IA.

Leitura exige só login (`ver` é o objetivo da tela — não se restringe por
role). Escrita exige a permissão `projetos-ia:editar` da matriz de acesso.

Catálogo de filiais (cadastro raro, feito por quem administra o portal) vive
em `router_admin`, mesmo padrão de `backend/portal/router.py` (App/Secao).
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from backend.auth.dependencies import get_current_user, require_admin, require_permissao
from backend.core.database import db
from backend.core.http import ensure_slug
from backend.projetos_ia import service
from backend.projetos_ia.permissoes import EDITAR

router = APIRouter(prefix="/api/projetos-ia", tags=["projetos-ia"])
router_admin = APIRouter(prefix="/api/admin", tags=["admin"])


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
    nome: str
    uf: Optional[str] = None
    regiao: str


class FilialUpdate(BaseModel):
    nome: Optional[str] = None
    uf: Optional[str] = None
    regiao: Optional[str] = None


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
def criar(body: ProjetoCreate, _: dict = Depends(require_permissao(EDITAR))):
    ensure_slug(body.slug)
    dados = body.model_dump(exclude={"plano", "proximo_marco_data"})
    dados["proximo_marco_data"] = _iso(body.proximo_marco_data)
    plano = [
        {"previsto_inicio": _iso(f.previsto_inicio), "previsto_fim": _iso(f.previsto_fim)}
        for f in body.plano
    ]
    with db() as session:
        return service.criar_projeto(session, dados, plano)


@router.patch("/{slug}")
def atualizar(slug: str, body: ProjetoUpdate, _: dict = Depends(require_permissao(EDITAR))):
    fields = body.model_dump(exclude_unset=True)
    if "proximo_marco_data" in fields:
        fields["proximo_marco_data"] = _iso(body.proximo_marco_data)
    with db() as session:
        return service.atualizar_projeto(session, slug, fields)


@router.patch("/{slug}/fases/{ordem}")
def atualizar_fase(slug: str, ordem: int, body: FaseUpdate, user: dict = Depends(require_permissao(EDITAR))):
    fields = body.model_dump(exclude_unset=True)
    for campo in ("previsto_inicio", "previsto_fim", "concluido_em"):
        if campo in fields:
            fields[campo] = _iso(getattr(body, campo))
    with db() as session:
        return service.atualizar_fase(session, slug, ordem, fields, user.get("nome") or user["username"])


# ============ Rollout ============

@router.post("/{slug}/rollout", status_code=201)
def incluir_rollout(slug: str, body: RolloutCreate, _: dict = Depends(require_permissao(EDITAR))):
    with db() as session:
        return service.incluir_rollout(session, slug, body.filial_id)


@router.patch("/{slug}/rollout/{filial_id}")
def atualizar_rollout(slug: str, filial_id: int, body: RolloutUpdate, _: dict = Depends(require_permissao(EDITAR))):
    fields = body.model_dump(exclude_unset=True)
    if "data" in fields:
        fields["data"] = _iso(body.data)
    if "nao_se_aplica" in fields:
        # Coluna é Integer (0/1), não Boolean — mesma convenção de `ativo`/`is_admin`
        # no resto da casa. Converter aqui evita depender de o driver do banco
        # aceitar bool Python num bind de Integer (SQLite aceita, Postgres não).
        fields["nao_se_aplica"] = int(fields["nao_se_aplica"])
    with db() as session:
        return service.atualizar_rollout(session, slug, filial_id, fields)


@router.delete("/{slug}/rollout/{filial_id}")
def remover_rollout(slug: str, filial_id: int, _: dict = Depends(require_permissao(EDITAR))):
    with db() as session:
        return service.remover_rollout(session, slug, filial_id)


# ============ Filiais (catálogo, admin) ============

@router_admin.get("/filiais")
def admin_listar_filiais(_: dict = Depends(require_admin)):
    with db() as session:
        return service.listar_filiais(session)


@router_admin.post("/filiais", status_code=201)
def admin_criar_filial(body: FilialCreate, _: dict = Depends(require_admin)):
    with db() as session:
        return service.criar_filial(session, body.model_dump())


@router_admin.patch("/filiais/{filial_id}")
def admin_atualizar_filial(filial_id: int, body: FilialUpdate, _: dict = Depends(require_admin)):
    with db() as session:
        return service.atualizar_filial(session, filial_id, body.model_dump(exclude_unset=True))


@router_admin.post("/filiais/{filial_id}/toggle")
def admin_toggle_filial(filial_id: int, _: dict = Depends(require_admin)):
    with db() as session:
        return service.toggle_filial(session, filial_id)
