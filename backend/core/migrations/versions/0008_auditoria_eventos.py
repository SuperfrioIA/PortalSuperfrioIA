"""Auditoria funcional: tabela `auditoria_eventos`, append-only por trigger.

Fase 1 de docs/AUDITORIA_FUNCIONAL.md — quem fez o quê, quando, com que
resultado. Não é log técnico (isso continua sendo o stdout do container) nem
métrica operacional: é a trilha que responde "quem concedeu esta permissão" e
"quem abriu qual app".

## Por que trigger, e não só disciplina de código

`backend/auditoria/service.py` só expõe `registrar()` e `listar()` — nenhum
caminho de código faz UPDATE ou DELETE. Isso protege contra o próprio código
e contra engano, mas não contra alguém com acesso de dono ao banco. O trigger
é a segunda camada: recusa a alteração no nível do banco, com a mesma
mensagem nas duas exceções (UPDATE e DELETE), para o erro entregue ao cliente
do driver ser claro em qualquer um dos dois casos.

## Por que a checagem de dialeto, e não `render_as_batch`

`CREATE TRIGGER`/`CREATE FUNCTION` são DDL específicos de cada banco — não
tem equivalente genérico no Alembic (diferente de ADD COLUMN, que o batch
mode do SQLite sabe traduzir). Mesmo padrão de decisão das migrations 0004 e
0005: SQL na mão, escolhido por `op.get_bind().dialect.name`.

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-03

"""
import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

_TABELA = "auditoria_eventos"
_MENSAGEM = "auditoria_eventos é append-only"

# Nomes de trigger/função — usados tanto no upgrade quanto no downgrade, então
# ficam em constante para não divergir entre os dois.
_TRIGGER_SQLITE_UPDATE = "auditoria_eventos_bloquear_update"
_TRIGGER_SQLITE_DELETE = "auditoria_eventos_bloquear_delete"
_FUNCAO_PG = "auditoria_eventos_bloquear"
_TRIGGER_PG = "auditoria_eventos_imutavel"


def upgrade() -> None:
    op.create_table(
        _TABELA,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ocorrido_em", sa.Text(), nullable=False),
        sa.Column("correlacao_id", sa.Text(), nullable=True),
        sa.Column("ator_usuario_id", sa.Integer(), nullable=True),
        sa.Column("ator_username", sa.Text(), nullable=True),
        sa.Column("ator_ip", sa.Text(), nullable=True),
        sa.Column("origem", sa.Text(), nullable=False, server_default=sa.text("'hub'")),
        sa.Column("app_slug", sa.Text(), nullable=True),
        sa.Column("categoria", sa.Text(), nullable=False),
        sa.Column("acao", sa.Text(), nullable=False),
        sa.Column("alvo_tipo", sa.Text(), nullable=True),
        sa.Column("alvo_id", sa.Text(), nullable=True),
        sa.Column("alvo_rotulo", sa.Text(), nullable=True),
        sa.Column("resultado", sa.Text(), nullable=False),
        sa.Column("detalhes", sa.Text(), nullable=False, server_default=sa.text("'{}'")),
        sa.CheckConstraint(
            "resultado IN ('ok', 'negado', 'erro')", name="ck_auditoria_eventos_resultado"
        ),
        sqlite_autoincrement=True,
    )
    op.create_index("idx_auditoria_eventos_ocorrido_em", _TABELA, ["ocorrido_em"])
    op.create_index("idx_auditoria_eventos_ator", _TABELA, ["ator_usuario_id"])
    op.create_index("idx_auditoria_eventos_app", _TABELA, ["app_slug"])
    op.create_index("idx_auditoria_eventos_categoria_acao", _TABELA, ["categoria", "acao"])

    dialeto = op.get_bind().dialect.name
    if dialeto == "sqlite":
        op.execute(
            f"CREATE TRIGGER {_TRIGGER_SQLITE_UPDATE} BEFORE UPDATE ON {_TABELA} "
            f"BEGIN SELECT RAISE(ABORT, '{_MENSAGEM}'); END;"
        )
        op.execute(
            f"CREATE TRIGGER {_TRIGGER_SQLITE_DELETE} BEFORE DELETE ON {_TABELA} "
            f"BEGIN SELECT RAISE(ABORT, '{_MENSAGEM}'); END;"
        )
    elif dialeto == "postgresql":
        op.execute(
            f"CREATE FUNCTION {_FUNCAO_PG}() RETURNS trigger AS $$ "
            f"BEGIN RAISE EXCEPTION '{_MENSAGEM}'; END; $$ LANGUAGE plpgsql;"
        )
        op.execute(
            f"CREATE TRIGGER {_TRIGGER_PG} BEFORE UPDATE OR DELETE ON {_TABELA} "
            f"FOR EACH ROW EXECUTE FUNCTION {_FUNCAO_PG}();"
        )
    # Outro dialeto (ex.: `alembic --sql` sem conexão real): a tabela sobe sem
    # a trava de banco — a trava de código (`service.py` não expor UPDATE/DELETE)
    # continua valendo. Não é o caminho de produção deste projeto.


def downgrade() -> None:
    dialeto = op.get_bind().dialect.name
    if dialeto == "sqlite":
        op.execute(f"DROP TRIGGER IF EXISTS {_TRIGGER_SQLITE_UPDATE}")
        op.execute(f"DROP TRIGGER IF EXISTS {_TRIGGER_SQLITE_DELETE}")
    elif dialeto == "postgresql":
        op.execute(f"DROP TRIGGER IF EXISTS {_TRIGGER_PG} ON {_TABELA}")
        op.execute(f"DROP FUNCTION IF EXISTS {_FUNCAO_PG}()")

    op.drop_index("idx_auditoria_eventos_categoria_acao", table_name=_TABELA)
    op.drop_index("idx_auditoria_eventos_app", table_name=_TABELA)
    op.drop_index("idx_auditoria_eventos_ator", table_name=_TABELA)
    op.drop_index("idx_auditoria_eventos_ocorrido_em", table_name=_TABELA)
    op.drop_table(_TABELA)
