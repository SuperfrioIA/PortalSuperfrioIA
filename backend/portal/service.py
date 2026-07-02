"""Interface do módulo Portal para os demais módulos.

Quem precisa de dados de apps/seções chama estas funções — nunca as tabelas.
Todas recebem a Session do chamador (mesma transação).
"""
from sqlalchemy import select

from backend.core.http import ids_por_slug_or_400
from backend.portal.models import App, Secao


def apps_ativos_com_secao(session, app_ids: list[int] | None = None) -> list[dict]:
    """Apps ativos (de seções ativas) com os dados da seção embutidos.

    `app_ids=None` → todos (admin); lista → só esses (permissão do usuário).
    """
    stmt = (
        select(
            *App.__table__.c,
            Secao.slug.label("secao_slug"),
            Secao.nome.label("secao_nome"),
            Secao.nome_es.label("secao_nome_es"),
            Secao.icone.label("secao_icone"),
            Secao.ordem.label("secao_ordem"),
        )
        .join_from(App, Secao, Secao.id == App.secao_id)
        .where(App.ativo == 1, Secao.ativo == 1)
        .order_by(Secao.ordem, App.ordem, App.nome)
    )
    if app_ids is not None:
        stmt = stmt.where(App.id.in_(app_ids))
    rows = session.execute(stmt).mappings().fetchall()
    return [dict(r) for r in rows]


def app_ids_por_slug(session, slugs: list[str]) -> list[int]:
    """Resolve slugs de apps para ids; 400 se algum não existir."""
    return ids_por_slug_or_400(session, App, slugs, "app")


def slugs_por_app_ids(session, app_ids: list[int]) -> dict[int, str]:
    """Mapa id → slug dos apps informados."""
    if not app_ids:
        return {}
    rows = session.execute(
        select(App.id, App.slug).where(App.id.in_(app_ids))
    ).all()
    return {id_: slug for id_, slug in rows}
