"""Rotas do Portal: home (/api/portal) e administração do catálogo (/api/admin).

Princípios (herdados do CRUD original):
- Toggle ativo/inativo em vez de DELETE (auditável).
- PATCH é parcial: só atualiza o que vier no body.
- Slug é stable: nunca é editado depois de criado.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, insert, select, update

from backend.auth.dependencies import get_current_user, require_admin
from backend.core.database import _now, db
from backend.core.http import apply_update, ensure_slug, row_or_404, unique_or_409
from backend.portal import service
from backend.portal.models import App, Secao
from backend.usuarios import service as usuarios_service

router = APIRouter(prefix="/api/portal", tags=["portal"])
router_admin = APIRouter(prefix="/api/admin", tags=["admin"])


# ============ Home ============

@router.get("/home")
def home(user: dict = Depends(get_current_user)):
    """Estrutura pronta pro frontend: lista de seções com seus apps."""
    with db() as session:
        if user.get("is_admin"):
            apps = service.apps_ativos_com_secao(session)
        else:
            permitidos = usuarios_service.app_ids_permitidos(session, user["id"])
            apps = service.apps_ativos_com_secao(session, app_ids=permitidos)

    secoes: dict[str, dict] = {}
    for a in apps:
        slug = a["secao_slug"]
        if slug not in secoes:
            secoes[slug] = {
                "slug": slug,
                "nome": a["secao_nome"],
                "nome_es": a["secao_nome_es"],
                "icone": a["secao_icone"],
                "ordem": a["secao_ordem"],
                "apps": [],
            }
        secoes[slug]["apps"].append({
            "slug": a["slug"],
            "nome": a["nome"],
            "nome_es": a["nome_es"],
            "descricao": a["descricao"],
            "descricao_es": a["descricao_es"],
            "icone": a["icone"],
            "url": a["url"],
            "tipo_acesso": a["tipo_acesso"],
            "badge": a["badge"],
        })

    return {
        "user": {
            "username": user["username"],
            "nome": user["nome"],
            "is_admin": bool(user["is_admin"]),
        },
        "secoes": sorted(secoes.values(), key=lambda s: s["ordem"]),
    }


# ============ Seções (admin) ============

class SecaoCreate(BaseModel):
    slug: str
    nome: str
    nome_es: Optional[str] = None
    descricao: Optional[str] = None
    descricao_es: Optional[str] = None
    icone: Optional[str] = None
    ordem: int = 0


class SecaoUpdate(BaseModel):
    nome: Optional[str] = None
    nome_es: Optional[str] = None
    descricao: Optional[str] = None
    descricao_es: Optional[str] = None
    icone: Optional[str] = None
    ordem: Optional[int] = None


@router_admin.get("/secoes")
def listar_secoes(_: dict = Depends(require_admin)):
    with db() as session:
        rows = session.execute(
            select(*Secao.__table__.c, func.count(App.id).label("apps_count"))
            .join_from(Secao, App, App.secao_id == Secao.id, isouter=True)
            .group_by(Secao.id)
            .order_by(Secao.ordem, Secao.nome)
        ).mappings().fetchall()
    return [dict(r) for r in rows]


@router_admin.post("/secoes", status_code=201)
def criar_secao(body: SecaoCreate, _: dict = Depends(require_admin)):
    ensure_slug(body.slug)
    with db() as session:
        with unique_or_409("slug", body.slug):
            cur = session.execute(
                insert(Secao).values(
                    slug=body.slug, nome=body.nome, nome_es=body.nome_es,
                    descricao=body.descricao, descricao_es=body.descricao_es,
                    icone=body.icone, ordem=body.ordem,
                )
            )
        return row_or_404(session, Secao, cur.inserted_primary_key[0], "secoes")


@router_admin.patch("/secoes/{secao_id}")
def atualizar_secao(secao_id: int, body: SecaoUpdate, _: dict = Depends(require_admin)):
    with db() as session:
        row_or_404(session, Secao, secao_id, "secoes")
        fields = body.model_dump(exclude_unset=True)
        if not fields:
            return row_or_404(session, Secao, secao_id, "secoes")
        apply_update(session, Secao, secao_id, fields)
        return row_or_404(session, Secao, secao_id, "secoes")


@router_admin.post("/secoes/{secao_id}/toggle")
def toggle_secao(secao_id: int, _: dict = Depends(require_admin)):
    with db() as session:
        row = row_or_404(session, Secao, secao_id, "secoes")
        novo = 0 if row["ativo"] else 1
        session.execute(update(Secao).where(Secao.id == secao_id).values(ativo=novo))
        return row_or_404(session, Secao, secao_id, "secoes")


# ============ Apps (admin) ============

class AppCreate(BaseModel):
    slug: str
    nome: str
    nome_es: Optional[str] = None
    secao_id: int
    url: str
    descricao: Optional[str] = None
    descricao_es: Optional[str] = None
    icone: Optional[str] = None
    tipo_acesso: str = "url"
    badge: Optional[str] = None
    ordem: int = 0


class AppUpdate(BaseModel):
    nome: Optional[str] = None
    nome_es: Optional[str] = None
    descricao: Optional[str] = None
    descricao_es: Optional[str] = None
    icone: Optional[str] = None
    secao_id: Optional[int] = None
    url: Optional[str] = None
    tipo_acesso: Optional[str] = None
    badge: Optional[str] = None
    ordem: Optional[int] = None


def _check_tipo_acesso(tipo: Optional[str]) -> None:
    if tipo is not None and tipo not in ("url", "iframe"):
        raise HTTPException(400, "tipo_acesso deve ser 'url' ou 'iframe'")


def _check_url(url: Optional[str]) -> None:
    if url is None:
        return
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "url deve começar com http:// ou https://")


_APP_COM_SECAO = (
    select(
        *App.__table__.c,
        Secao.slug.label("secao_slug"),
        Secao.nome.label("secao_nome"),
    )
    .join_from(App, Secao, Secao.id == App.secao_id)
)


def _select_app(session, app_id: int) -> dict:
    row = session.execute(
        _APP_COM_SECAO.where(App.id == app_id)
    ).mappings().fetchone()
    if not row:
        raise HTTPException(404, f"app {app_id} não encontrado")
    return dict(row)


@router_admin.get("/apps")
def listar_apps(_: dict = Depends(require_admin)):
    with db() as session:
        rows = session.execute(
            _APP_COM_SECAO.order_by(Secao.ordem, App.ordem, App.nome)
        ).mappings().fetchall()
    return [dict(r) for r in rows]


@router_admin.post("/apps", status_code=201)
def criar_app(body: AppCreate, _: dict = Depends(require_admin)):
    ensure_slug(body.slug)
    _check_tipo_acesso(body.tipo_acesso)
    _check_url(body.url)
    with db() as session:
        row_or_404(session, Secao, body.secao_id, "secoes")
        with unique_or_409("slug", body.slug):
            cur = session.execute(
                insert(App).values(
                    slug=body.slug, nome=body.nome, nome_es=body.nome_es,
                    descricao=body.descricao, descricao_es=body.descricao_es,
                    icone=body.icone, secao_id=body.secao_id, url=body.url,
                    tipo_acesso=body.tipo_acesso, badge=body.badge, ordem=body.ordem,
                )
            )
        return _select_app(session, cur.inserted_primary_key[0])


@router_admin.patch("/apps/{app_id}")
def atualizar_app(app_id: int, body: AppUpdate, _: dict = Depends(require_admin)):
    _check_tipo_acesso(body.tipo_acesso)
    _check_url(body.url)
    with db() as session:
        row_or_404(session, App, app_id, "apps")
        if body.secao_id is not None:
            row_or_404(session, Secao, body.secao_id, "secoes")
        fields = body.model_dump(exclude_unset=True)
        if not fields:
            return _select_app(session, app_id)
        apply_update(session, App, app_id, fields, touch_updated=True)
        return _select_app(session, app_id)


@router_admin.post("/apps/{app_id}/toggle")
def toggle_app(app_id: int, _: dict = Depends(require_admin)):
    with db() as session:
        row = row_or_404(session, App, app_id, "apps")
        novo = 0 if row["ativo"] else 1
        session.execute(
            update(App).where(App.id == app_id).values(ativo=novo, atualizado_em=_now())
        )
        return _select_app(session, app_id)
