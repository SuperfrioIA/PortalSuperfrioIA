"""Auditoria de download da volumetria — a única tabela deste módulo, no banco
do Hub.

Por que tabela própria e não a `cat_auditoria` da nuvem-ia (decisão da Maria,
27/ago/2026): auditar lá exigiria INSERT para o role `hub_leitura`, e o
somente-leitura morreria na primeira exceção. Começa limpa; a `cat_auditoria`
continua valendo para a tela antiga até o H4 — não somar as duas.

O que a linha guarda, e por quê:

- **`recorte`** (JSON): o log de acesso do Hub não registra query string, de
  propósito (nunca gravar `code=` do SSO). Então é AQUI que fica "qual recorte
  saiu" — é a pergunta que uma auditoria de download responde;
- **duas fases**: a linha nasce `rodando` antes da primeira linha sair e fecha
  `ok` com a contagem real ou `erro` com a mensagem. Download interrompido no
  meio é justamente o que se quer ver — escrito só no fim, não deixaria rastro;
- **`usuario`** é o username do Hub (snapshot em texto, sem FK): a auditoria
  tem que sobreviver à exclusão do cadastro.

Timestamps em texto UTC (`_now()`), como o resto do Hub.
"""
from sqlalchemy import CheckConstraint, Index, Integer, Text
from sqlalchemy import text as sa_text
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base, _now

STATUS = ("rodando", "ok", "erro")
FORMATOS = ("csv", "xlsx")


class VolumetriaDownload(Base):
    __tablename__ = "volumetria_downloads"
    __table_args__ = (
        CheckConstraint(
            "status IN ('rodando', 'ok', 'erro')", name="ck_volumetria_downloads_status"
        ),
        CheckConstraint(
            "formato IN ('csv', 'xlsx')", name="ck_volumetria_downloads_formato"
        ),
        Index("idx_volumetria_downloads_criado_em", "criado_em"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    criado_em: Mapped[str] = mapped_column(Text, nullable=False, default=_now)
    terminado_em: Mapped[str | None] = mapped_column(Text)
    usuario: Mapped[str] = mapped_column(Text, nullable=False)
    formato: Mapped[str] = mapped_column(Text, nullable=False)
    # o recorte exato dos filtros da tela, como a consulta o recebeu (JSON)
    recorte: Mapped[str] = mapped_column(Text, nullable=False, server_default=sa_text("'{}'"))
    linhas: Mapped[int | None] = mapped_column(Integer)
    ip: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default="rodando", server_default=sa_text("'rodando'")
    )
    erro: Mapped[str | None] = mapped_column(Text)
