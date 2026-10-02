"""Prompt de sistema versionado.

O texto vive em `backend/ia/prompts/sistema_<versão>.md`, em arquivo, para a revisão (e o
dossiê do piloto) lerem exatamente o que o modelo recebe. Mudou o texto, sobe a versão
(arquivo novo + `VERSAO`): ela é gravada em cada resposta (`ia_mensagens.meta`), então
uma mudança de comportamento da IA é rastreável ao prompt que a causou. O `sistema_v1.md`
fica no repositório como histórico da avaliação de 02/10/2026 (R01, R12 e S01 pediram a v2).

O arquivo é estático e **idêntico para todas as perguntas**; o que muda por pergunta
(data de hoje, domínio) vai em um segundo bloco, fora do cache de prompt (T-30).
"""
from datetime import date
from functools import lru_cache
from pathlib import Path

VERSAO = "sistema_v2"
_PASTA = Path(__file__).resolve().parent / "prompts"


@lru_cache(maxsize=None)
def sistema() -> str:
    return (_PASTA / f"{VERSAO}.md").read_text(encoding="utf-8").strip()


def cabecalho_da_pergunta(hoje: date, dominio: str) -> str:
    """O que muda por pergunta. Curto de propósito: fica fora do trecho cacheado."""
    return (f"Hoje é {hoje.strftime('%d/%m/%Y')} ({hoje.isoformat()}). "
            f"Domínio desta conversa: {dominio}.")
