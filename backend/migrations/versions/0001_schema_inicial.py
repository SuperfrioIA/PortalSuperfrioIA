"""Schema inicial do Hub — equivalente ao init_db antigo (6 tabelas + índices).

Bancos criados pelo código pré-Alembic já têm este schema e são carimbados
nesta revisão pelo init_db() (stamp), sem recriar nada.

Revision ID: 0001
Revises:
Create Date: 2026-07-02

"""
import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "usuarios",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.Text(), nullable=False, unique=True),
        sa.Column("nome", sa.Text()),
        sa.Column("email", sa.Text()),
        sa.Column("password_hash", sa.Text()),
        sa.Column("auth_source", sa.Text(), nullable=False, server_default=sa.text("'local'")),
        sa.Column("ativo", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("is_admin", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("token_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("criado_em", sa.Text(), nullable=False),
        sa.Column("atualizado_em", sa.Text()),
        sqlite_autoincrement=True,
    )

    op.create_table(
        "secoes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.Text(), nullable=False, unique=True),
        sa.Column("nome", sa.Text(), nullable=False),
        sa.Column("descricao", sa.Text()),
        sa.Column("icone", sa.Text()),
        sa.Column("ordem", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("ativo", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("nome_es", sa.Text()),
        sa.Column("descricao_es", sa.Text()),
        sqlite_autoincrement=True,
    )
    op.create_index("idx_secoes_ativo", "secoes", ["ativo"])

    op.create_table(
        "apps",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.Text(), nullable=False, unique=True),
        sa.Column("nome", sa.Text(), nullable=False),
        sa.Column("descricao", sa.Text()),
        sa.Column("icone", sa.Text()),
        sa.Column(
            "secao_id",
            sa.Integer(),
            sa.ForeignKey("secoes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("tipo_acesso", sa.Text(), nullable=False, server_default=sa.text("'url'")),
        sa.Column("badge", sa.Text()),
        sa.Column("ordem", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("ativo", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("criado_em", sa.Text(), nullable=False),
        sa.Column("atualizado_em", sa.Text()),
        sa.Column("nome_es", sa.Text()),
        sa.Column("descricao_es", sa.Text()),
        sqlite_autoincrement=True,
    )
    op.create_index("idx_apps_secao", "apps", ["secao_id"])
    op.create_index("idx_apps_ativo", "apps", ["ativo"])

    op.create_table(
        "roles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.Text(), nullable=False, unique=True),
        sa.Column("nome", sa.Text(), nullable=False),
        sa.Column("descricao", sa.Text()),
        sa.Column("ativo", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sqlite_autoincrement=True,
    )

    op.create_table(
        "role_apps",
        sa.Column(
            "role_id", sa.Integer(), sa.ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column(
            "app_id", sa.Integer(), sa.ForeignKey("apps.id", ondelete="CASCADE"), primary_key=True
        ),
    )

    op.create_table(
        "usuario_roles",
        sa.Column(
            "usuario_id",
            sa.Integer(),
            sa.ForeignKey("usuarios.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "role_id", sa.Integer(), sa.ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
        ),
    )


def downgrade() -> None:
    op.drop_table("usuario_roles")
    op.drop_table("role_apps")
    op.drop_table("roles")
    op.drop_index("idx_apps_ativo", table_name="apps")
    op.drop_index("idx_apps_secao", table_name="apps")
    op.drop_table("apps")
    op.drop_index("idx_secoes_ativo", table_name="secoes")
    op.drop_table("secoes")
    op.drop_table("usuarios")
