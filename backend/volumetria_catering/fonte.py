"""A chave que escolhe de onde a tela lê: o Postgres intermediário ou o DW direto.

Lote C2 do plano revisado em 06/set/2026 (`docs/PLANO_VOLUMETRIA_DW_DIRETO.md`).

## Por que uma chave, e não uma reescrita

O plano de 02/set mandava reescrever `recorte.py`, `matriz.py`, `planilha.py` e
`download.py` no lugar, trocando o SQL do Postgres pelo do Oracle. Isso era
aceitável enquanto valia a premissa de que "a volumetria nunca rodou em produção
no Hub". Ela caiu em 06/set: **o card está no ar com usuários**. Com gente na
tela, o rebuild que sobe o SQL novo passa a SER a virada — e se a tradução
estiver errada, descobre-se com a tela quebrada na frente de quem usa, e voltar
exige rollback de imagem.

A chave troca isso por três coisas:

1. os arquivos do Postgres **ficam intactos**, e os do Oracle entram ao lado
   (`*_dw.py`). Nenhum lote de código muda o que a tela mostra enquanto a chave
   estiver em `postgres` — então cada lote pode ir para produção normalmente;
2. a virada vira **uma linha no `.env` da VM + restart**, reversível em segundos
   sem imagem anterior;
3. os dois caminhos ficam vivos ao mesmo tempo, o que é o que permite compará-los
   **em produção, com dado real** (o comparador só-admin do C3) antes de virar.

O custo é o módulo carregar os dois conjuntos de arquivos por uma ou duas
semanas. O C6 apaga o lado Postgres, e esta chave junto.

## Lida a cada chamada, não no import

Como `conexao.url()`: para os testes trocarem a fonte com `monkeypatch`, e para
não existir estado de módulo que a suíte precise zerar. No container a variável
é lida no start de qualquer jeito (`docker compose up -d` relê o `.env`;
`restart` sozinho não — ver `docs/DEPLOY_VM.md` §1).

## Valor inválido é erro nomeando a variável, não silêncio

`VOLUMETRIA_CATERING_FONTE=oracle` (um valor que parece certo e não é) tem que
virar 503 dizendo o que se esperava — nunca cair no padrão em silêncio. Cair no
padrão faria a Maria acreditar que virou e a tela continuar no Postgres.
"""

import os

ENV_FONTE = "VOLUMETRIA_CATERING_FONTE"

POSTGRES = "postgres"
DW = "dw"
FONTES = (POSTGRES, DW)

# O padrão é o que está em produção hoje. Trocar o padrão é decisão do C6, não
# deste arquivo.
PADRAO = POSTGRES


class FonteInvalida(ValueError):
    """Valor de `VOLUMETRIA_CATERING_FONTE` que não é nenhuma das fontes."""


def ativa() -> str:
    """A fonte que a tela usa agora: `postgres` ou `dw`."""
    bruto = (os.environ.get(ENV_FONTE) or "").strip().lower()
    if not bruto:
        return PADRAO
    if bruto not in FONTES:
        raise FonteInvalida(
            f"{ENV_FONTE}={bruto!r} não é uma fonte conhecida "
            f"(esperado {POSTGRES!r} ou {DW!r}; vazio = {PADRAO!r})"
        )
    return bruto


def e_dw() -> bool:
    return ativa() == DW
