"""Tabelas do módulo Projetos IA — projetos, fases, filiais e rollout.

Aditiva: não altera nem apaga nada das tabelas existentes. Gerada por
autogenerate e revisada manualmente — o diff bruto trazia ruído de reflection
do SQLite em tabelas antigas (FK/autoincrement de `apps`, `roles`, `secoes`
etc.), removido daqui porque não corresponde a nenhuma mudança real de schema.

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-27

"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "filiais",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("nome", sa.Text(), nullable=False),
        sa.Column("uf", sa.Text(), nullable=True),
        sa.Column("regiao", sa.Text(), nullable=False),
        sa.Column("ativo", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("nome"),
        sqlite_autoincrement=True,
    )
    op.create_index("idx_filiais_ativo", "filiais", ["ativo"])

    op.create_table(
        "projetos",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("nome", sa.Text(), nullable=False),
        sa.Column("area", sa.Text(), nullable=False),
        sa.Column("objetivo", sa.Text(), nullable=False),
        sa.Column("problema", sa.Text(), nullable=False),
        sa.Column("beneficio", sa.Text(), nullable=False),
        sa.Column("publico", sa.Text(), nullable=False),
        sa.Column("acelerador", sa.Text(), nullable=False),
        sa.Column("responsavel_ti", sa.Text(), nullable=True),
        sa.Column("key_user", sa.Text(), nullable=True),
        sa.Column("proximo_marco_texto", sa.Text(), nullable=True),
        sa.Column("proximo_marco_data", sa.Text(), nullable=True),
        sa.Column("ativo", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("criado_em", sa.Text(), nullable=False),
        sa.Column("atualizado_em", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
        sqlite_autoincrement=True,
    )
    op.create_index("idx_projetos_ativo", "projetos", ["ativo"])

    op.create_table(
        "projeto_fases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("projeto_id", sa.Integer(), nullable=False),
        sa.Column("ordem", sa.Integer(), nullable=False),
        sa.Column("previsto_inicio", sa.Text(), nullable=False),
        sa.Column("previsto_fim", sa.Text(), nullable=True),
        sa.Column("concluido_em", sa.Text(), nullable=True),
        sa.Column("observacao", sa.Text(), nullable=True),
        sa.Column("registrado_por", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["projeto_id"], ["projetos.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("projeto_id", "ordem", name="uq_projeto_fases_projeto_ordem"),
        sqlite_autoincrement=True,
    )
    op.create_index("idx_projeto_fases_projeto", "projeto_fases", ["projeto_id"])

    op.create_table(
        "projeto_rollout",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("projeto_id", sa.Integer(), nullable=False),
        sa.Column("filial_id", sa.Integer(), nullable=False),
        sa.Column("data", sa.Text(), nullable=True),
        sa.Column("publico_treinado", sa.Text(), nullable=True),
        sa.Column("key_user_local", sa.Text(), nullable=True),
        sa.Column("nao_se_aplica", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.ForeignKeyConstraint(["projeto_id"], ["projetos.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["filial_id"], ["filiais.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("projeto_id", "filial_id", name="uq_projeto_rollout_projeto_filial"),
        sqlite_autoincrement=True,
    )
    op.create_index("idx_projeto_rollout_projeto", "projeto_rollout", ["projeto_id"])


def downgrade() -> None:
    op.drop_table("projeto_rollout")
    op.drop_table("projeto_fases")
    op.drop_table("projetos")
    op.drop_table("filiais")
