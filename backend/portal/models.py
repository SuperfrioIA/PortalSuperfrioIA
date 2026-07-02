from sqlalchemy import ForeignKey, Index, Integer, Text
from sqlalchemy import text as sa_text
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base, _now


class Secao(Base):
    __tablename__ = "secoes"
    __table_args__ = (
        Index("idx_secoes_ativo", "ativo"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    nome: Mapped[str] = mapped_column(Text, nullable=False)
    descricao: Mapped[str | None] = mapped_column(Text)
    icone: Mapped[str | None] = mapped_column(Text)
    ordem: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=sa_text("0"))
    ativo: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=sa_text("1"))
    nome_es: Mapped[str | None] = mapped_column(Text)
    descricao_es: Mapped[str | None] = mapped_column(Text)


class App(Base):
    __tablename__ = "apps"
    __table_args__ = (
        Index("idx_apps_secao", "secao_id"),
        Index("idx_apps_ativo", "ativo"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    nome: Mapped[str] = mapped_column(Text, nullable=False)
    descricao: Mapped[str | None] = mapped_column(Text)
    icone: Mapped[str | None] = mapped_column(Text)
    secao_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("secoes.id", ondelete="CASCADE"), nullable=False
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    tipo_acesso: Mapped[str] = mapped_column(
        Text, nullable=False, default="url", server_default=sa_text("'url'")
    )
    badge: Mapped[str | None] = mapped_column(Text)
    ordem: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=sa_text("0"))
    ativo: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=sa_text("1"))
    criado_em: Mapped[str] = mapped_column(Text, nullable=False, default=_now)
    atualizado_em: Mapped[str | None] = mapped_column(Text)
    nome_es: Mapped[str | None] = mapped_column(Text)
    descricao_es: Mapped[str | None] = mapped_column(Text)
