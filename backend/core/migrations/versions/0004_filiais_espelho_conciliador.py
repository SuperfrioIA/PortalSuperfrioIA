"""Filiais espelhando o cadastro do Conciliador de Estoque + unidades de negócio (B.U).

`filiais` ganha as colunas que o Conciliador tem em `warehouses` (codigo, cidade,
responsavel, unidade de negócio) e **perde o UNIQUE(nome)**: a chave de negócio
passa a ser `codigo`, como lá. Sem isso a carga das 59 filiais de produção não
entra — cinco nomes (BAIXADA, CCV, ITA, MAQ, MGG) aparecem em duas filiais cada.

Duas coisas para quem for reverter ou reaplicar isto:

1. O `UNIQUE(nome)` foi criado sem nome em 0003, então cada banco o nomeia à sua
   maneira: em SQLite ele é anônimo (só existe como índice interno) e o batch
   mode precisa de `naming_convention` para conseguir referenciá-lo; em Postgres
   ele virou `filiais_nome_key` — mas em vez de confiar nesse nome, buscamos o
   real no catálogo (`pg_constraint`), que é à prova de banco criado por outro
   caminho.
2. O `downgrade` recria o `UNIQUE(nome)`, o que é impossível depois do seed das
   59 (cinco nomes repetidos). Ele **aborta na primeira linha**, antes de
   qualquer DDL: se deixasse o batch mode do SQLite tentar, a reversão morria no
   meio — índice já derrubado, `_alembic_tmp_filiais` órfã e a versão ainda em
   0004. Para reverter de verdade, apague ou renomeie as duplicadas antes.

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-27

"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

# Dá nome ao UNIQUE anônimo de `filiais.nome` quando o batch mode do SQLite
# reflete a tabela para recriá-la. O batch mode recusa recriar constraint sem
# nome ("Constraint must have a name"), daí a convenção cobrir `fk` também.
NAMING = {
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s",
}


def _pg_constraint_unique_nome(bind) -> str | None:
    """Nome real do UNIQUE(nome) de `filiais` no Postgres, direto do catálogo."""
    return bind.execute(
        sa.text(
            """
            SELECT c.conname
              FROM pg_constraint c
              JOIN pg_class t ON t.oid = c.conrelid
             WHERE t.relname = 'filiais'
               AND c.contype = 'u'
               AND pg_get_constraintdef(c.oid) = 'UNIQUE (nome)'
            """
        )
    ).scalar()


def upgrade() -> None:
    bind = op.get_bind()
    postgres = bind.dialect.name == "postgresql"

    op.create_table(
        "unidades_negocio",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("nome", sa.Text(), nullable=False),
        sa.Column("responsavel", sa.Text(), nullable=True),
        sa.Column("ativo", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("nome", name="uq_unidades_negocio_nome"),
        sqlite_autoincrement=True,
    )
    op.create_index("idx_unidades_negocio_ativo", "unidades_negocio", ["ativo"])

    with op.batch_alter_table("filiais", naming_convention=NAMING) as batch:
        batch.add_column(sa.Column("codigo", sa.Text(), nullable=True))
        batch.add_column(sa.Column("cidade", sa.Text(), nullable=True))
        batch.add_column(sa.Column("responsavel", sa.Text(), nullable=True))
        batch.add_column(
            sa.Column(
                "unidade_negocio_id",
                sa.Integer(),
                sa.ForeignKey(
                    "unidades_negocio.id",
                    ondelete="SET NULL",
                    name="fk_filiais_unidade_negocio_id",
                ),
                nullable=True,
            )
        )
        if not postgres:
            batch.drop_constraint("uq_filiais_nome", type_="unique")

    if postgres:
        if op.get_context().as_sql:
            # `alembic --sql` não tem conexão para consultar o catálogo: usa o
            # nome que o Postgres gera por convenção (<tabela>_<coluna>_key).
            op.drop_constraint("filiais_nome_key", "filiais", type_="unique")
        else:
            conname = _pg_constraint_unique_nome(bind)
            if conname:
                op.drop_constraint(conname, "filiais", type_="unique")

    # Índice em vez de UniqueConstraint: funciona igual nos dois bancos sem
    # depender de batch mode, e ambos permitem vários NULL num índice único
    # (as filiais cadastradas à mão, sem código, continuam válidas).
    op.create_index("uq_filiais_codigo", "filiais", ["codigo"], unique=True)


def downgrade() -> None:
    # Checagem primeiro: o UNIQUE(nome) só volta se os nomes forem únicos, e uma
    # falha no meio do batch mode deixa o banco quebrado (ver cabeçalho).
    # Em `--sql` não há como consultar — quem aplicar o script responde por isso.
    repetidos = (
        []
        if op.get_context().as_sql
        else [
            nome
            for (nome,) in op.get_bind().execute(
                sa.text("SELECT nome FROM filiais GROUP BY nome HAVING COUNT(*) > 1")
            )
        ]
    )
    if repetidos:
        raise RuntimeError(
            "downgrade da 0004 precisa de nome único em `filiais`. Repetidos: "
            + ", ".join(sorted(repetidos))
            + ". Apague ou renomeie as filiais duplicadas antes de reverter."
        )

    op.drop_index("uq_filiais_codigo", table_name="filiais")

    # Vale para os dois bancos: em Postgres o batch mode só emite os ALTER TABLE
    # direto; em SQLite recria a tabela sem as colunas e com o UNIQUE de volta.
    with op.batch_alter_table("filiais", naming_convention=NAMING) as batch:
        batch.drop_column("unidade_negocio_id")
        batch.drop_column("responsavel")
        batch.drop_column("cidade")
        batch.drop_column("codigo")
        # Falha aqui se existirem nomes repetidos — ver o cabeçalho do arquivo.
        batch.create_unique_constraint("uq_filiais_nome", ["nome"])

    op.drop_index("idx_unidades_negocio_ativo", table_name="unidades_negocio")
    op.drop_table("unidades_negocio")
