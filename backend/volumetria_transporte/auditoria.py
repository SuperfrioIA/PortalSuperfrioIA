"""Auditoria de download: quem baixou o quê, com qual recorte.

Cópia de `backend/volumetria_catering/auditoria.py`, outra tabela
(`volumetria_transporte_downloads`, `models.py`). Mesma sessão própria com
commit imediato — ver lá para o porquê (o download é um stream que pode
morrer no meio; se o registro vivesse na mesma transação da consulta, uma
falha apagaria o próprio rastro da tentativa)."""

import json
import logging

from sqlalchemy import select

from backend.core.database import _now, db
from backend.volumetria_transporte.models import FORMATOS, VolumetriaTransporteDownload

logger = logging.getLogger(__name__)


def abrir(recorte, formato, ip=None, usuario=None) -> int:
    if formato not in FORMATOS:
        raise ValueError(f"formato fora do escopo da auditoria: {formato!r}")
    with db() as session:
        registro = VolumetriaTransporteDownload(
            usuario=usuario or "-",
            formato=formato,
            recorte=json.dumps(recorte or {}, ensure_ascii=False, default=str),
            ip=ip,
            status="rodando",
        )
        session.add(registro)
        session.flush()
        return registro.id


def fechar(registro: int, linhas=None) -> None:
    _atualizar(registro, "ok", linhas=linhas)


def falhar(registro: int, erro) -> None:
    _atualizar(registro, "erro", erro=str(erro)[:2000])
    logger.warning("auditoria volumetria-transporte %s: download falhou -- %s", registro, erro)


def _atualizar(registro: int, status: str, linhas=None, erro=None) -> None:
    with db() as session:
        linha = session.get(VolumetriaTransporteDownload, registro)
        if linha is None:
            logger.warning("auditoria volumetria-transporte %s: registro não encontrado", registro)
            return
        linha.status = status
        linha.terminado_em = _now()
        linha.linhas = linhas
        linha.erro = erro


def _como_dict(linha: VolumetriaTransporteDownload) -> dict:
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
    with db() as session:
        linhas = session.execute(
            select(VolumetriaTransporteDownload)
            .order_by(VolumetriaTransporteDownload.id.desc())
            .limit(limite)
        ).scalars().all()
        return [_como_dict(linha) for linha in linhas]
