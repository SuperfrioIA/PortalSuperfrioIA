"""Retenção do SuperfrioIA: a rotina que apaga o que venceu (DD-25).

| O quê | Prazo | Critério |
|---|---|---|
| `ia_mensagens` | 90 dias | `criado_em` mais antigo que 90 dias |
| `ia_conversas` | — | ficou **sem mensagem** (e não é mais nova que o prazo) |
| `ia_consultas` | 180 dias | `criado_em` mais antigo que 180 dias |

- **Não toca a trilha de auditoria**, nem os eventos `ia.*`: a retenção da
  auditoria geral é decisão separada (D-9b, aberta) e fora deste lote;
- **não toca `ia_concessoes`**: é o histórico de quem teve acesso e quem decidiu;
- **mensagem apagada aos 90 dias não derruba a consulta**: `ia_consultas.mensagem_id`
  é `SET NULL`, então a consulta fica até os 180;
- **roda mesmo com `IA_HABILITADO=false`**: dado retido sem uso continua sendo dado;
- **idempotente e em lotes**: rodar duas vezes seguidas apaga zero na segunda, e um
  volume grande não trava o banco numa transação só;
- "mais antigo que N dias" é **estritamente** mais antigo: a mensagem de exatamente
  90 dias fica e a de 90 dias e 1 segundo sai.

Agendada em `backend/main.py` (`agendar_diario`, `backend/core/scheduler.py`).
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select

from backend.core.database import db
from backend.ia import auditoria, config
from backend.ia.models import IaConsulta, IaConversa, IaMensagem

logger = logging.getLogger("backend.ia.retencao")

LOTE = 1000
JOB_ID = "ia_retencao"

_C, _M, _Q = IaConversa.__table__, IaMensagem.__table__, IaConsulta.__table__


def _corte(agora: datetime, dias: int) -> str:
    return (agora - timedelta(days=dias)).strftime("%Y-%m-%d %H:%M:%S")


def _apagar_em_lotes(tabela, condicao, lote: int) -> int:
    """Apaga o que casa com `condicao`, `lote` linhas por transação."""
    total = 0
    while True:
        with db() as session:
            ids = session.execute(select(tabela.c.id).where(condicao).limit(lote)).scalars().all()
            if not ids:
                return total
            session.execute(delete(tabela).where(tabela.c.id.in_(ids)))
        total += len(ids)


def executar(agora: datetime | None = None, lote: int = LOTE) -> dict:
    """Apaga mensagens, conversas vazias e consultas vencidas. Devolve as contagens."""
    agora = agora or datetime.now(timezone.utc)
    corte_mensagens = _corte(agora, config.retencao_mensagens_dias())
    corte_consultas = _corte(agora, config.retencao_consultas_dias())

    mensagens = _apagar_em_lotes(_M, _M.c.criado_em < corte_mensagens, lote)
    sem_mensagem = ~select(_M.c.id).where(_M.c.conversa_id == _C.c.id).exists()
    conversas = _apagar_em_lotes(_C, (_C.c.atualizado_em < corte_mensagens) & sem_mensagem, lote)
    consultas = _apagar_em_lotes(_Q, _Q.c.criado_em < corte_consultas, lote)

    contagens = {
        "mensagens": mensagens, "conversas": conversas, "consultas": consultas,
        "prazo_mensagens_dias": config.retencao_mensagens_dias(),
        "prazo_consultas_dias": config.retencao_consultas_dias(),
    }
    auditoria.retencao(contagens)
    logger.info("ia retenção: %s", contagens)
    return contagens


def job() -> None:
    """O que o agendador chama. Falha na rotina é registrada e **não derruba o app**."""
    try:
        executar()
    except Exception:
        logger.exception("ia retenção: a rotina falhou")
        try:
            auditoria.erro(None, None, dominio="-", tipo="retencao")
        except Exception:  # a trilha também falhou: já está no log
            logger.exception("ia retenção: não foi possível registrar o erro na trilha")
