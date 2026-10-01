"""Interface do módulo Portal para os demais módulos.

Quem precisa de dados de apps/seções chama estas funções — nunca as tabelas.
Todas recebem a Session do chamador (mesma transação).
"""
from typing import Callable

from sqlalchemy import select

from backend.core.http import ids_por_slug_or_400
from backend.portal.models import App, Secao

# Apps cuja existência na tela depende de uma chave de funcionalidade (feature
# flag) lida a cada chamada. O portal não conhece o módulo dono da chave: quem
# a controla se registra aqui (hoje, `backend/ia`). Registrado, o app só aparece
# em `home`, `sistemas` e `abrir` enquanto a função devolver True — mesmo que o
# registro dele exista no banco com `ativo = 1` (DD-27).
_CHAVES_DE_APP: dict[str, Callable[[], bool]] = {}


def registrar_chave_de_app(slug: str, ligada: Callable[[], bool]) -> None:
    """Declara que o app `slug` só é liberado enquanto `ligada()` for True."""
    _CHAVES_DE_APP[slug] = ligada


def app_liberado(slug: str) -> bool:
    """False só quando o app tem chave registrada e ela está desligada."""
    ligada = _CHAVES_DE_APP.get(slug)
    return True if ligada is None else bool(ligada())


def apps_ativos_com_secao(
    session, app_ids: list[int] | None = None, *, apenas_liberados: bool = False
) -> list[dict]:
    """Apps ativos (de seções ativas) com os dados da seção embutidos.

    `app_ids=None` → todos (admin); lista → só esses (permissão do usuário).

    `apenas_liberados=True` tira o app cuja chave de funcionalidade está desligada
    (ver `_CHAVES_DE_APP`). É **opt-in de propósito**, e só as portas de entrada
    (`home` e `sistemas`) o usam. A matriz de acesso e a lista de permissões do
    admin NÃO podem esconder o app: com ele fora da grade, salvar uma role
    reinseria `role_apps` só com as células visíveis e revogaria o `ver` dele em
    silêncio, justamente na hora de desligar a chave numa emergência.
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
    return [dict(r) for r in rows if not apenas_liberados or app_liberado(r["slug"])]


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
