"""Interface do módulo Usuários para os demais módulos.

Auth autentica por aqui; Portal descobre por aqui quais apps o usuário pode ver;
qualquer módulo pergunta por aqui se o usuário tem uma permissão de ação.
Todas as funções recebem a Session do chamador (mesma transação).

Modelo de permissão (detalhes em `backend/core/permissoes.py`): a matriz é
app × ação. A coluna `ver` mora em `role_apps`; as demais ações moram em
`role_permissoes`. Nos dois casos, **role inativa não concede nada**.
"""
from sqlalchemy import select

from backend.core.permissoes import ACAO_VER, listar as listar_catalogo
from backend.portal import service as portal_service
from backend.usuarios.models import Role, Usuario, role_apps, role_permissoes, usuario_roles


def por_username(session, username: str, apenas_ativos: bool = True) -> dict | None:
    """Linha completa do usuário (inclui password_hash/token_version — uso interno
    dos módulos; routers nunca devolvem isso pro cliente)."""
    stmt = select(Usuario.__table__).where(Usuario.username == username)
    if apenas_ativos:
        stmt = stmt.where(Usuario.ativo == 1)
    row = session.execute(stmt).mappings().fetchone()
    return dict(row) if row else None


def app_ids_permitidos(session, usuario_id: int) -> list[int]:
    """Ids de apps que as roles **ativas** do usuário liberam (a coluna `ver`).

    Não filtra `apps.ativo` — quem decide o que exibir é o dono do catálogo, o
    Portal. Filtra `roles.ativo` sim: desativar uma role tem que cortar o acesso,
    igual já acontecia com as permissões de ação.
    """
    rows = session.execute(
        select(role_apps.c.app_id)
        .distinct()
        .join_from(role_apps, usuario_roles, usuario_roles.c.role_id == role_apps.c.role_id)
        .join(Role, Role.id == role_apps.c.role_id)
        .where(usuario_roles.c.usuario_id == usuario_id, Role.ativo == 1)
    ).scalars()
    return list(rows)


def _acoes_concedidas(session, usuario_id: int) -> list[str]:
    """Slugs de `role_permissoes` vindos das roles ativas do usuário."""
    rows = session.execute(
        select(role_permissoes.c.permissao_slug)
        .distinct()
        .join_from(
            role_permissoes, usuario_roles, usuario_roles.c.role_id == role_permissoes.c.role_id
        )
        .join(Role, Role.id == role_permissoes.c.role_id)
        .where(usuario_roles.c.usuario_id == usuario_id, Role.ativo == 1)
    ).scalars()
    return list(rows)


def permissoes_do_usuario(session, usuario_id: int) -> set[str]:
    """Todas as permissões efetivas, no formato `<app>:<acao>`.

    Junta as duas metades da matriz: `<app>:ver` derivado de `role_apps` e as
    ações vindas de `role_permissoes`. **Não** aplica o bypass de admin — quem faz
    isso é `require_permissao`, num lugar só.
    """
    app_ids = app_ids_permitidos(session, usuario_id)
    slugs = portal_service.slugs_por_app_ids(session, app_ids)
    permissoes = {f"{slug}:{ACAO_VER}" for slug in slugs.values()}
    permissoes.update(_acoes_concedidas(session, usuario_id))
    return permissoes


def tem_permissao(session, usuario_id: int, permissao_slug: str) -> bool:
    """O usuário tem esta permissão por alguma role ativa? (sem bypass de admin)"""
    return permissao_slug in permissoes_do_usuario(session, usuario_id)


def todas_permissoes(session) -> set[str]:
    """Tudo que existe hoje — usado para responder o acesso de um admin.

    É o catálogo em código (ações) mais um `<app>:ver` por app ativo, para que o
    frontend possa checar `permissoes.includes(...)` sem tratar admin à parte.
    """
    apps = portal_service.apps_ativos_com_secao(session)
    tudo = {f"{a['slug']}:{ACAO_VER}" for a in apps}
    tudo.update(p.slug for p in listar_catalogo())
    return tudo
