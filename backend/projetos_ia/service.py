"""Interface pública do módulo Projetos IA.

Quem precisa destes dados chama estas funções — nunca os models direto (regra
de ouro). Todas recebem a Session do chamador (mesma transação).

Núcleo do módulo: nada de status manual. Quem edita registra fatos (datas,
observações); fase atual, atraso e status de rollout são sempre calculados
aqui a partir da data real (`date.today()`), nunca de um campo gravado.
"""
from datetime import date

from fastapi import HTTPException
from sqlalchemy import delete, func, insert, select, update

from backend.core.database import _now
from backend.core.http import row_or_404, unique_or_409
from backend.projetos_ia.models import (
    Filial,
    Projeto,
    ProjetoFase,
    ProjetoRollout,
    UnidadeNegocio,
)

FASES = (
    "Ideia recebida", "Em avaliação", "POC / Validação", "Construção TI",
    "Implantação", "Acompanhamento", "Em suporte",
)
N_FASES = len(FASES)
ULTIMA_FASE = N_FASES - 1
# Primeira fase (índice) em que o rollout por filial passa a fazer sentido.
FASE_INICIO_ROLLOUT = 4


def _hoje() -> date:
    return date.today()


def _parse(iso: str | None) -> date | None:
    return date.fromisoformat(iso) if iso else None


# ---------- Derivações (nunca gravadas — sempre recalculadas na leitura) ----------

def _fase_atual(fases: list[dict]) -> int:
    """Primeira fase sem conclusão; se todas concluídas, fica na última (Em suporte)."""
    for f in sorted(fases, key=lambda x: x["ordem"]):
        if not f["concluido_em"]:
            return f["ordem"]
    return ULTIMA_FASE


def _atraso_dias(fases_por_ordem: dict[int, dict], fase_atual: int, hoje: date) -> int:
    if fase_atual >= ULTIMA_FASE:
        return 0
    fim = _parse(fases_por_ordem[fase_atual]["previsto_fim"])
    if fim is None or fim >= hoje:
        return 0
    return (hoje - fim).days


def _status_rollout(r: dict, hoje: date) -> str:
    if r["nao_se_aplica"]:
        return "nao_se_aplica"
    d = _parse(r["data"])
    if d is None:
        return "pendente"
    return "treinada" if d <= hoje else "agendada"


def _rollout_resumo(rollout_com_status: list[dict]) -> dict | None:
    if not rollout_com_status:
        return None
    previstas = [r for r in rollout_com_status if r["status"] != "nao_se_aplica"]
    treinadas = [r for r in previstas if r["status"] == "treinada"]
    agendadas = [r for r in previstas if r["status"] == "agendada"]
    pendentes = [r for r in previstas if r["status"] == "pendente"]
    proxima = min(agendadas, key=lambda r: r["data"]) if agendadas else None
    return {
        "previstas": len(previstas),
        "treinadas": len(treinadas),
        "agendadas": len(agendadas),
        "pendentes": len(pendentes),
        "nao_se_aplica": len(rollout_com_status) - len(previstas),
        "pct": round(len(treinadas) / len(previstas) * 100) if previstas else 0,
        "proximo_treinamento": proxima,
    }


# ---------- Leitura ----------

def _fases_do_projeto(session, projeto_id: int) -> list[dict]:
    rows = session.execute(
        select(ProjetoFase.__table__)
        .where(ProjetoFase.projeto_id == projeto_id)
        .order_by(ProjetoFase.ordem)
    ).mappings().fetchall()
    return [dict(r) for r in rows]


def _rollout_do_projeto(session, projeto_id: int) -> list[dict]:
    hoje = _hoje()
    rows = session.execute(
        select(
            ProjetoRollout.__table__,
            Filial.nome.label("filial_nome"),
            Filial.uf.label("filial_uf"),
            Filial.regiao.label("filial_regiao"),
        )
        .join_from(ProjetoRollout, Filial, Filial.id == ProjetoRollout.filial_id)
        .where(ProjetoRollout.projeto_id == projeto_id)
    ).mappings().fetchall()
    return [{**dict(r), "status": _status_rollout(r, hoje)} for r in rows]


def _com_derivados(session, projeto: dict, incluir_rollout: bool) -> dict:
    """`fases` sempre vai junto (leve, só 7 linhas — a visão Gantt do portfólio
    precisa delas mesmo na lista). `rollout` (bruto, com nome/status por
    filial) só na leitura de um projeto só; a lista usa `rollout_resumo`."""
    fases = _fases_do_projeto(session, projeto["id"])
    fase_atual = _fase_atual(fases)
    atrasado_dias = _atraso_dias({f["ordem"]: f for f in fases}, fase_atual, _hoje())
    rollout = _rollout_do_projeto(session, projeto["id"]) if fase_atual >= FASE_INICIO_ROLLOUT else []
    extra = {
        "fase_atual": fase_atual,
        "atrasado_dias": atrasado_dias,
        "fases": fases,
        "rollout_resumo": _rollout_resumo(rollout),
    }
    if incluir_rollout:
        extra["rollout"] = rollout
    return {**projeto, **extra}


def listar_projetos(session) -> list[dict]:
    rows = session.execute(
        select(Projeto.__table__).where(Projeto.ativo == 1).order_by(Projeto.nome)
    ).mappings().fetchall()
    return [_com_derivados(session, dict(r), incluir_rollout=False) for r in rows]


def projeto_por_slug_or_404(session, slug: str) -> dict:
    row = session.execute(
        select(Projeto.__table__).where(Projeto.slug == slug)
    ).mappings().fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"projeto '{slug}' não encontrado")
    return dict(row)


def detalhe_projeto(session, slug: str) -> dict:
    projeto = projeto_por_slug_or_404(session, slug)
    return _com_derivados(session, projeto, incluir_rollout=True)


# ---------- Escrita: projeto ----------

def criar_projeto(session, dados: dict, plano: list[dict]) -> dict:
    """`plano`: lista com exatamente `N_FASES` janelas {previsto_inicio, previsto_fim}."""
    if len(plano) != N_FASES:
        raise HTTPException(400, f"plano precisa ter exatamente {N_FASES} fases")
    with unique_or_409("slug", dados["slug"]):
        cur = session.execute(insert(Projeto).values(**dados, atualizado_em=_now()))
    projeto_id = cur.inserted_primary_key[0]
    for ordem, janela in enumerate(plano):
        session.execute(
            insert(ProjetoFase).values(
                projeto_id=projeto_id, ordem=ordem,
                previsto_inicio=janela["previsto_inicio"],
                previsto_fim=janela.get("previsto_fim"),
            )
        )
    return detalhe_projeto(session, dados["slug"])


def atualizar_projeto(session, slug: str, campos: dict) -> dict:
    projeto = projeto_por_slug_or_404(session, slug)
    if campos:
        session.execute(
            update(Projeto).where(Projeto.id == projeto["id"]).values(**campos, atualizado_em=_now())
        )
    return detalhe_projeto(session, slug)


def atualizar_fase(session, slug: str, ordem: int, campos: dict, usuario_nome: str) -> dict:
    projeto = projeto_por_slug_or_404(session, slug)
    fase = session.execute(
        select(ProjetoFase.__table__).where(
            ProjetoFase.projeto_id == projeto["id"], ProjetoFase.ordem == ordem
        )
    ).mappings().fetchone()
    if not fase:
        raise HTTPException(404, f"fase {ordem} não encontrada para o projeto '{slug}'")

    valores = dict(campos)
    if "concluido_em" in valores:
        valores["registrado_por"] = usuario_nome if valores["concluido_em"] else None

    if valores:
        session.execute(update(ProjetoFase).where(ProjetoFase.id == fase["id"]).values(**valores))
    session.execute(update(Projeto).where(Projeto.id == projeto["id"]).values(atualizado_em=_now()))
    return detalhe_projeto(session, slug)


# ---------- Filiais (catálogo, administrado em /api/admin/filiais) ----------

def _stmt_filiais():
    """Filial + nome da B.U (LEFT JOIN — filial sem B.U é o caso normal)."""
    return (
        select(Filial.__table__, UnidadeNegocio.nome.label("unidade_negocio_nome"))
        .join_from(
            Filial, UnidadeNegocio,
            UnidadeNegocio.id == Filial.unidade_negocio_id, isouter=True,
        )
        .order_by(Filial.regiao, Filial.nome)
    )


def _filial_detalhe(session, filial_id: int) -> dict:
    row_or_404(session, Filial, filial_id, "filiais")  # 404 padronizado da casa
    return dict(session.execute(_stmt_filiais().where(Filial.id == filial_id)).mappings().fetchone())


def _valida_unidade_negocio(session, unidade_negocio_id) -> None:
    """B.U inexistente é erro do chamador (400), não 404 da filial."""
    if unidade_negocio_id is None:
        return
    existe = session.execute(
        select(UnidadeNegocio.id).where(UnidadeNegocio.id == unidade_negocio_id)
    ).scalar_one_or_none()
    if existe is None:
        raise HTTPException(400, f"unidade de negócio {unidade_negocio_id} não existe")


def _texto(valores: dict, campos: tuple[str, ...]) -> dict:
    """Apara espaços e transforma "" em None (o Pydantic aceita string vazia)."""
    out = dict(valores)
    for campo in campos:
        if isinstance(out.get(campo), str):
            out[campo] = out[campo].strip() or None
    return out


def _normaliza_filial(dados: dict, criando: bool) -> dict:
    """UF sempre em maiúscula (`sp` e `SP` são a mesma coisa) e obrigatório em
    branco vira 400 — sem isso um `nome` só com espaços viraria 500 no NOT NULL."""
    out = _texto(dados, ("codigo", "nome", "cidade", "uf", "regiao", "responsavel"))
    if out.get("uf"):
        out["uf"] = out["uf"].upper()
    obrigatorios = ("codigo", "nome", "regiao")
    vazios = [
        c for c in obrigatorios
        if (criando and not out.get(c)) or (not criando and c in out and not out[c])
    ]
    if vazios:
        raise HTTPException(400, f"campo(s) obrigatório(s) em branco: {', '.join(vazios)}")
    return out


def listar_filiais(session, apenas_ativas: bool = False) -> list[dict]:
    stmt = _stmt_filiais()
    if apenas_ativas:
        stmt = stmt.where(Filial.ativo == 1)
    return [dict(r) for r in session.execute(stmt).mappings().fetchall()]


def filial_por_id(session, filial_id: int) -> dict | None:
    """Uma filial pelo id, ou None. Existe para outros módulos (ex.: Usuários, que
    vincula pessoa a filial) não lerem a tabela `filiais` direto — regra de ouro do
    CONTRIBUTING.md."""
    row = session.execute(
        _stmt_filiais().where(Filial.id == filial_id)
    ).mappings().fetchone()
    return dict(row) if row else None


def criar_filial(session, dados: dict) -> dict:
    """`codigo` é a chave de negócio (mesmo do ERP/Conciliador) — daí o 409 nele."""
    dados = _normaliza_filial(dados, criando=True)
    _valida_unidade_negocio(session, dados.get("unidade_negocio_id"))
    with unique_or_409("codigo", dados["codigo"]):
        cur = session.execute(insert(Filial).values(**dados))
    return _filial_detalhe(session, cur.inserted_primary_key[0])


def atualizar_filial(session, filial_id: int, campos: dict) -> dict:
    row_or_404(session, Filial, filial_id, "filiais")
    campos = _normaliza_filial(campos, criando=False)
    if "unidade_negocio_id" in campos:
        _valida_unidade_negocio(session, campos["unidade_negocio_id"])
    if campos:
        session.execute(update(Filial).where(Filial.id == filial_id).values(**campos))
    return _filial_detalhe(session, filial_id)


def toggle_filial(session, filial_id: int) -> dict:
    row = row_or_404(session, Filial, filial_id, "filiais")
    novo = 0 if row["ativo"] else 1
    session.execute(update(Filial).where(Filial.id == filial_id).values(ativo=novo))
    return _filial_detalhe(session, filial_id)


# ---------- Unidades de negócio (B.U — catálogo admin) ----------

def _stmt_unidades_negocio():
    """B.U + quantas filiais estão vinculadas (derivado, não guardamos contador).

    `group_by` só pela PK: Postgres aceita por dependência funcional e SQLite
    não se importa.
    """
    return (
        select(UnidadeNegocio.__table__, func.count(Filial.id).label("filiais"))
        .join_from(
            UnidadeNegocio, Filial,
            Filial.unidade_negocio_id == UnidadeNegocio.id, isouter=True,
        )
        .group_by(UnidadeNegocio.id)
        .order_by(UnidadeNegocio.nome)
    )


def _unidade_negocio_detalhe(session, unidade_id: int) -> dict:
    row_or_404(session, UnidadeNegocio, unidade_id, "unidades de negócio")
    stmt = _stmt_unidades_negocio().where(UnidadeNegocio.id == unidade_id)
    return dict(session.execute(stmt).mappings().fetchone())


def listar_unidades_negocio(session, apenas_ativas: bool = False) -> list[dict]:
    stmt = _stmt_unidades_negocio()
    if apenas_ativas:
        stmt = stmt.where(UnidadeNegocio.ativo == 1)
    return [dict(r) for r in session.execute(stmt).mappings().fetchall()]


def _normaliza_unidade_negocio(dados: dict, criando: bool) -> dict:
    out = _texto(dados, ("nome", "responsavel"))
    if (criando and not out.get("nome")) or (not criando and "nome" in out and not out["nome"]):
        raise HTTPException(400, "nome da unidade de negócio em branco")
    return out


def criar_unidade_negocio(session, dados: dict) -> dict:
    dados = _normaliza_unidade_negocio(dados, criando=True)
    with unique_or_409("nome", dados["nome"]):
        cur = session.execute(insert(UnidadeNegocio).values(**dados))
    return _unidade_negocio_detalhe(session, cur.inserted_primary_key[0])


def atualizar_unidade_negocio(session, unidade_id: int, campos: dict) -> dict:
    """O nome pode mudar — a filial liga por id, não por nome (igual no Conciliador)."""
    row_or_404(session, UnidadeNegocio, unidade_id, "unidades de negócio")
    campos = _normaliza_unidade_negocio(campos, criando=False)
    if campos:
        with unique_or_409("nome", campos.get("nome")):
            session.execute(
                update(UnidadeNegocio).where(UnidadeNegocio.id == unidade_id).values(**campos)
            )
    return _unidade_negocio_detalhe(session, unidade_id)


def toggle_unidade_negocio(session, unidade_id: int) -> dict:
    """Inativar não desfaz os vínculos — a filial continua apontando pra B.U."""
    row = row_or_404(session, UnidadeNegocio, unidade_id, "unidades de negócio")
    novo = 0 if row["ativo"] else 1
    session.execute(update(UnidadeNegocio).where(UnidadeNegocio.id == unidade_id).values(ativo=novo))
    return _unidade_negocio_detalhe(session, unidade_id)


# ---------- Rollout (projeto × filial) ----------

def _rollout_row_or_404(session, projeto_id: int, filial_id: int) -> dict:
    row = session.execute(
        select(ProjetoRollout.__table__).where(
            ProjetoRollout.projeto_id == projeto_id, ProjetoRollout.filial_id == filial_id
        )
    ).mappings().fetchone()
    if not row:
        raise HTTPException(404, "filial não está no escopo de rollout deste projeto")
    return dict(row)


def incluir_rollout(session, slug: str, filial_id: int) -> dict:
    projeto = projeto_por_slug_or_404(session, slug)
    row_or_404(session, Filial, filial_id, "filiais")
    existe = session.execute(
        select(ProjetoRollout.id).where(
            ProjetoRollout.projeto_id == projeto["id"], ProjetoRollout.filial_id == filial_id
        )
    ).scalar_one_or_none()
    if existe is not None:
        raise HTTPException(409, "filial já está no escopo de rollout deste projeto")
    session.execute(insert(ProjetoRollout).values(projeto_id=projeto["id"], filial_id=filial_id))
    session.execute(update(Projeto).where(Projeto.id == projeto["id"]).values(atualizado_em=_now()))
    return detalhe_projeto(session, slug)


def atualizar_rollout(session, slug: str, filial_id: int, campos: dict) -> dict:
    projeto = projeto_por_slug_or_404(session, slug)
    row = _rollout_row_or_404(session, projeto["id"], filial_id)
    if campos:
        session.execute(update(ProjetoRollout).where(ProjetoRollout.id == row["id"]).values(**campos))
    session.execute(update(Projeto).where(Projeto.id == projeto["id"]).values(atualizado_em=_now()))
    return detalhe_projeto(session, slug)


def remover_rollout(session, slug: str, filial_id: int) -> dict:
    projeto = projeto_por_slug_or_404(session, slug)
    row = _rollout_row_or_404(session, projeto["id"], filial_id)
    session.execute(delete(ProjetoRollout).where(ProjetoRollout.id == row["id"]))
    session.execute(update(Projeto).where(Projeto.id == projeto["id"]).values(atualizado_em=_now()))
    return detalhe_projeto(session, slug)
