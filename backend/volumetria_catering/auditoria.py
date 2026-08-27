"""Auditoria de download: quem baixou o que, com qual recorte.

Reescrita pequena do `catering/auditoria.py` da nuvem-ia: mesma forma
(`abrir` -> `fechar`/`falhar`), outro destino — a tabela `volumetria_downloads`
do banco do Hub (`models.py`), via SQLAlchemy. Só download: login é do Hub.

## Sessão própria, commit imediato

O download é um *stream* que pode morrer no meio. Se o registro vivesse na
mesma transação da consulta, uma falha apagaria o próprio rastro da tentativa.
Por isso `abrir()` grava e commita **antes** de a primeira linha sair
(`db()` commita ao sair do bloco), e `fechar()`/`falhar()` atualizam depois,
em sessão nova.
"""

import json
import logging

from sqlalchemy import select

from backend.core.database import _now, db
from backend.volumetria_catering.models import FORMATOS, VolumetriaDownload

logger = logging.getLogger(__name__)


def abrir(recorte, formato, ip=None, usuario=None) -> int:
    """Registra a tentativa e devolve o id. Commita na hora."""
    if formato not in FORMATOS:
        raise ValueError(f"formato fora do escopo da auditoria: {formato!r}")
    with db() as session:
        registro = VolumetriaDownload(
            usuario=usuario or "-",
            formato=formato,
            recorte=json.dumps(recorte or {}, ensure_ascii=False, default=str),
            ip=ip,
            status="rodando",
        )
        session.add(registro)
        session.flush()  # id gerado agora; o commit é do `db()`
        return registro.id


def fechar(registro: int, linhas=None) -> None:
    """Conclui o registro com a contagem de linhas que realmente saíram."""
    _atualizar(registro, "ok", linhas=linhas)


def falhar(registro: int, erro) -> None:
    """Marca a tentativa como falha. Download interrompido não pode aparecer
    como concluído."""
    _atualizar(registro, "erro", erro=str(erro)[:2000])
    logger.warning("auditoria volumetria %s: download falhou -- %s", registro, erro)


def _atualizar(registro: int, status: str, linhas=None, erro=None) -> None:
    with db() as session:
        linha = session.get(VolumetriaDownload, registro)
        if linha is None:
            logger.warning("auditoria volumetria %s: registro não encontrado", registro)
            return
        linha.status = status
        linha.terminado_em = _now()
        linha.linhas = linhas
        linha.erro = erro


def _como_dict(linha: VolumetriaDownload) -> dict:
    return {
        "id": linha.id,
        "criado_em": linha.criado_em,
        "terminado_em": linha.terminado_em,
        "usuario": linha.usuario,
        "formato": linha.formato,
        "recorte": json.loads(linha.recorte or "{}"),
        "linhas": linha.linhas,
        "ip": linha.ip,
        "status": linha.status,
        "erro": linha.erro,
    }


def listar(limite: int = 100) -> list[dict]:
    """As últimas tentativas, mais recente primeiro."""
    with db() as session:
        linhas = session.execute(
            select(VolumetriaDownload)
            .order_by(VolumetriaDownload.id.desc())
            .limit(limite)
        ).scalars().all()
        return [_como_dict(linha) for linha in linhas]
