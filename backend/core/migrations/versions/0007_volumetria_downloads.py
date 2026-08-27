"""Auditoria de download da volumetria de catering: `volumetria_downloads`.

Tabela própria do Hub, e não a `cat_auditoria` da nuvem-ia — decisão da Maria
em 27/ago/2026 (docs/PLANO_VOLUMETRIA_CATERING.md, mecânica 4). O módulo
`backend/volumetria_catering/` lê o banco da nuvem-ia com um role só de SELECT;
auditar lá exigiria INSERT e o somente-leitura morreria na primeira exceção.

O que a linha guarda: quem (username do Hub, snapshot em texto, sem FK — a
auditoria sobrevive à exclusão do cadastro), quando, em qual formato, **qual
recorte** (JSON — o log de acesso do Hub não grava query string, de propósito),
quantas linhas realmente saíram e o status. A linha nasce `rodando` antes da
primeira linha do arquivo sair e fecha `ok`/`erro` — download interrompido no
meio é justamente o que se quer ver.

Começa limpa: a `cat_auditoria` da V3 continua valendo para a tela antiga até o
H4. Não somar as duas ao ler números de uso.

Um índice, em `criado_em`: a pergunta que esta tabela responde é "quem baixou
o que em tal período".

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-27

"""
import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

_TABELA = "volumetria_downloads"
_INDICE = "idx_volumetria_downloads_criado_em"


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
            "status IN ('rodando', 'ok', 'erro')", name="ck_volumetria_downloads_status"
        ),
        sa.CheckConstraint(
            "formato IN ('csv', 'xlsx')", name="ck_volumetria_downloads_formato"
        ),
        sqlite_autoincrement=True,
    )
    op.create_index(_INDICE, _TABELA, ["criado_em"])


def downgrade() -> None:
    op.drop_index(_INDICE, table_name=_TABELA)
    op.drop_table(_TABELA)
