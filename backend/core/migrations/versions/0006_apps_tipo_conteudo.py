"""Apps ganham `tipo_conteudo`: separa INDICADOR de SISTEMA no catálogo.

O menu do portal passou a ter dois grupos — Indicadores e Sistemas — e essa
diferença não existia em lugar nenhum do modelo: `tipo_acesso` só diz COMO o app
abre (nova aba, iframe, tela nativa), nunca O QUE ele é. Sem a coluna, a regra
teria que morar numa lista de slugs dentro do JS e quebrar a cada app novo.

Aditiva e com default: todo app existente vira 'sistema', que é o caso da grande
maioria e mantém a home igual ao que era para quem não mexer em nada.

O passo de dados marca como indicador os dois painéis que já nascem indicador
(`processos-abertos` e `integracao-in-out`). São slugs estáveis, criados pelo
seed do repositório — não é chute sobre o estado de produção. Qualquer outro app
(Volumetria, Ocupação, o que vier) é classificado no cadastro, em
Administração › Apps, sem precisar de migration.

NOT NULL com server_default funciona direto no SQLite (ADD COLUMN aceita default
constante), então não precisa de batch mode aqui — nada de recriar a tabela
`apps`, que é referenciada por `role_apps`.

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-25

"""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "apps",
        sa.Column(
            "tipo_conteudo",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'sistema'"),
        ),
    )
    op.execute(
        "UPDATE apps SET tipo_conteudo = 'indicador' "
        "WHERE slug IN ('processos-abertos', 'integracao-in-out')"
    )


def downgrade() -> None:
    op.drop_column("apps", "tipo_conteudo")
