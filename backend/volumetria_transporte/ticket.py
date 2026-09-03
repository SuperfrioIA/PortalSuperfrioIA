"""Ticket de curta duração para o download — o único jeito de o navegador
baixar um arquivo autenticado neste Hub.

Cópia de `backend/volumetria_catering/ticket.py`: nada aqui é específico de
catering (é JWT genérico assinado com o segredo do Hub), então o `ticket.py`
já avisava "se um segundo app precisar do mesmo mecanismo, é hora de subir
para `backend/auth/`". O segundo (e terceiro) chegaram; a extração fica para
quando alguém decidir fazer o T1.

## O problema

O Hub autentica com `Authorization: Bearer`, e o token mora no `localStorage`:
só o JavaScript o alcança. O download, porém, **navega** (`window.location`),
porque é a navegação que faz o navegador salvar o arquivo com o nome do
`Content-Disposition` e que deixa o CSV sair em *streaming* — e navegação não
carrega header nenhum. Sem isto, a tela tomaria 401 na cara do usuário.

O caminho alternativo era baixar por `fetch` e salvar um Blob, mas isso traz o
arquivo inteiro para a memória da aba — e o CSV sai em streaming justamente
porque o recorte passa de 400 mil linhas (decisão da Maria, 27/ago/2026, opção B
do lote H2 em `docs/PLANO_VOLUMETRIA_CATERING.md`).

## O desenho

Um JWT assinado com o **mesmo segredo do Hub** (não nasce um segundo segredo),
com validade de um minuto e três amarras:

- `escopo`: vale só para o download deste módulo. Um ticket não é um token de
  sessão e não abre mais nada;
- `rec`: a impressão digital do recorte pedido. Ticket de um recorte **não
  serve para outro** — quem interceptasse não trocaria os filtros;
- `sub` + `tver`: quem pediu, e a versão do token dele. É a mesma checagem do
  `get_current_user`, então logout, troca de senha ou revogação **matam o
  ticket** antes do minuto acabar. A permissão `exportar` é reconferida no banco
  no momento do download, não só na emissão.

## Por que `tver` e não `tv`

`get_current_user` exige o claim `tv` para aceitar um Bearer. O ticket guarda a
mesma informação com **outro nome**, de propósito: assim ele é recusado como
token de sessão em todo o resto do Hub. Com `tv`, um ticket achado no histórico
ou no log do balanceador valeria por um minuto como a pessoa inteira — e é
justamente porque ele viaja em lugar exposto que ele não pode valer isso. Ticket
serve para um download e nada mais.

O ticket viaja na query string, e por isso a validade é curta: o log de acesso
do Hub nunca grava query string (ver `backend/main.py`), mas o histórico do
navegador grava, e o log do balanceador registra a request line.

Mora aqui, e não em `backend/auth/`, porque hoje este é o único download
servido pelo backend em todo o Hub. Se um segundo app precisar do mesmo
mecanismo, é hora de subir para `backend/auth/` — não antes.
"""

import hashlib
from datetime import datetime, timedelta, timezone

import jwt

from backend.auth.service import JWT_ALG, JWT_SECRET
from backend.volumetria_transporte.permissoes import APP_SLUG

ESCOPO = f"{APP_SLUG}:download"

# Um minuto: o ticket é pedido e usado no mesmo clique — o que existe entre os
# dois é uma navegação. Prazo maior só aumentaria a janela de quem achasse a URL
# no histórico de uma máquina compartilhada.
VALIDO_POR_SEGUNDOS = 60


class TicketInvalido(Exception):
    """Ticket ausente, expirado, adulterado, de outro escopo ou de outro
    recorte. A mensagem é para a tela, então diz o que fazer."""


def assinatura_do_recorte(itens) -> str:
    """Impressão digital dos parâmetros do download.

    Recebe pares `(chave, valor)` — `request.query_params.multi_items()` menos o
    próprio `ticket` — e devolve um sha256 estável. **Ordenado**: a mesma
    consulta com os filtros em ordem diferente é o mesmo recorte, e sem ordenar
    o ticket morreria por um detalhe de montagem da URL.
    """
    cru = "&".join(f"{chave}={valor}" for chave, valor in sorted(itens))
    return hashlib.sha256(cru.encode("utf-8")).hexdigest()


def emitir(usuario: dict, itens) -> str:
    """Assina um ticket para este usuário e este recorte."""
    agora = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": usuario["username"],
            "tver": usuario["token_version"],
            "escopo": ESCOPO,
            "rec": assinatura_do_recorte(itens),
            "iat": int(agora.timestamp()),
            "exp": int((agora + timedelta(seconds=VALIDO_POR_SEGUNDOS)).timestamp()),
        },
        JWT_SECRET,
        algorithm=JWT_ALG,
    )


def abrir(ticket: str, itens) -> dict:
    """Valida o ticket contra o recorte que está sendo pedido.

    Devolve o payload (com `sub` e `tver`, para quem chama conferir o usuário no
    banco). Não toca no banco de propósito: aqui é só a parte criptográfica.
    """
    try:
        payload = jwt.decode(ticket, JWT_SECRET, algorithms=[JWT_ALG])
    except jwt.ExpiredSignatureError:
        raise TicketInvalido(
            "o link do download expirou (ele vale um minuto). Clique em baixar "
            "de novo na tela."
        ) from None
    except jwt.PyJWTError:
        raise TicketInvalido("link de download inválido.") from None

    if payload.get("escopo") != ESCOPO:
        raise TicketInvalido("este token não serve para baixar a volumetria.")
    if payload.get("rec") != assinatura_do_recorte(itens):
        raise TicketInvalido(
            "o link do download não corresponde ao recorte pedido. Clique em "
            "baixar de novo na tela, sem editar a URL."
        )
    if not payload.get("sub"):
        raise TicketInvalido("link de download inválido.")
    return payload
