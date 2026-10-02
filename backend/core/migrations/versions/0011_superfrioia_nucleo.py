"""SuperfrioIA (Lote 2): conversas, mensagens, consultas e concessões.

Quatro tabelas novas, nenhuma alteração nas existentes. Ver `backend/ia/models.py`
para o papel de cada uma.

Pontos que importam no Postgres e no SQLite:

- **`ia_mensagens.conversa_id` ON DELETE CASCADE**: apagar a conversa leva as mensagens.
- **`ia_consultas.mensagem_id` ON DELETE SET NULL**: a retenção apaga a mensagem aos 90
  dias e a consulta sobrevive até os 180 (DD-25).
- **Índices únicos parciais em `ia_concessoes`**: no máximo um pedido `pendente` e uma
  concessão `ativa` por (usuário, domínio). O banco impede o duplo clique no pedido e
  duas concessões ativas da mesma pessoa. SQLite e Postgres aceitam índice parcial.
  A corrida de dois aprovadores sobre o MESMO pedido não é coberta por índice: quem a
  fecha é o `UPDATE ... WHERE status = <esperado>` com conferência de linhas afetadas,
  em `backend/ia/permissoes.py` (quem chega depois leva 409).

Downgrade: remove as quatro tabelas (e com elas o histórico de conversas e
concessões). É o desfazer de um lote que nunca esteve ligado em produção.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-01

"""
import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ia_conversas",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("usuario_id", sa.Integer(), nullable=False),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("dominio", sa.Text(), nullable=False),
        sa.Column("titulo", sa.Text(), nullable=False),
        sa.Column("criado_em", sa.Text(), nullable=False),
        sa.Column("atualizado_em", sa.Text(), nullable=False),
        sqlite_autoincrement=True,
    )
    op.create_index("idx_ia_conversas_usuario", "ia_conversas", ["usuario_id", "atualizado_em"])

    op.create_table(
        "ia_mensagens",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "conversa_id", sa.Integer(),
            sa.ForeignKey("ia_conversas.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("papel", sa.Text(), nullable=False),
        sa.Column("texto", sa.Text(), nullable=False),
        sa.Column("blocos", sa.Text(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("meta", sa.Text(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("feedback", sa.Integer(), nullable=True),
        sa.Column("criado_em", sa.Text(), nullable=False),
        sa.CheckConstraint("papel IN ('usuario', 'ia')", name="ck_ia_mensagens_papel"),
        sqlite_autoincrement=True,
    )
    op.create_index("idx_ia_mensagens_conversa", "ia_mensagens", ["conversa_id", "id"])
    op.create_index("idx_ia_mensagens_criado_em", "ia_mensagens", ["criado_em"])

    op.create_table(
        "ia_consultas",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "mensagem_id", sa.Integer(),
            sa.ForeignKey("ia_mensagens.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("usuario_id", sa.Integer(), nullable=False),
        sa.Column("dominio", sa.Text(), nullable=False),
        sa.Column("capacidade", sa.Text(), nullable=False),
        sa.Column("parametros", sa.Text(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("escopo_aplicado", sa.Text(), nullable=False),
        sa.Column("situacao", sa.Text(), nullable=False),
        sa.Column("motivo", sa.Text(), nullable=True),
        sa.Column("linhas", sa.Integer(), nullable=True),
        sa.Column("duracao_ms", sa.Integer(), nullable=True),
        sa.Column("chamadas_logicas", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("chamadas_servico", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("paginas_lidas", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("consultas_dw", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "limite_interno_atingido", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("criado_em", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "situacao IN ('ok', 'bloqueio', 'erro')", name="ck_ia_consultas_situacao"
        ),
        sqlite_autoincrement=True,
    )
    op.create_index("idx_ia_consultas_criado_em", "ia_consultas", ["criado_em"])
    op.create_index("idx_ia_consultas_mensagem", "ia_consultas", ["mensagem_id"])

    op.create_table(
        "ia_concessoes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("usuario_id", sa.Integer(), nullable=False),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("dominio", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("motivo_pedido", sa.Text(), nullable=False),
        sa.Column("pedido_em", sa.Text(), nullable=False),
        sa.Column("decidido_por", sa.Text(), nullable=True),
        sa.Column("decidido_em", sa.Text(), nullable=True),
        sa.Column("motivo_decisao", sa.Text(), nullable=True),
        sa.Column("validade_ate", sa.Text(), nullable=True),
        sa.Column("autoaprovacao", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("revogado_por", sa.Text(), nullable=True),
        sa.Column("revogado_em", sa.Text(), nullable=True),
        sa.Column("motivo_revogacao", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('pendente', 'ativa', 'negada', 'revogada')",
            name="ck_ia_concessoes_status",
        ),
        sqlite_autoincrement=True,
    )
    op.create_index("idx_ia_concessoes_usuario", "ia_concessoes", ["usuario_id", "dominio"])
    op.create_index("idx_ia_concessoes_dominio_status", "ia_concessoes", ["dominio", "status"])
    for status in ("pendente", "ativa"):
        op.create_index(
            f"uq_ia_concessoes_{status}",
            "ia_concessoes",
            ["usuario_id", "dominio"],
            unique=True,
            sqlite_where=sa.text(f"status = '{status}'"),
            postgresql_where=sa.text(f"status = '{status}'"),
        )


def downgrade() -> None:
    for status in ("ativa", "pendente"):
        op.drop_index(f"uq_ia_concessoes_{status}", table_name="ia_concessoes")
    op.drop_index("idx_ia_concessoes_dominio_status", table_name="ia_concessoes")
    op.drop_index("idx_ia_concessoes_usuario", table_name="ia_concessoes")
    op.drop_table("ia_concessoes")

    op.drop_index("idx_ia_consultas_mensagem", table_name="ia_consultas")
    op.drop_index("idx_ia_consultas_criado_em", table_name="ia_consultas")
    op.drop_table("ia_consultas")

    op.drop_index("idx_ia_mensagens_criado_em", table_name="ia_mensagens")
    op.drop_index("idx_ia_mensagens_conversa", table_name="ia_mensagens")
    op.drop_table("ia_mensagens")

    op.drop_index("idx_ia_conversas_usuario", table_name="ia_conversas")
    op.drop_table("ia_conversas")
