"""Auditoria de download da volumetria de transporte: `volumetria_transporte_downloads`.

Mesmo desenho de `0007_volumetria_downloads.py` (ver lá para o porquê de cada
coluna), tabela própria — este módulo não tem a coluna `app` compartilhada que
o T1 (base comum, ainda não feito) traria.

Renumerada de `0008` para `0009` no rebase de 04/set: a branch
`feat/auditoria-nucleo` mergeou primeiro e tomou o `0008` de verdade
(`0008_auditoria_eventos.py`) — esta encadeia depois dela.

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-04

"""
import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

_TABELA = "volumetria_transporte_downloads"
_INDICE = "idx_volumetria_transporte_downloads_criado_em"


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
            name="ck_volumetria_transporte_downloads_status",
        ),
        sa.CheckConstraint(
            "formato IN ('csv', 'xlsx')", name="ck_volumetria_transporte_downloads_formato"
        ),
        sqlite_autoincrement=True,
    )
    op.create_index(_INDICE, _TABELA, ["criado_em"])


def downgrade() -> None:
    op.drop_index(_INDICE, table_name=_TABELA)
    op.drop_table(_TABELA)
