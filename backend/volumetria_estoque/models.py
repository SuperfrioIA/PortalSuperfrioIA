"""Auditoria de download da volumetria de estoque — tabela própria no banco
do Hub. Mesmo desenho de `backend/volumetria_catering/models.py`, ver lá para
o porquê de cada decisão."""

from sqlalchemy import CheckConstraint, Index, Integer, Text
from sqlalchemy import text as sa_text
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base, _now

STATUS = ("rodando", "ok", "erro")
FORMATOS = ("csv", "xlsx")


class VolumetriaEstoqueDownload(Base):
    __tablename__ = "volumetria_estoque_downloads"
    __table_args__ = (
        CheckConstraint(
            "status IN ('rodando', 'ok', 'erro')",
            name="ck_volumetria_estoque_downloads_status",
        ),
        CheckConstraint(
            "formato IN ('csv', 'xlsx')", name="ck_volumetria_estoque_downloads_formato"
        ),
        Index("idx_volumetria_estoque_downloads_criado_em", "criado_em"),
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
