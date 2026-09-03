"""Conexão com o DW Oracle — por request, somente leitura, falha graciosa.

Cópia de `backend/volumetria_catering/conexao_dw.py` (lote D1 de
`docs/PLANO_VOLUMETRIA_DW_DIRETO.md`), que por sua vez veio de
`nuvem-ia catering/carga/fonte_oracle.py` — provado em produção desde
25/ago/2026. Este arquivo é 100% genérico (nada de catering nele), e é
exatamente por isso que ele é a única coisa que dois módulos ganharam
duplicada sem discussão: extrair pra `backend/dw_consulta/` fica para o T1, se
algum dia acontecer.

**Diferente do catering, este módulo não tem `conexao.py` (Postgres)** — não
existe fonte intermediária para transporte, então esta é a ÚNICA conexão.

## A premissa que este arquivo rompe

O desenho de 27/ago/2026 dizia: *"o Hub nunca conecta no DW. O perímetro da
credencial de produção não cresce."* A decisão da Maria de 02/set/2026 troca
isso por três reduções de custo, e as três estão no código:

1. a credencial é **nova e de somente leitura**, não a `DW_USER` da carga — daí
   os nomes `DW_LEITURA_USUARIO`/`DW_LEITURA_SENHA` serem diferentes dos da
   nuvem-ia. Copiar a linha do `.env` de lá para cá não conecta nada, o que é
   exatamente a proteção que se quer: a credencial da carga tem GRANT de escrita
   no Postgres e não deve poder chegar aqui por descuido de copiar-e-colar;
2. ela é digitada **direto no `.env` da VM** — não passa por chat, PR, script de
   deploy nem sessão de IA. Por isso não há default: faltando a variável, isto
   não conecta em lugar nenhum e diz qual variável falta;
3. somente leitura é provada por mecanismo — ver a seção abaixo.

## Somente leitura: o que é mecanismo e o que é promessa

Três camadas, e é honesto dizer de quem é cada uma:

1. **o GRANT do usuário de leitura no DW** (lado do Luciano). É a única que
   impede escrita de verdade; as outras duas impedem que a gente tente;
2. **nunca chamamos `commit`**. O `oracledb` abre a sessão sem autocommit, e
   toda conexão daqui fecha no `finally` de quem a abriu — um DML que
   escapasse morreria no rollback implícito do `close()`;
3. **dois testes**, em `tests/test_volumetria_transporte_dw.py`: um **estático**,
   que percorre a árvore sintática e reprova palavra de escrita em qualquer
   literal deste módulo e qualquer chamada a `commit`/`rollback`/`executemany`;
   e um **de runtime**, com cursor falso que recusa comando que não comece por
   `SELECT`. Nenhum dos dois sozinho basta: o estático não vê escrita montada
   por concatenação, o de runtime não vê caminho que o teste não exercita.

O que deliberadamente **não** fazemos é emitir `ALTER SESSION SET TRANSACTION
READ ONLY`, o equivalente Oracle do `default_transaction_read_only` que o
`conexao.py` usa no Postgres. Dois motivos: ele abre uma transação com snapshot
próprio, e transação longa numa conexão de tela é pior que o problema que
resolveria; e ele obrigaria este módulo a emitir um comando que começa com
`ALTER`, furando as duas guardas acima em troca de uma proteção que o GRANT já
dá. Trocar uma trava que funciona por uma que parece bem é mau negócio.

## Por request, sem pool, nada aberto no startup

Mesmo raciocínio do `conexao.py`: um card de leitura, uso interno, sem
concorrência que justifique pool. E é o que permite a **falha graciosa** — o Hub
não abre nada no startup, então DW fora do ar não impede o Hub de subir nem
derruba `/api/health`. Degrada só este card.

## `fetch_decimals`, a linha que corrompe número se faltar

Medido na nuvem-ia em 25/ago/2026: o `oracledb` vem com
`defaults.fetch_decimals = False`, e com isso todo `NUMBER` chega como `float`.
Peso em kg com 3 decimais passando por ponto flutuante binário perde precisão
**em silêncio**, que é o pior tipo de perda. `conectar()` liga a opção antes de
abrir a sessão.

Ligar isso no import seria mais curto e pior: quem importasse o módulo mudaria o
comportamento global do driver sem pedir.
"""

import logging
import os

logger = logging.getLogger(__name__)

# O que a sondagem de 25/ago/2026 provou funcionar: modo thin (Python puro, sem
# Instant Client — importa para a imagem `python:3.12-slim` do Hub), contra o
# Oracle 12.2.0.1.0. Host, porta e serviço têm padrão porque NÃO são segredo
# (estão no plano e no runbook); usuário e senha não têm.
PADRAO_HOST = "oracleprd-aws.superfrio.com.br"
PADRAO_PORTA = "1521"
PADRAO_SERVICO = "pdwgener"

ENV_HOST = "DW_HOST"
ENV_PORTA = "DW_PORTA"
ENV_SERVICO = "DW_SERVICO"
ENV_USUARIO = "DW_LEITURA_USUARIO"
ENV_SENHA = "DW_LEITURA_SENHA"

# Rede que não responde tem que virar mensagem, não spinner eterno: quem espera
# é uma pessoa com a tela aberta. Mais folgado que os 5 s do Postgres porque o
# D0 mediu as CONSULTAS (0,1 a 1,2 s) e não o aperto de mão do listener, que é
# outro custo e é desconhecido.
TIMEOUT_CONEXAO_SEGUNDOS = 8

# Linhas por round trip. O default do driver é 100, e com ele uma leitura de
# 40 mil linhas custa 400 idas e voltas na rede.
LOTE_LEITURA = 1_000


class DWIndisponivel(Exception):
    """O DW não está configurado ou não respondeu.

    Vira 503 no router — só neste card. Não é erro do Hub."""


class CredencialAusente(DWIndisponivel):
    """Falta `DW_LEITURA_USUARIO` ou `DW_LEITURA_SENHA` no ambiente.

    Subclasse de `DWIndisponivel` de propósito: quem trata "o card está fora"
    não precisa saber a diferença, e quem quer distinguir configuração de rede
    ainda pode. É o mesmo desenho do `VolumetriaIndisponivel` no Postgres."""


def _driver():
    """Import preguiçoso do `oracledb`.

    Preguiçoso para que a suíte que só confere o SQL gerado não dependa do
    driver estar instalado, e para que um ambiente sem o pacote falhe com
    mensagem deste módulo em vez de derrubar o import do router — e com ele o
    Hub inteiro."""
    try:
        import oracledb
    except ImportError as erro:  # pragma: no cover - ambiente sem a dependência
        raise DWIndisponivel(
            "o driver do Oracle (oracledb) não está instalado neste ambiente. "
            "Ele está em requirements.txt; a imagem do Hub precisa de rebuild."
        ) from erro
    return oracledb


def configurar_driver():
    """Liga `fetch_decimals` e devolve o módulo do driver.

    Função própria, e não efeito de import, para poder ser exercitada por teste
    sem abrir conexão: é uma linha que, faltando, corrompe peso em silêncio."""
    oracledb = _driver()
    oracledb.defaults.fetch_decimals = True
    return oracledb


def dsn() -> str:
    """`host:porta/serviço` — a forma que a sondagem de 25/ago/2026 usou.

    Não é segredo, e é o que o diagnóstico mostra: sem ele, "não conectei" não
    diz se o destino estava certo."""
    host = os.environ.get(ENV_HOST) or PADRAO_HOST
    porta = os.environ.get(ENV_PORTA) or PADRAO_PORTA
    servico = os.environ.get(ENV_SERVICO) or PADRAO_SERVICO
    return f"{host}:{porta}/{servico}"


def credencial() -> tuple[str, str]:
    """Usuário e senha do ambiente, ou `CredencialAusente` nomeando o que falta.

    Conferida ANTES de mexer no driver: variável de ambiente faltando é erro de
    configuração e não deve deixar rastro — o `fetch_decimals` é estado global
    do módulo `oracledb`."""
    usuario = (os.environ.get(ENV_USUARIO) or "").strip()
    senha = os.environ.get(ENV_SENHA) or ""
    faltando = [
        nome for nome, valor in ((ENV_USUARIO, usuario), (ENV_SENHA, senha)) if not valor
    ]
    if faltando:
        raise CredencialAusente(
            f"volumetria de transporte não configurada neste ambiente: falta "
            f"{' e '.join(faltando)} (ver .env.example). É a credencial de "
            "SOMENTE LEITURA do DW, digitada à mão no .env da VM. O resto do Hub "
            "não depende dela."
        )
    return usuario, senha


def configurado() -> bool:
    """Se a credencial está no ambiente. Para o diagnóstico poder dizer
    "não configurado" sem tentar conectar — e sem revelar valor nenhum."""
    try:
        credencial()
    except CredencialAusente:
        return False
    return True


def conectar():
    """Sessão nova no DW. Quem chama fecha (`conexao.close()`).

    Nunca guarda nem loga a credencial: o log do Hub fica em arquivo na VM, e
    metade de uma credencial já é informação demais para um arquivo de log."""
    usuario, senha = credencial()
    oracledb = configurar_driver()
    destino = dsn()
    try:
        return oracledb.connect(
            user=usuario,
            password=senha,
            dsn=destino,
            tcp_connect_timeout=TIMEOUT_CONEXAO_SEGUNDOS,
        )
    except Exception as erro:
        # `oracledb.Error` cobriria o esperado (`ORA-01017` senha errada,
        # `DPY-6005` rota fechada), mas erro de configuração do próprio driver
        # sai como `ValueError`/`TypeError` — e um 500 genérico neste card é
        # exatamente o que a falha graciosa existe para evitar. Só o TIPO do
        # erro na mensagem: o texto do driver pode carregar usuário e DSN, e
        # isto chega na tela.
        logger.error("volumetria/DW: sessão não abriu (%s)", type(erro).__name__)
        raise DWIndisponivel(
            f"o DW não respondeu ({type(erro).__name__}). A volumetria de "
            "transporte lê o DW direto; o resto do Hub continua funcionando. Se "
            "isto persistir, o log do Hub tem o tipo do erro e o runbook em "
            "docs/DEPLOY_VM.md diz como conferir a rota até o DW."
        ) from erro


def preparar_cursor(cur) -> None:
    """Os dois atributos que governam o tamanho do round trip.

    Ficam num lugar só porque têm que ser setados ANTES do `execute`, e é o tipo
    de linha que se esquece ao escrever a segunda consulta."""
    cur.arraysize = LOTE_LEITURA
    cur.prefetchrows = LOTE_LEITURA + 1
