"""Tabelas do SuperfrioIA no banco do Hub (migration `0011`).

Quatro tabelas, com papéis diferentes (arquitetura §16):

- **`ia_conversas` / `ia_mensagens`**: o **conteúdo** que o usuário vê. A única cópia
  em repouso do que foi exibido (`blocos`: tiles, série, tabela) mora em
  `ia_mensagens`. O texto da pergunta já está **mascarado** (CPF, CNPJ, e-mail,
  telefone). Retenção de 90 dias (DD-25).
- **`ia_consultas`**: o **fato** de cada consulta ao indicador — parâmetros (rótulos,
  nunca a chave do cliente), escopo aplicado, quanto trabalho foi feito de fato.
  **Sem linhas de dado.** Retenção de 180 dias (DD-25).
- **`ia_concessoes`**: pedido e concessão de uso de um domínio, uma tabela com
  `status` (pendente, ativa, negada, revogada). "Vencida" não é status: é
  `validade_ate` no passado, calculado na leitura.

Timestamps em texto UTC (`_now()`), como o resto do Hub. `usuario_id` é um
snapshot sem FK: a trilha tem que sobreviver à exclusão do cadastro.

`ia_consultas.mensagem_id` é `ON DELETE SET NULL`, de propósito: a mensagem some aos
90 dias e a consulta fica até os 180. Com `CASCADE` a retenção de 180 dias seria
mentira; com `RESTRICT` a exclusão das mensagens falharia.
"""
from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Text
from sqlalchemy import text as sa_text
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base, _now

STATUS_CONCESSAO = ("pendente", "ativa", "negada", "revogada")
PAPEIS = ("usuario", "ia")
SITUACOES = ("ok", "bloqueio", "erro")


class IaConversa(Base):
    __tablename__ = "ia_conversas"
    __table_args__ = (
        Index("idx_ia_conversas_usuario", "usuario_id", "atualizado_em"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    usuario_id: Mapped[int] = mapped_column(Integer, nullable=False)
    username: Mapped[str] = mapped_column(Text, nullable=False)
    dominio: Mapped[str] = mapped_column(Text, nullable=False)
    titulo: Mapped[str] = mapped_column(Text, nullable=False)
    criado_em: Mapped[str] = mapped_column(Text, nullable=False, default=_now)
    atualizado_em: Mapped[str] = mapped_column(Text, nullable=False, default=_now)


class IaMensagem(Base):
    __tablename__ = "ia_mensagens"
    __table_args__ = (
        CheckConstraint("papel IN ('usuario', 'ia')", name="ck_ia_mensagens_papel"),
        Index("idx_ia_mensagens_conversa", "conversa_id", "id"),
        Index("idx_ia_mensagens_criado_em", "criado_em"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversa_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("ia_conversas.id", ondelete="CASCADE"), nullable=False
    )
    papel: Mapped[str] = mapped_column(Text, nullable=False)
    texto: Mapped[str] = mapped_column(Text, nullable=False)
    # o que foi exibido (JSON): tiles, gráfico, tabela, fonte, avisos
    blocos: Mapped[str] = mapped_column(Text, nullable=False, server_default=sa_text("'[]'"))
    # provedor, duração, aviso de dado pessoal mascarado... (JSON)
    meta: Mapped[str] = mapped_column(Text, nullable=False, server_default=sa_text("'{}'"))
    feedback: Mapped[int | None] = mapped_column(Integer)  # 1 ajudou, -1 não ajudou
    criado_em: Mapped[str] = mapped_column(Text, nullable=False, default=_now)


class IaConsulta(Base):
    __tablename__ = "ia_consultas"
    __table_args__ = (
        CheckConstraint("situacao IN ('ok', 'bloqueio', 'erro')", name="ck_ia_consultas_situacao"),
        Index("idx_ia_consultas_criado_em", "criado_em"),
        Index("idx_ia_consultas_mensagem", "mensagem_id"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mensagem_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("ia_mensagens.id", ondelete="SET NULL")
    )
    usuario_id: Mapped[int] = mapped_column(Integer, nullable=False)
    dominio: Mapped[str] = mapped_column(Text, nullable=False)
    capacidade: Mapped[str] = mapped_column(Text, nullable=False)
    # parâmetros como o Hub os resolveu, em RÓTULOS (nunca a chave do cliente)
    parametros: Mapped[str] = mapped_column(Text, nullable=False, server_default=sa_text("'{}'"))
    escopo_aplicado: Mapped[str] = mapped_column(Text, nullable=False)
    situacao: Mapped[str] = mapped_column(Text, nullable=False)
    motivo: Mapped[str | None] = mapped_column(Text)
    linhas: Mapped[int | None] = mapped_column(Integer)
    duracao_ms: Mapped[int | None] = mapped_column(Integer)
    # DD-24: o que contou no teto (chamadas lógicas) e o que foi feito de fato
    chamadas_logicas: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    chamadas_servico: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    paginas_lidas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    consultas_dw: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    limite_interno_atingido: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    criado_em: Mapped[str] = mapped_column(Text, nullable=False, default=_now)


class IaConcessao(Base):
    __tablename__ = "ia_concessoes"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pendente', 'ativa', 'negada', 'revogada')",
            name="ck_ia_concessoes_status",
        ),
        Index("idx_ia_concessoes_usuario", "usuario_id", "dominio"),
        Index("idx_ia_concessoes_dominio_status", "dominio", "status"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    usuario_id: Mapped[int] = mapped_column(Integer, nullable=False)
    username: Mapped[str] = mapped_column(Text, nullable=False)
    dominio: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    motivo_pedido: Mapped[str] = mapped_column(Text, nullable=False)
    pedido_em: Mapped[str] = mapped_column(Text, nullable=False, default=_now)
    decidido_por: Mapped[str | None] = mapped_column(Text)
    decidido_em: Mapped[str | None] = mapped_column(Text)
    motivo_decisao: Mapped[str | None] = mapped_column(Text)
    validade_ate: Mapped[str | None] = mapped_column(Text)
    autoaprovacao: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    revogado_por: Mapped[str | None] = mapped_column(Text)
    revogado_em: Mapped[str | None] = mapped_column(Text)
    motivo_revogacao: Mapped[str | None] = mapped_column(Text)
