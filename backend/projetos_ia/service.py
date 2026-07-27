"""Interface pública do módulo Projetos IA.

Quem precisa destes dados chama estas funções — nunca os models direto (regra
de ouro). Todas recebem a Session do chamador (mesma transação).

Núcleo do módulo: nada de status manual. Quem edita registra fatos (datas,
observações); fase atual, atraso e status de rollout são sempre calculados
aqui a partir da data real (`date.today()`), nunca de um campo gravado.
"""
from datetime import date

from fastapi import HTTPException
from sqlalchemy import delete, insert, select, update

from backend.core.database import _now
from backend.core.http import row_or_404, unique_or_409
from backend.projetos_ia.models import Filial, Projeto, ProjetoFase, ProjetoRollout

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

def listar_filiais(session, apenas_ativas: bool = False) -> list[dict]:
    stmt = select(Filial.__table__).order_by(Filial.regiao, Filial.nome)
    if apenas_ativas:
        stmt = stmt.where(Filial.ativo == 1)
    return [dict(r) for r in session.execute(stmt).mappings().fetchall()]


def criar_filial(session, dados: dict) -> dict:
    with unique_or_409("nome", dados["nome"]):
        cur = session.execute(insert(Filial).values(**dados))
    return row_or_404(session, Filial, cur.inserted_primary_key[0], "filiais")


def atualizar_filial(session, filial_id: int, campos: dict) -> dict:
    row_or_404(session, Filial, filial_id, "filiais")
    if campos:
        session.execute(update(Filial).where(Filial.id == filial_id).values(**campos))
    return row_or_404(session, Filial, filial_id, "filiais")


def toggle_filial(session, filial_id: int) -> dict:
    row = row_or_404(session, Filial, filial_id, "filiais")
    novo = 0 if row["ativo"] else 1
    session.execute(update(Filial).where(Filial.id == filial_id).values(ativo=novo))
    return row_or_404(session, Filial, filial_id, "filiais")


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
