"""Interface do módulo Usuários para os demais módulos.

Auth autentica por aqui; Portal descobre por aqui quais apps o usuário pode
ver. Todas as funções recebem a Session do chamador (mesma transação).
"""
from sqlalchemy import select

from backend.usuarios.models import Usuario, role_apps, usuario_roles


def por_username(session, username: str, apenas_ativos: bool = True) -> dict | None:
    """Linha completa do usuário (inclui password_hash/token_version — uso interno
    dos módulos; routers nunca devolvem isso pro cliente)."""
    stmt = select(Usuario.__table__).where(Usuario.username == username)
    if apenas_ativos:
        stmt = stmt.where(Usuario.ativo == 1)
    row = session.execute(stmt).mappings().fetchone()
    return dict(row) if row else None


def app_ids_permitidos(session, usuario_id: int) -> list[int]:
    """Ids de apps que as roles do usuário liberam (sem filtrar ativo — quem
    decide o que exibir é o dono do catálogo, o Portal)."""
    rows = session.execute(
        select(role_apps.c.app_id)
        .distinct()
        .join_from(role_apps, usuario_roles, usuario_roles.c.role_id == role_apps.c.role_id)
        .where(usuario_roles.c.usuario_id == usuario_id)
    ).scalars()
    return list(rows)
