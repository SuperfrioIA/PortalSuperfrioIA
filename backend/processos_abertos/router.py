"""Histórico compartilhado do dashboard "Processos Abertos".

O dashboard (frontend/processos-abertos/, Receita 1 do CONTRIBUTING.md) roda
inteiro no navegador. Este router existe só pra centralizar as semanas
processadas num arquivo compartilhado — sem banco, sem ORM, sem migration —
em vez de cada upload ficar preso ao localStorage de quem processou.

Leitura é pública (mesmo nível de acesso que os arquivos estáticos do app,
que já são abertos sem login). Escrita exige a permissão `processos-abertos:editar`
(ou ser admin) — ver o app na home é uma permissão, atualizar os dados é outra.

A permissão é declarada em `permissoes.py` deste módulo e concedida pela matriz de
acesso na tela de Administração. Nada de slug escrito na mão aqui.
"""
import json
import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.auth.dependencies import get_current_user_optional, require_permissao, usuario_pode
from backend.core.database import DB_PATH
from backend.processos_abertos.permissoes import EDITAR

router = APIRouter(prefix="/api/processos-abertos", tags=["processos-abertos"])

_DATA_PATH: Path = DB_PATH.parent / "processos_abertos_extra.json"
_lock = threading.Lock()


class Semana(BaseModel):
    date: str
    total: int
    d5p: int
    d1: int
    d25: int
    pct: float
    units: int
    resumo: dict[str, Any] = {}
    tipos: dict[str, Any] = {}


def _ler() -> list[dict]:
    if not _DATA_PATH.exists():
        return []
    with _DATA_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def _escrever(semanas: list[dict]) -> None:
    _DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _DATA_PATH.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(semanas, f, ensure_ascii=False)
    tmp.replace(_DATA_PATH)


@router.get("/historico")
def listar_historico() -> list[dict]:
    return _ler()


@router.get("/pode-editar", deprecated=True)
def pode_editar(user: dict | None = Depends(get_current_user_optional)) -> dict:
    """DEPRECADO — use `GET /api/auth/me/permissoes` e cheque `processos-abertos:editar`.

    Mantido porque o app estático é servido com cache (`?v=`) e pode estar rodando
    uma versão anterior do JS por algum tempo depois do deploy. Remover quando o
    frontend embutido já estiver no endpoint global.
    """
    return {"pode_editar": usuario_pode(user, EDITAR)}


@router.post("/historico")
def salvar_semana(semana: Semana, _: dict = Depends(require_permissao(EDITAR))) -> list[dict]:
    """Upsert por `date`: mesma semana reprocessada substitui a anterior."""
    with _lock:
        semanas = _ler()
        payload = semana.model_dump()
        idx = next((i for i, s in enumerate(semanas) if s.get("date") == payload["date"]), None)
        if idx is not None:
            semanas[idx] = payload
        else:
            semanas.append(payload)
        _escrever(semanas)
    return semanas
