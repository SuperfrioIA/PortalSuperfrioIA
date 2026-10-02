"""Configuração do SuperfrioIA: a chave `IA_HABILITADO` e os limites.

## Por que tudo é lido a cada chamada

`habilitado()` e os limites leem o ambiente **na hora**, não no import. Foi
decidido (DD-27) que a chave desligada esconde o card e faz as rotas responderem
404, e que isso é provado **ligando e desligando no mesmo processo**. Um valor
congelado no import tornaria o teste impossível e obrigaria um restart até para
desligar numa emergência de verdade (o restart continua sendo o procedimento
documentado, mas não é mais a única forma).

## Limites (DD-16, DD-24, DD-25, DD-28)

Os valores abaixo são o padrão; cada um pode ser trocado por variável de
ambiente sem mexer em código. Valor inválido (não numérico, zero, negativo) cai
no padrão em vez de derrubar a tela. O contrato do domínio (`dominios/*.yaml`)
só pode **apertar** o limite de consultas por pergunta, nunca afrouxar.
"""
import os

SLUG_APP = "superfrioia"

# Teto de linhas do ranking que o modelo recebe (DD-28: N = 10, teto 20). O teto
# não é configurável: é regra de produto, não ajuste de operação.
TOP_N_PADRAO = 10
TOP_N_TETO = 20

_VERDADEIROS = {"1", "true", "yes", "sim", "on"}


def habilitado() -> bool:
    """A chave mestra. Padrão **desligada**: o deploy do código não expõe nada."""
    return os.environ.get("IA_HABILITADO", "false").strip().lower() in _VERDADEIROS


def _inteiro(nome: str, padrao: int) -> int:
    try:
        valor = int(os.environ[nome])
    except (KeyError, ValueError):
        return padrao
    return valor if valor > 0 else padrao


def provedor_nome() -> str:
    return os.environ.get("IA_PROVEDOR", "falso").strip().lower() or "falso"


def cota_diaria() -> int:
    """Perguntas por usuário por dia (DD-24)."""
    return _inteiro("IA_COTA_DIA", 30)


def tamanho_maximo_da_pergunta() -> int:
    """Caracteres (DD-24)."""
    return _inteiro("IA_TAM_PERGUNTA", 1000)


def max_consultas_por_pergunta() -> int:
    """Chamadas **lógicas** ao indicador pedidas pelo modelo (DD-16, DD-24)."""
    return _inteiro("IA_MAX_CONSULTAS", 3)


def max_operacoes_dw_por_pergunta() -> int:
    """Limite **independente** do trabalho interno: chamadas efetivas ao serviço
    da volumetria (cada uma abre uma conexão ao DW e confere o contrato). Uma
    pergunta de uma só chamada lógica pode, por exemplo, varrer várias páginas
    de um ranking (DD-24, A-5). Padrão 12 = 3 consultas x 4 páginas."""
    return _inteiro("IA_MAX_OPERACOES_DW", 12)


def max_paginas_por_varredura() -> int:
    """Páginas de unidades lidas por um ranking (A-5). 5 páginas = 60 unidades."""
    return _inteiro("IA_MAX_PAGINAS", 5)


def max_passos_do_provedor() -> int:
    """Execuções de ferramenta por pergunta, de qualquer tipo. Corta um modelo
    que fica em laço mesmo sem estourar as consultas."""
    return _inteiro("IA_MAX_PASSOS", 8)


def retencao_mensagens_dias() -> int:
    """DD-25: mensagens por 90 dias."""
    return _inteiro("IA_RETENCAO_MENSAGENS_DIAS", 90)


def retencao_consultas_dias() -> int:
    """DD-25: metadados de consultas por 180 dias."""
    return _inteiro("IA_RETENCAO_CONSULTAS_DIAS", 180)


def validade_concessao_dias() -> int:
    """D-20: validade padrão da concessão, 180 dias."""
    return _inteiro("IA_VALIDADE_CONCESSAO_DIAS", 180)


# ----------------------------------------------------------- provedor (Lote 3)
# Nada aqui tem valor "de produção" embutido: modelo, tempos e preços são ajuste de
# operação (DD-30 / T-29+). Preço e câmbio NÃO têm padrão de propósito: um valor
# inventado viraria "custo medido" no relatório. Sem preço, os tokens são medidos e o
# custo sai como "não calculado".

def _numero(nome: str, padrao: float | None, *, minimo: float = 0.0) -> float | None:
    try:
        valor = float(os.environ[nome].replace(",", "."))
    except (KeyError, ValueError):
        return padrao
    return valor if valor > minimo else padrao


def modelo() -> str:
    """D-2: Sonnet 5.5, configurável (`IA_MODELO`)."""
    return os.environ.get("IA_MODELO", "").strip() or "claude-sonnet-5-5"


def anthropic_api_key() -> str | None:
    """A chave só é lida aqui, na hora de criar o cliente. Nunca vai a log, a erro, a
    resposta da API ou à trilha."""
    return os.environ.get("ANTHROPIC_API_KEY", "").strip() or None


def timeout_do_provedor_s() -> float:
    """Tempo máximo de UMA tentativa HTTP ao modelo (o SDK refaz até `IA_TENTATIVAS` vezes)."""
    return _numero("IA_TIMEOUT_S", 30.0, minimo=0.0)


def prazo_da_pergunta_s() -> float:
    """Prazo da pergunta inteira no provedor. É conferido ANTES de cada rodada, e cada chamada
    nunca pede mais tempo do que o que resta dele; mas uma chamada que já começou pode passar
    do prazo em até `IA_TIMEOUT_S` x (`IA_TENTATIVAS` + 1), mais a espera entre tentativas.
    O padrão (55 s) fica abaixo do tempo ocioso padrão do balanceador (60 s): uma pergunta que
    demora mais do que isso termina neutra no Hub em vez de dar 504 enquanto o servidor segue
    gastando. Confirmar o tempo do balanceador real antes do piloto (runbook)."""
    return _numero("IA_PRAZO_PERGUNTA_S", 55.0, minimo=0.0)


def tentativas_do_provedor() -> int:
    """Novas tentativas do SDK em 429, 5xx e falha de conexão (0 desliga)."""
    try:
        valor = int(os.environ["IA_TENTATIVAS"])
    except (KeyError, ValueError):
        return 2
    return valor if 0 <= valor <= 5 else 2


def max_tokens_de_saida() -> int:
    return _inteiro("IA_MAX_TOKENS_SAIDA", 1024)


def esforco() -> str | None:
    """`low`... `max` (D-2 sugere low/medium para chat). Sem padrão: o parâmetro só vai
    na requisição se for configurado, para a primeira rodada real não quebrar por um
    parâmetro que o modelo possa recusar."""
    valor = os.environ.get("IA_ESFORCO", "").strip().lower()
    return valor if valor in {"low", "medium", "high", "xhigh", "max"} else None


def inference_geo() -> str | None:
    """Região de processamento pedida ao provedor (D-1). Sem padrão: valor e
    disponibilidade dependem do contrato da conta; o dossiê registra o que valer."""
    return os.environ.get("IA_INFERENCE_GEO", "").strip() or None


def reparos_do_verificador() -> int:
    """Quantas vezes o modelo pode reescrever um texto que o verificador de números
    reprovou, antes de a resposta ser retida (T-31)."""
    try:
        valor = int(os.environ["IA_REPAROS"])
    except (KeyError, ValueError):
        return 1
    return valor if 0 <= valor <= 3 else 1


def precos() -> dict:
    """Preço por milhão de tokens (USD) e câmbio, para estimar o custo por pergunta.
    Valores `None` = não configurado = custo não calculado."""
    return {
        "entrada": _numero("IA_PRECO_ENTRADA_USD_MTOK", None),
        "saida": _numero("IA_PRECO_SAIDA_USD_MTOK", None),
        "cache_leitura": _numero("IA_PRECO_CACHE_LEITURA_USD_MTOK", None),
        "cache_escrita": _numero("IA_PRECO_CACHE_ESCRITA_USD_MTOK", None),
        "cambio_brl": _numero("IA_CAMBIO_USD_BRL", None),
    }


# ----------------------------------------------------- endurecimento (Lote 4)
def max_simultaneas() -> int:
    """Perguntas em andamento por usuário (no mesmo processo). LIMITA a corrida da cota diária
    (ela pode passar em até `valor - 1` perguntas, não em N) e a rajada de custo de um script em
    laço (T-42). Por processo: com mais de um worker o teto multiplica."""
    return _inteiro("IA_MAX_SIMULTANEAS", 2)


def limite_de_execucao_dw_s() -> float:
    """Prazo de execução de CADA chamada ao DW feita pela IA (`call_timeout`). As consultas da
    Volumetria medidas levam de 0,1 a 1,3 s; 20 s é folga larga que ainda corta uma consulta
    pendurada. Só vale para a IA: a tela não tem esse limite."""
    return _numero("IA_DW_TIMEOUT_S", 20.0, minimo=0.0)


def tamanho_maximo_do_resultado() -> int:
    """Caracteres do resultado de UMA ferramenta enviado ao modelo. Acima disso o modelo
    recebe um erro pedindo recorte menor, em vez de um resultado que estoura o contexto e
    o custo (T-43). Hoje um ranking de 20 itens com 12 meses tem ~6 mil; a margem é larga."""
    return _inteiro("IA_TAM_RESULTADO", 20000)


def avisos_de_ativacao() -> list[str]:
    """Combinações que o Hub deixa subir mas que o piloto não admite. O boot registra cada
    uma como WARNING; não derrubam a subida (a chave mestra desliga tudo e continua sendo o
    caminho de emergência). Só olham configuração: nunca leem nem mostram a chave."""
    if not habilitado():
        return []
    avisos = []
    nome = provedor_nome()
    if nome != "falso" and autoaprovacao_permitida():
        avisos.append("IA_AUTOAPROVACAO está ligada com provedor real: a autoaprovação é proibida antes "
                      "do piloto (DD-13). Defina IA_AUTOAPROVACAO=false.")
    if nome == "anthropic" and not anthropic_api_key():
        avisos.append("IA_PROVEDOR=anthropic sem ANTHROPIC_API_KEY: toda pergunta vai responder a mensagem neutra.")
    if nome == "falso" and os.environ.get("SUPERFRIO_ENV", "dev").strip().lower() == "prod":
        avisos.append("provedor de teste (falso) com a chave mestra ligada em produção: as respostas não são de modelo.")
    return avisos


def registrar_avisos_de_ativacao() -> list[str]:
    """Registra cada aviso como WARNING (é o que o boot chama). Devolve a lista, para o teste."""
    import logging

    avisos = avisos_de_ativacao()
    for aviso in avisos:
        logging.getLogger("backend.ia").warning("SuperfrioIA: %s", aviso)
    return avisos


def autoaprovacao_permitida() -> bool:
    """DD-13: permitida durante a PoC (o evento sai marcado `autoaprovacao`),
    **proibida antes do piloto**. Para proibir: `IA_AUTOAPROVACAO=false`."""
    return os.environ.get("IA_AUTOAPROVACAO", "true").strip().lower() in _VERDADEIROS
