"""Status da última tentativa de integração automática via FTP.

Mesmo padrão do `router.py` deste módulo: arquivo JSON simples, sem banco —
só alimenta o indicador que substitui o botão de upload manual na tela.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.core.database import DB_PATH

_STATUS_PATH: Path = DB_PATH.parent / "processos_abertos_ftp_status.json"
_lock = threading.Lock()


def ler_status() -> dict[str, Any]:
    if not _STATUS_PATH.exists():
        return {}
    with _STATUS_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def escrever_status(*, ok: bool, mensagem: str, tentativa: str, data_sucesso: str | None = None) -> None:
    """Sobrescreve o status atual. `data_sucesso` (AAAA-MM-DD) só é atualizado
    quando informado — uma tentativa que falhou não apaga a última data boa."""
    with _lock:
        atual = ler_status()
        novo = {
            "ok": ok,
            "mensagem": mensagem,
            "tentativa": tentativa,
            "em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "ultima_data_sucesso": data_sucesso or atual.get("ultima_data_sucesso"),
        }
        _STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _STATUS_PATH.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(novo, f, ensure_ascii=False)
        tmp.replace(_STATUS_PATH)
