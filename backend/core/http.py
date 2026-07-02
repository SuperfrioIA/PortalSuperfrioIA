"""Helpers HTTP genéricos usados pelos routers dos módulos.

São infra (validação de slug, 404 por id, update parcial, 409 de UNIQUE):
recebem o model do módulo chamador — o core não conhece nenhum domínio.
"""
from contextlib import contextmanager

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from backend.core.database import _now


@contextmanager
def unique_or_409(field: str, value: str):
    """Converte violação de UNIQUE do banco em 409 com mensagem clara."""
    try:
        yield
    except IntegrityError as e:
        msg = str(e.orig)
        # "UNIQUE constraint failed" (SQLite) / "duplicate key value" (Postgres)
        if "UNIQUE" in msg or "duplicate key" in msg:
            raise HTTPException(409, f"{field} '{value}' já existe")
        raise


def _slug_ok(slug: str) -> bool:
    return bool(slug) and all(c.isalnum() or c in "-_" for c in slug) and slug == slug.lower()


def ensure_slug(slug: str) -> None:
    if not _slug_ok(slug):
        raise HTTPException(
            status_code=400,
            detail="slug deve ser minúsculo, com letras, números, '-' ou '_'",
        )


def row_or_404(session, model, row_id: int, label: str) -> dict:
    """Linha completa por id ou 404 ("<label> <id> não encontrado")."""
    row = session.execute(
        select(model.__table__).where(model.id == row_id)
    ).mappings().fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"{label} {row_id} não encontrado")
    return dict(row)


def apply_update(session, model, row_id: int, fields: dict, touch_updated: bool = False) -> None:
    """UPDATE parcial: só as colunas em `fields`. Se touch_updated, seta atualizado_em=agora."""
    values = dict(fields)
    if touch_updated:
        values["atualizado_em"] = _now()
    session.execute(update(model).where(model.id == row_id).values(**values))


def ids_por_slug_or_400(session, model, slugs: list[str], label: str) -> list[int]:
    """Resolve uma lista de slugs para ids do `model`; 400 se algum não existir."""
    if not slugs:
        return []
    rows = session.execute(
        select(model.id, model.slug).where(model.slug.in_(slugs))
    ).all()
    encontrados = {slug: id_ for id_, slug in rows}
    faltando = [s for s in slugs if s not in encontrados]
    if faltando:
        raise HTTPException(400, f"{label} slug(s) inexistente(s): {', '.join(faltando)}")
    return [encontrados[s] for s in slugs]
