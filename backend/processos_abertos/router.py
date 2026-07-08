"""Histórico compartilhado do dashboard "Processos Abertos".

O dashboard (frontend/processos-abertos/, Receita 1 do CONTRIBUTING.md) roda
inteiro no navegador. Este router existe só pra centralizar as semanas
processadas num arquivo compartilhado — sem banco, sem ORM, sem migration —
em vez de cada upload ficar preso ao localStorage de quem processou.

Leitura é pública (mesmo nível de acesso que os arquivos estáticos do app,
que já são abertos sem login). Escrita exige estar logado no portal.
"""
import json
import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.auth.dependencies import get_current_user
from backend.core.database import DB_PATH

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


@router.post("/historico")
def salvar_semana(semana: Semana, _: dict = Depends(get_current_user)) -> list[dict]:
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
