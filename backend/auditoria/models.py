from sqlalchemy import CheckConstraint, Index, Integer, Text
from sqlalchemy import text as sa_text
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base, _now


class AuditoriaEvento(Base):
    __tablename__ = "auditoria_eventos"
    __table_args__ = (
        CheckConstraint("resultado IN ('ok', 'negado', 'erro')", name="ck_auditoria_eventos_resultado"),
        Index("idx_auditoria_eventos_ocorrido_em", "ocorrido_em"),
        Index("idx_auditoria_eventos_ator", "ator_usuario_id"),
        Index("idx_auditoria_eventos_app", "app_slug"),
        Index("idx_auditoria_eventos_categoria_acao", "categoria", "acao"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ocorrido_em: Mapped[str] = mapped_column(Text, nullable=False, default=_now)
    correlacao_id: Mapped[str | None] = mapped_column(Text)
    # Snapshot do ator, sem FK: a trilha sobrevive à exclusão do cadastro
    # (mesma decisão de `volumetria_catering/models.py`).
    ator_usuario_id: Mapped[int | None] = mapped_column(Integer)
    ator_username: Mapped[str | None] = mapped_column(Text)
    ator_ip: Mapped[str | None] = mapped_column(Text)
    origem: Mapped[str] = mapped_column(Text, nullable=False, default="hub", server_default=sa_text("'hub'"))
    app_slug: Mapped[str | None] = mapped_column(Text)
    categoria: Mapped[str] = mapped_column(Text, nullable=False)
    acao: Mapped[str] = mapped_column(Text, nullable=False)
    alvo_tipo: Mapped[str | None] = mapped_column(Text)
    alvo_id: Mapped[str | None] = mapped_column(Text)
    alvo_rotulo: Mapped[str | None] = mapped_column(Text)
    resultado: Mapped[str] = mapped_column(Text, nullable=False)
    # JSON como texto — diff da mutação, motivo da recusa, ou filtros de uma
    # exportação. Nunca senha, hash, token, code ou state (ver `_sanear`).
    detalhes: Mapped[str] = mapped_column(Text, nullable=False, default="{}", server_default=sa_text("'{}'"))
