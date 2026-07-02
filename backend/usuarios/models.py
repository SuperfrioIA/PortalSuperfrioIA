from sqlalchemy import Column, ForeignKey, Integer, Table, Text
from sqlalchemy import text as sa_text
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base, _now


class Usuario(Base):
    __tablename__ = "usuarios"
    __table_args__ = {"sqlite_autoincrement": True}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    nome: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)
    password_hash: Mapped[str | None] = mapped_column(Text)
    auth_source: Mapped[str] = mapped_column(
        Text, nullable=False, default="local", server_default=sa_text("'local'")
    )
    ativo: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=sa_text("1"))
    is_admin: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=sa_text("0"))
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=sa_text("1"))
    criado_em: Mapped[str] = mapped_column(Text, nullable=False, default=_now)
    atualizado_em: Mapped[str | None] = mapped_column(Text)


class Role(Base):
    __tablename__ = "roles"
    __table_args__ = {"sqlite_autoincrement": True}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    nome: Mapped[str] = mapped_column(Text, nullable=False)
    descricao: Mapped[str | None] = mapped_column(Text)
    ativo: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=sa_text("1"))


# Grant role→app. A FK aponta pra tabela do Portal (`apps`), o que é permitido:
# a regra de ouro proíbe SELECT no código, não integridade referencial no banco.
role_apps = Table(
    "role_apps",
    Base.metadata,
    Column("role_id", Integer, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column("app_id", Integer, ForeignKey("apps.id", ondelete="CASCADE"), primary_key=True),
)

usuario_roles = Table(
    "usuario_roles",
    Base.metadata,
    Column("usuario_id", Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", Integer, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
)
