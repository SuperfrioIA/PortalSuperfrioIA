"""Auditoria de download da volumetria de transporte — tabela própria no
banco do Hub, mesmo desenho de `backend/volumetria_catering/models.py`
(duas fases, recorte em JSON, usuário como texto sem FK — ver lá para o
porquê de cada decisão). Tabela própria, e não a `volumetria_downloads` do
catering, porque este módulo não tem T1 (a coluna `app` compartilhada é o que
o T1 traria)."""

from sqlalchemy import CheckConstraint, Index, Integer, Text
from sqlalchemy import text as sa_text
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base, _now

STATUS = ("rodando", "ok", "erro")
FORMATOS = ("csv", "xlsx")


class VolumetriaTransporteDownload(Base):
    __tablename__ = "volumetria_transporte_downloads"
    __table_args__ = (
        CheckConstraint(
            "status IN ('rodando', 'ok', 'erro')",
            name="ck_volumetria_transporte_downloads_status",
        ),
        CheckConstraint(
            "formato IN ('csv', 'xlsx')", name="ck_volumetria_transporte_downloads_formato"
        ),
        Index("idx_volumetria_transporte_downloads_criado_em", "criado_em"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    criado_em: Mapped[str] = mapped_column(Text, nullable=False, default=_now)
    terminado_em: Mapped[str | None] = mapped_column(Text)
    usuario: Mapped[str] = mapped_column(Text, nullable=False)
    formato: Mapped[str] = mapped_column(Text, nullable=False)
    recorte: Mapped[str] = mapped_column(Text, nullable=False, server_default=sa_text("'{}'"))
    linhas: Mapped[int | None] = mapped_column(Integer)
    ip: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default="rodando", server_default=sa_text("'rodando'")
    )
    erro: Mapped[str | None] = mapped_column(Text)
