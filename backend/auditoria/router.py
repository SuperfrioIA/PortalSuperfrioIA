"""Leitura da trilha de auditoria — só admin.

Um papel de auditor não-admin é roadmap (seção 14 do relatório de revisão
arquitetural): criar a permissão agora, sem uso real, só inflaria a matriz de
acesso com uma linha órfã. `require_admin` basta para a Fase 1.
"""
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from backend.auditoria import service
from backend.auth.dependencies import require_admin
from backend.core.database import db

router_admin = APIRouter(prefix="/api/admin/auditoria", tags=["auditoria"])


def _filtros_nao_vazios(**kwargs) -> dict:
    return {k: v for k, v in kwargs.items() if v}


@router_admin.get("")
def listar_eventos(
    de: str | None = Query(None, description="AAAA-MM-DD"),
    ate: str | None = Query(None, description="AAAA-MM-DD"),
    ator_username: str | None = None,
    app_slug: str | None = None,
    categoria: str | None = None,
    acao: str | None = None,
    resultado: str | None = None,
    pagina: int = Query(1, ge=1),
    por_pagina: int = Query(50, ge=1, le=200),
    user: dict = Depends(require_admin),
):
    with db() as session:
        pagina_de_eventos = service.listar(
            session, de=de, ate=ate, ator_username=ator_username, app_slug=app_slug,
            categoria=categoria, acao=acao, resultado=resultado,
            pagina=pagina, por_pagina=por_pagina,
        )
        service.registrar(
            session, categoria="auditoria", acao="auditoria.consultar", resultado="ok",
            ator=user,
            detalhes=_filtros_nao_vazios(
                de=de, ate=ate, ator_username=ator_username, app_slug=app_slug,
                categoria=categoria, acao=acao, resultado=resultado,
            ),
        )
    return pagina_de_eventos


@router_admin.get("/exportar")
def exportar_eventos(
    de: str | None = Query(None, description="AAAA-MM-DD"),
    ate: str | None = Query(None, description="AAAA-MM-DD"),
    ator_username: str | None = None,
    app_slug: str | None = None,
    categoria: str | None = None,
    acao: str | None = None,
    resultado: str | None = None,
    user: dict = Depends(require_admin),
):
    filtros = dict(
        de=de, ate=ate, ator_username=ator_username, app_slug=app_slug,
        categoria=categoria, acao=acao, resultado=resultado,
    )
    service.registrar(
        categoria="auditoria", acao="auditoria.exportar", resultado="ok",
        ator=user, detalhes=_filtros_nao_vazios(**filtros),
    )
    return StreamingResponse(
        service.exportar_csv(**filtros),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="auditoria.csv"'},
    )


@router_admin.get("/catalogo")
def listar_catalogo(_: dict = Depends(require_admin)):
    """As categorias e ações válidas — alimenta os filtros da tela."""
    from backend.auditoria import catalogo

    return [{"categoria": e.categoria, "acao": e.acao, "descricao": e.descricao} for e in catalogo.listar()]
