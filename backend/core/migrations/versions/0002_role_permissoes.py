"""Tabela role_permissoes — grant de ações (editar/exportar/administrar) por role.

A coluna `ver` da matriz de acesso continua em `role_apps`; esta tabela guarda só
as demais ações. Ver `backend/core/permissoes.py`.

Aditiva e reversível: não altera, move nem apaga nada das tabelas existentes.

Inclui um backfill: ambientes que criaram a role `processos-abertos-editor` na mão
(o mecanismo antigo, em que o *slug da role* era a permissão) recebem o grant
equivalente, para que ninguém perca acesso na virada.

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-26

"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

# Role criada à mão no mecanismo antigo -> permissão equivalente no novo.
_BACKFILL = {"processos-abertos-editor": "processos-abertos:editar"}


def upgrade() -> None:
    op.create_table(
        "role_permissoes",
        sa.Column(
            "role_id", sa.Integer(), sa.ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("permissao_slug", sa.Text(), primary_key=True),
    )

    conn = op.get_bind()
    roles = sa.table(
        "roles", sa.column("id", sa.Integer), sa.column("slug", sa.Text)
    )
    grants = sa.table(
        "role_permissoes", sa.column("role_id", sa.Integer), sa.column("permissao_slug", sa.Text)
    )
    for role_slug, permissao in _BACKFILL.items():
        role_id = conn.execute(
            sa.select(roles.c.id).where(roles.c.slug == role_slug)
        ).scalar_one_or_none()
        if role_id is not None:
            conn.execute(
                sa.insert(grants).values(role_id=role_id, permissao_slug=permissao)
            )


def downgrade() -> None:
    op.drop_table("role_permissoes")
