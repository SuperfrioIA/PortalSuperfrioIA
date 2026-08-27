"""Conexão com o banco da nuvem-ia — por request, somente leitura, falha graciosa.

## Por request, sem pool

Mesmo padrão da V3: um endpoint de leitura, uso interno, sem concorrência que
justifique pool. E é o que permite a falha graciosa: o Hub não abre nada no
startup, então `nuvem-db` fora do ar não impede o Hub de subir.

## Somente leitura por mecanismo, em duas camadas

1. o role `hub_leitura` (criado pela Maria na VM, lote H3) só tem SELECT nas
   `cat_*`;
2. toda conexão daqui abre com `default_transaction_read_only=on`. Mesmo se
   alguém apontar `VOLUMETRIA_DB_URL` para o usuário `nuvem` (dono de tudo), um
   UPDATE escrito por engano neste módulo é recusado pelo Postgres.

## A URL é lida a cada chamada, não no import

Para o módulo poder ser desligado/ligado por variável de ambiente sem tocar no
processo, e para os testes trocarem o destino com `monkeypatch`. O formato é o
do libpq (`postgresql://usuario:senha@host:5432/banco`) — NÃO o do SQLAlchemy
(`postgresql+psycopg://`), que o `DATABASE_URL` do Hub usa.
"""

import os

import psycopg

ENV_URL = "VOLUMETRIA_DB_URL"

# Segundos até desistir de conectar. Curto de propósito: quem espera é uma
# pessoa com a tela aberta, e "banco fora do ar" tem que virar mensagem, não
# spinner eterno.
TEMPO_LIMITE_CONEXAO = 5

# Sem host nem role na mensagem: ela vai para a tela de quem tem `ver`, e o
# formato já está documentado no .env.example.
FALTA_URL = (
    f"volumetria de catering não configurada neste ambiente: falta a variável "
    f"{ENV_URL} (ver .env.example). O resto do Hub não depende dela."
)


class VolumetriaIndisponivel(Exception):
    """O banco da volumetria não está configurado ou não respondeu.

    Vira 503 no router — só neste card. Não é erro do Hub."""


def url() -> str | None:
    valor = (os.environ.get(ENV_URL) or "").strip()
    return valor or None


def conectar() -> psycopg.Connection:
    """Abre a conexão somente leitura. Quem chama fecha (`conn.close()`)."""
    destino = url()
    if destino is None:
        raise VolumetriaIndisponivel(FALTA_URL)
    try:
        return psycopg.connect(
            destino,
            connect_timeout=TEMPO_LIMITE_CONEXAO,
            options="-c default_transaction_read_only=on",
        )
    except (psycopg.Error, ValueError) as erro:
        # `psycopg.Error` cobre banco fora do ar (OperationalError) e URL
        # malformada (ProgrammingError); `ValueError`, parâmetro inválido na
        # conninfo. Sem a mensagem crua do driver: ela pode carregar host e
        # usuário da URL, e isto vai para a tela.
        raise VolumetriaIndisponivel(
            "o banco da volumetria de catering não respondeu "
            f"({type(erro).__name__}). A carga e o banco são da nuvem-ia; o resto "
            "do Hub continua funcionando."
        ) from erro
