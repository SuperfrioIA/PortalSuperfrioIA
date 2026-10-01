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


def autoaprovacao_permitida() -> bool:
    """DD-13: permitida durante a PoC (o evento sai marcado `autoaprovacao`),
    **proibida antes do piloto**. Para proibir: `IA_AUTOAPROVACAO=false`."""
    return os.environ.get("IA_AUTOAPROVACAO", "true").strip().lower() in _VERDADEIROS
