"""Auditoria de download da volumetria de estoque: `volumetria_estoque_downloads`.

Mesmo desenho de `0009_volumetria_transporte_downloads.py`, tabela própria.

Renumerada de `0009` para `0010` no rebase de 04/set, pela mesma razão da
irmã do transporte: encadeia depois de `0009_volumetria_transporte_downloads.py`,
que por sua vez encadeia depois de `0008_auditoria_eventos.py` (mergeada
primeiro).

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-04

"""
import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

_TABELA = "volumetria_estoque_downloads"
_INDICE = "idx_volumetria_estoque_downloads_criado_em"


def upgrade() -> None:
    op.create_table(
        _TABELA,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("criado_em", sa.Text(), nullable=False),
        sa.Column("terminado_em", sa.Text(), nullable=True),
        sa.Column("usuario", sa.Text(), nullable=False),
        sa.Column("formato", sa.Text(), nullable=False),
        sa.Column("recorte", sa.Text(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("linhas", sa.Integer(), nullable=True),
        sa.Column("ip", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'rodando'")),
        sa.Column("erro", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('rodando', 'ok', 'erro')",
            name="ck_volumetria_estoque_downloads_status",
        ),
        sa.CheckConstraint(
            "formato IN ('csv', 'xlsx')", name="ck_volumetria_estoque_downloads_formato"
        ),
        sqlite_autoincrement=True,
    )
    op.create_index(_INDICE, _TABELA, ["criado_em"])


def downgrade() -> None:
    op.drop_index(_INDICE, table_name=_TABELA)
    op.drop_table(_TABELA)
