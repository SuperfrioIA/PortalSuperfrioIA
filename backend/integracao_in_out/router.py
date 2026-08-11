"""Base compartilhada do dashboard "Integração In/Out".

O dashboard (frontend/integracao-in-out/, Receita 1 do CONTRIBUTING.md) roda
inteiro no navegador: quem tem permissão sobe o `rpt_jda_in_out_volumetry`,
o JS agrega e manda o resultado pra cá. Este router existe só pra centralizar
essa base num arquivo compartilhado — sem banco, sem ORM, sem migration — em
vez de cada upload ficar preso ao navegador de quem processou.

**Gravação é por (ano, mês), não por data de upload.** O relatório do JDA não
tem coluna de data: só Ano e Mês. Cada envio reescreve por inteiro os meses que
vieram no arquivo e não encosta nos outros. Duas consequências que são o motivo
do desenho:

- subir o mesmo arquivo duas vezes não duplica nada (é substituição, não soma);
- o relatório do mês corrente atualiza só o mês corrente — janeiro a julho
  continuam valendo o que o último arquivo que os continha disse.

Uma unidade que sumiu do mês no arquivo novo some do mês na base: o mês é
limpo antes de receber o conteúdo do envio, senão sobraria número velho de
quem zerou.

Leitura da base é pública (mesmo nível de acesso que os arquivos estáticos do
app, que já são abertos sem login). O log de auditoria — que tem nome de usuário
— e a escrita exigem `integracao-in-out:editar` (ou ser admin).
"""
import json
import math
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from backend.auth.dependencies import require_permissao
from backend.core.database import DB_PATH
from backend.integracao_in_out.permissoes import EDITAR

router = APIRouter(prefix="/api/integracao-in-out", tags=["integracao-in-out"])

_DATA_PATH: Path = DB_PATH.parent / "integracao_in_out.json"
_lock = threading.Lock()

# Log de auditoria: quem subiu o quê, quando. Cortado no envio mais antigo pra
# não crescer sem limite — um upload por dia útil dá ~1 ano de rastro.
_MAX_UPLOADS = 250

_DIRECOES = ("IN", "OUT")
_RE_ANO = re.compile(r"^\d{4}$")
_RE_MES = re.compile(r"^(0[1-9]|1[0-2])$")

# Tetos de sanidade do payload — o relatório real tem ~20 unidades e ~120
# clientes. Existem pra um POST malformado (ou malicioso) não virar um JSON de
# centenas de MB no disco do servidor.
_MAX_UNIDADES = 300
_MAX_CLIENTES = 5_000
_MAX_ANOS = 10

# Índices do vetor de contagem, na ordem em que o frontend monta:
# [integrado_pedidos, total_pedidos, integrado_linhas, total_linhas,
#  integrado_ondas, total_ondas]
_TAM_VETOR = 6
_I_PEDIDOS_INT, _I_PEDIDOS_TOT = 0, 1


def _valida_contagens(por_chave: dict, *, maximo: int, rotulo: str) -> None:
    if len(por_chave) > maximo:
        raise ValueError(f"{rotulo}: máximo de {maximo} entradas por direção")
    for chave, por_mes in por_chave.items():
        if not chave or len(chave) > 120:
            raise ValueError(f"{rotulo}: chave inválida")
        for mes, vetor in por_mes.items():
            if not _RE_MES.match(mes):
                raise ValueError(f"{rotulo}: mês inválido '{mes}' (esperado 01–12)")
            if len(vetor) != _TAM_VETOR:
                raise ValueError(f"{rotulo}: vetor do mês {mes} precisa ter {_TAM_VETOR} números")
            for n in vetor:
                if not math.isfinite(n) or n < 0:
                    raise ValueError(f"{rotulo}: contagem inválida no mês {mes}")


class BaseAno(BaseModel):
    """Agregado de um ano: por unidade (`agg`) e por cliente (`cli`)."""

    agg: dict[str, dict[str, dict[str, list[float]]]] = Field(default_factory=dict)
    cli: dict[str, dict[str, dict[str, list[float]]]] = Field(default_factory=dict)
    climap: dict[str, str] = Field(default_factory=dict)

    @field_validator("agg", "cli")
    @classmethod
    def _direcoes_conhecidas(cls, v: dict, info) -> dict:
        desconhecidas = set(v) - set(_DIRECOES)
        if desconhecidas:
            raise ValueError(f"direções inválidas: {sorted(desconhecidas)}")
        maximo = _MAX_UNIDADES if info.field_name == "agg" else _MAX_CLIENTES
        for direcao, por_chave in v.items():
            _valida_contagens(por_chave, maximo=maximo, rotulo=f"{info.field_name}.{direcao}")
        return v

    @field_validator("climap")
    @classmethod
    def _climap_limitado(cls, v: dict) -> dict:
        if len(v) > _MAX_CLIENTES:
            raise ValueError(f"climap: máximo de {_MAX_CLIENTES} clientes")
        return v


class Envio(BaseModel):
    """Um upload do relatório, já agregado pelo navegador."""

    arquivo: str = Field(default="", max_length=260)
    linhas: int = Field(default=0, ge=0)
    anos: dict[str, BaseAno]

    @field_validator("anos")
    @classmethod
    def _anos_validos(cls, v: dict) -> dict:
        if not v:
            raise ValueError("nenhum ano no envio")
        if len(v) > _MAX_ANOS:
            raise ValueError(f"máximo de {_MAX_ANOS} anos por envio")
        invalidos = [a for a in v if not _RE_ANO.match(a)]
        if invalidos:
            raise ValueError(f"ano inválido: {sorted(invalidos)} (esperado AAAA)")
        return v


def _vazio() -> dict[str, Any]:
    return {"anos": {}, "atualizado_em": None, "arquivo": None, "uploads": []}


def _ler() -> dict[str, Any]:
    if not _DATA_PATH.exists():
        return _vazio()
    with _DATA_PATH.open("r", encoding="utf-8") as f:
        dados = json.load(f)
    base = _vazio()
    base.update(dados)
    return base


def _escrever(base: dict[str, Any]) -> None:
    _DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _DATA_PATH.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(base, f, ensure_ascii=False)
    tmp.replace(_DATA_PATH)


def _meses_do_ano(ano: BaseAno) -> set[str]:
    """Meses que o envio traz — é o que define o que vai ser reescrito."""
    meses: set[str] = set()
    for escopo in (ano.agg, ano.cli):
        for por_chave in escopo.values():
            for por_mes in por_chave.values():
                meses.update(por_mes)
    return meses


def _aplicar_ano(base_ano: dict[str, Any], novo: BaseAno, meses: set[str]) -> None:
    for escopo in ("agg", "cli"):
        entrada = getattr(novo, escopo)
        atual = base_ano.setdefault(escopo, {})
        for direcao in _DIRECOES:
            destino = atual.setdefault(direcao, {})
            for chave in list(destino):
                for mes in meses:
                    destino[chave].pop(mes, None)
                if not destino[chave]:
                    del destino[chave]
            for chave, por_mes in entrada.get(direcao, {}).items():
                destino.setdefault(chave, {}).update(por_mes)
    base_ano.setdefault("climap", {}).update(novo.climap)


def _totais_pedidos(ano: BaseAno) -> dict[str, list[float]]:
    """Integrado/total de pedidos por direção — só pro log de auditoria."""
    totais = {d: [0.0, 0.0] for d in _DIRECOES}
    for direcao, por_unidade in ano.agg.items():
        for por_mes in por_unidade.values():
            for vetor in por_mes.values():
                totais[direcao][0] += vetor[_I_PEDIDOS_INT]
                totais[direcao][1] += vetor[_I_PEDIDOS_TOT]
    return totais


@router.get("/base")
def ler_base() -> dict[str, Any]:
    """Base atual, por ano. Público — sem o log, que tem nome de usuário."""
    base = _ler()
    return {
        "anos": base["anos"],
        "atualizado_em": base["atualizado_em"],
        "arquivo": base["arquivo"],
    }


@router.get("/uploads")
def listar_uploads(_: dict = Depends(require_permissao(EDITAR))) -> list[dict]:
    """Log de auditoria dos envios — mais recente primeiro."""
    return list(reversed(_ler()["uploads"]))


@router.post("/base")
def gravar_base(envio: Envio, user: dict = Depends(require_permissao(EDITAR))) -> dict[str, Any]:
    """Reescreve os meses presentes no envio; os demais ficam como estavam."""
    resumo: dict[str, list[str]] = {}
    for ano, dados in envio.anos.items():
        meses = _meses_do_ano(dados)
        if not meses:
            raise HTTPException(status_code=422, detail=f"o ano {ano} veio sem nenhum mês")
        resumo[ano] = sorted(meses)

    agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _lock:
        base = _ler()
        for ano, dados in envio.anos.items():
            _aplicar_ano(base["anos"].setdefault(ano, {}), dados, set(resumo[ano]))
        base["atualizado_em"] = agora
        base["arquivo"] = envio.arquivo or None
        base["uploads"].append(
            {
                "em": agora,
                "por": user.get("username"),
                "arquivo": envio.arquivo or None,
                "linhas": envio.linhas,
                "meses": resumo,
                "totais": {
                    ano: _totais_pedidos(dados) for ano, dados in envio.anos.items()
                },
            }
        )
        base["uploads"] = base["uploads"][-_MAX_UPLOADS:]
        _escrever(base)

    return {"anos": base["anos"], "atualizado_em": agora, "arquivo": base["arquivo"]}
