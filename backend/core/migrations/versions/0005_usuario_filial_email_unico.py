"""Usuário ganha filial e o e-mail passa a ser único (case-insensitive).

Duas mudanças, as duas aditivas:

1. `usuarios.filial_id` — nullable, FK para `filiais` com ON DELETE SET NULL.
   Nullable porque os usuários que já existem não têm filial e ninguém pode
   perder acesso na virada; a obrigatoriedade vive no cadastro (API/tela), não
   no schema.

2. índice único em `lower(email)` — com o login por Microsoft Entra, o e-mail
   é a chave que casa a pessoa com o claim do token (`backend/auth/provisioning.py`).
   Dois cadastros com o mesmo e-mail deixariam o login SSO escolher um deles de
   forma arbitrária. `lower()` porque o Entra não garante caixa e a busca já era
   case-insensitive. E-mail nulo continua permitido e não conflita (NULL nunca
   colide em índice único), o que preserva os usuários locais sem e-mail.

Conferido antes de escrever esta migration: nenhum e-mail repetido em produção
(`select lower(email), count(*) ... group by 1 having count(*) > 1` voltou vazio
em 21/08/2026). Se algum ambiente tiver duplicata, o upgrade falha aqui — de
propósito, porque escolher qual cadastro sobrevive é decisão de quem administra,
não da migration.

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-21

"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

_INDICE_EMAIL = "uq_usuarios_email_lower"


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        # No SQLite o Alembic recusa ALTER de constraint (NotImplementedError) e
        # manda usar batch mode — que recriaria `usuarios` inteira. Duas razões
        # para não fazer isso aqui: o UNIQUE de `username` é anônimo e o batch
        # exigiria naming_convention (a armadilha documentada na migration 0004),
        # e recriar tabela referenciada por `usuario_roles` com
        # `PRAGMA foreign_keys = ON` é justamente o cenário que o próprio Alembic
        # avisa que pode deixar as filhas apontando para a tabela temporária.
        #
        # DDL na mão resolve sem recriar nada: o SQLite aceita ADD COLUMN com
        # REFERENCES desde que o default seja NULL, que é o caso. Assim dev/teste
        # ficam com a MESMA constraint de produção — o `PRAGMA foreign_keys = ON`
        # de backend/core/database.py faz o SQLite realmente aplicá-la.
        op.execute(
            "ALTER TABLE usuarios ADD COLUMN filial_id INTEGER "
            "REFERENCES filiais (id) ON DELETE SET NULL"
        )
    else:
        op.add_column(
            "usuarios",
            sa.Column(
                "filial_id",
                sa.Integer(),
                sa.ForeignKey("filiais.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
    op.create_index(
        _INDICE_EMAIL, "usuarios", [sa.text("lower(email)")], unique=True
    )


def downgrade() -> None:
    op.drop_index(_INDICE_EMAIL, table_name="usuarios")
    op.drop_column("usuarios", "filial_id")
