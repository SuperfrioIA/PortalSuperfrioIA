from sqlalchemy import ForeignKey, Index, Integer, Text, UniqueConstraint
from sqlalchemy import text as sa_text
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base, _now


class Projeto(Base):
    __tablename__ = "projetos"
    __table_args__ = (
        Index("idx_projetos_ativo", "ativo"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    nome: Mapped[str] = mapped_column(Text, nullable=False)
    area: Mapped[str] = mapped_column(Text, nullable=False)
    objetivo: Mapped[str] = mapped_column(Text, nullable=False)
    problema: Mapped[str] = mapped_column(Text, nullable=False)
    beneficio: Mapped[str] = mapped_column(Text, nullable=False)
    publico: Mapped[str] = mapped_column(Text, nullable=False)
    acelerador: Mapped[str] = mapped_column(Text, nullable=False)
    responsavel_ti: Mapped[str | None] = mapped_column(Text)
    key_user: Mapped[str | None] = mapped_column(Text)
    # Próximo marco: texto livre + data prevista (nem toda fase futura é um marco).
    proximo_marco_texto: Mapped[str | None] = mapped_column(Text)
    proximo_marco_data: Mapped[str | None] = mapped_column(Text)
    ativo: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=sa_text("1"))
    criado_em: Mapped[str] = mapped_column(Text, nullable=False, default=_now)
    # Tocado a cada escrita relacionada (projeto, conclusão de fase, rollout) —
    # não é um campo editável pelo usuário.
    atualizado_em: Mapped[str | None] = mapped_column(Text)


class ProjetoFase(Base):
    """Uma das 7 macrofases fixas de um projeto (índice `ordem`, 0..6).

    As 7 linhas são criadas junto com o projeto (ver service.criar_projeto) —
    nunca avulsas. `previsto_fim` nulo só é esperado na última fase (7 —
    "Em suporte"), que não tem meta de encerramento.
    """
    __tablename__ = "projeto_fases"
    __table_args__ = (
        UniqueConstraint("projeto_id", "ordem", name="uq_projeto_fases_projeto_ordem"),
        Index("idx_projeto_fases_projeto", "projeto_id"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    projeto_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projetos.id", ondelete="CASCADE"), nullable=False
    )
    ordem: Mapped[int] = mapped_column(Integer, nullable=False)
    previsto_inicio: Mapped[str] = mapped_column(Text, nullable=False)
    previsto_fim: Mapped[str | None] = mapped_column(Text)
    concluido_em: Mapped[str | None] = mapped_column(Text)
    observacao: Mapped[str | None] = mapped_column(Text)
    # Nome de quem registrou a conclusão, capturado automaticamente do usuário
    # logado no momento do registro (snapshot em texto — mesmo padrão de
    # `acelerador`/`key_user`; sem FK pra não acoplar em `usuarios`).
    registrado_por: Mapped[str | None] = mapped_column(Text)


class Filial(Base):
    """Catálogo único de filiais, reaproveitado por todo projeto no rollout."""
    __tablename__ = "filiais"
    __table_args__ = (
        Index("idx_filiais_ativo", "ativo"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nome: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    uf: Mapped[str | None] = mapped_column(Text)
    regiao: Mapped[str] = mapped_column(Text, nullable=False)
    ativo: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=sa_text("1"))


class ProjetoRollout(Base):
    """Escopo de rollout de um projeto numa filial — só existe linha pra quem entrou no escopo.

    Sem coluna de status: "pendente"/"agendada"/"treinada" é derivado de
    `data` (nula / futura / passada) em `service.py`. `nao_se_aplica` é a
    única exceção manual, porque não dá pra derivar de data.
    """
    __tablename__ = "projeto_rollout"
    __table_args__ = (
        UniqueConstraint("projeto_id", "filial_id", name="uq_projeto_rollout_projeto_filial"),
        Index("idx_projeto_rollout_projeto", "projeto_id"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    projeto_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projetos.id", ondelete="CASCADE"), nullable=False
    )
    filial_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("filiais.id", ondelete="CASCADE"), nullable=False
    )
    data: Mapped[str | None] = mapped_column(Text)
    publico_treinado: Mapped[str | None] = mapped_column(Text)
    key_user_local: Mapped[str | None] = mapped_column(Text)
    nao_se_aplica: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=sa_text("0"))
