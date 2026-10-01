"""As quatro ferramentas que o modelo pode chamar, e o executor que as protege.

| Ferramenta | O que faz |
|---|---|
| `listar_capacidades` | o que o domínio da conversa sabe responder |
| `descrever` | métricas, filtros, limitações, o que **não** se responde, exemplos |
| `consultar_indicador` | UMA consulta ao indicador, pelo adaptador do domínio |
| `amostrar_valores` | valores válidos de uma dimensão (unidade, cliente...), **por rótulo** |

O modelo não escreve SQL, não escolhe tabela e não recebe chave de cliente. Cada
ferramenta devolve `dict` já pronto: o número vem calculado pelo Hub.

## O executor aplica, nesta ordem

1. um **passo** a mais no contador da pergunta (corta modelo em laço);
2. o domínio pedido tem que ser o **da conversa** — trocar de domínio por dentro
   de uma ferramenta é recusado e auditado (`ia.bloqueio`);
3. em `consultar_indicador`, a **chamada lógica** é contada antes de validar
   qualquer parâmetro: tentativa recusada também gasta (DD-24);
4. o resultado, o erro ou o estouro de limite viram um registro para `ia_consultas`,
   sem linhas de dado e sem a chave do cliente.

`ErroDeFerramenta` volta ao modelo como resultado (`{"erro": ...}`) e a pergunta
segue. `EncerrarPergunta` sobe até o orquestrador e termina a pergunta.
"""
import importlib
import time

from backend.ia import dominios
from backend.ia.politicas import ContextoDaPergunta, EncerrarPergunta, ErroDeFerramenta

_PARAMETROS_DA_CONSULTA = {
    "type": "object",
    "description": "Parâmetros da consulta. Só os campos abaixo existem.",
    "properties": {
        "de": {"type": "string", "description": "Primeiro dia, AAAA-MM-DD (inclusivo)."},
        "ate": {"type": "string", "description": "Último dia, AAAA-MM-DD (inclusivo)."},
        "movimento": {"type": "string", "enum": ["rec", "exp", "amb"],
                      "description": "rec = entrada; exp = saída; amb = entrada + saída somadas."},
        "lente": {"type": "string", "enum": ["liq", "bru", "pal", "vol", "val"],
                  "description": "Medida. Padrão liq (peso líquido). pal só existe na entrada."},
        "faixa": {"type": "string", "enum": ["solicitado", "atendido", "separado"],
                  "description": "Só para saída e entrada + saída. Se omitida, o Hub usa 'atendido'."},
        "unidades": {"type": "array", "items": {"type": "string"},
                     "description": "Siglas de unidade (use amostrar_valores se tiver dúvida)."},
        "clientes": {"type": "array", "items": {"type": "string"},
                     "description": "NOMES de cliente. O Hub resolve; se for ambíguo, devolve candidatos."},
        "tipos_estoque": {"type": "array", "items": {"type": "string"}},
        "operacoes": {"type": "array", "items": {"type": "string"},
                      "description": "Tipos de operação. Não vale em movimento amb."},
        "dias": {"type": "array", "items": {"type": "integer"}, "description": "Dia do MÊS, 1 a 31."},
        "detalhe": {"type": "string", "enum": ["total", "unidade", "cliente", "faixa"],
                    "description": ("total (padrão); unidade = ranking de unidades; cliente = ranking de "
                                    "clientes de UMA unidade; faixa = as 3 faixas de UM cliente de UMA unidade.")},
        "limite": {"type": "integer", "description": "Itens do ranking. Padrão 10, máximo 20."},
        "derivacao": {
            "type": "object",
            "description": "Variação percentual entre dois meses; o Hub faz a conta.",
            "properties": {
                "tipo": {"type": "string", "enum": ["variacao_percentual"]},
                "mes_base": {"type": "string", "description": "AAAA-MM"},
                "mes_atual": {"type": "string", "description": "AAAA-MM"},
                "base": {"type": "string",
                         "enum": ["mes_incompleto_vs_inteiro", "mesmos_dias", "so_meses_completos"],
                         "description": "Só depois que o usuário escolher, se houver mês incompleto."},
            },
            "required": ["tipo", "mes_base", "mes_atual"],
        },
    },
    "required": ["movimento"],
}

ESQUEMAS = [
    {"nome": "listar_capacidades",
     "descricao": "Lista o que o domínio desta conversa sabe responder.",
     "parametros": {"type": "object", "properties": {}, "required": []}},
    {"nome": "descrever",
     "descricao": ("Descreve o domínio: medidas, filtros, limitações, o que não é respondido e exemplos. "
                   "Chame antes de recusar uma pergunta, para explicar o porquê."),
     "parametros": {"type": "object", "properties": {"dominio": {"type": "string"}}, "required": ["dominio"]}},
    {"nome": "consultar_indicador",
     "descricao": ("Executa UMA consulta ao indicador do domínio. Devolve números já calculados e prontos "
                   "para citar; não some, não divida, não ordene, não converta. Máximo de 3 consultas "
                   "por pergunta."),
     "parametros": {"type": "object",
                    "properties": {"dominio": {"type": "string"}, "parametros": _PARAMETROS_DA_CONSULTA},
                    "required": ["dominio", "parametros"]}},
    {"nome": "amostrar_valores",
     "descricao": "Valores válidos de uma dimensão que casam com o termo, por rótulo.",
     "parametros": {"type": "object",
                    "properties": {"dominio": {"type": "string"},
                                   "dimensao": {"type": "string",
                                                "enum": ["unidade", "cliente", "tipo_estoque", "operacao"]},
                                   "termo": {"type": "string"}},
                    "required": ["dominio", "dimensao", "termo"]}},
]

NOMES = frozenset(e["nome"] for e in ESQUEMAS)


def _adaptador(dominio):
    return importlib.import_module(f"backend.ia.adaptadores.{dominio.adaptador}")


def _bloqueio(ctx: ContextoDaPergunta, motivo: str, **detalhe) -> dict:
    ctx.bloqueios.append({"motivo": motivo, **detalhe})
    return {"erro": motivo}


def _snapshot(ctx: ContextoDaPergunta) -> tuple:
    return (ctx.chamadas_servico, ctx.paginas_lidas, ctx.consultas_dw)


def _registro(ctx, inicio, *, situacao, motivo=None, parametros=None, linhas=None) -> dict:
    """Uma linha de `ia_consultas`: o que foi feito de fato nesta consulta. Sem
    linhas de dado; parâmetros só quando a consulta foi aceita (já em rótulos).

    O trabalho é medido desde o fim do registro anterior (`ctx.marca`), então a
    leitura de opções feita por `amostrar_valores` ou `descrever` antes da consulta
    entra na conta dela: a soma dos registros bate com as conexões que o DW viu."""
    antes = ctx.marca
    ctx.marca = _snapshot(ctx)
    return {
        "capacidade": "matriz",
        "parametros": parametros if parametros is not None else {"recusado": True},
        "situacao": situacao,
        "motivo": motivo,
        "linhas": linhas,
        "duracao_ms": int((time.perf_counter() - inicio) * 1000),
        "chamadas_logicas": 1,
        "chamadas_servico": ctx.chamadas_servico - antes[0],
        "paginas_lidas": ctx.paginas_lidas - antes[1],
        "consultas_dw": ctx.consultas_dw - antes[2],
        "limite_interno_atingido": int(ctx.limite_interno_atingido),
    }


def executar(nome: str, argumentos: dict, ctx: ContextoDaPergunta) -> dict:
    """Executa uma ferramenta pedida pelo modelo. Nunca levanta `ErroDeFerramenta`;
    pode levantar `EncerrarPergunta`, que o orquestrador trata."""
    ctx.novo_passo()
    if nome not in NOMES:
        return _bloqueio(ctx, "ferramenta_desconhecida", ferramenta=str(nome)[:60])
    if not isinstance(argumentos, dict):
        return {"erro": "parametro_invalido", "mensagem": "os argumentos precisam ser um objeto"}

    if nome == "listar_capacidades":
        dominio = dominios.obter(ctx.dominio)
        return {"dominio": dominio.slug, "nome": dominio.nome,
                "capacidades": [{"nome": c["nome"], "descricao": c.get("descricao", "").strip()}
                                for c in dominio["capacidades"]]}

    pedido = argumentos.get("dominio")
    if pedido != ctx.dominio:
        # P5: mudança de domínio por dentro da ferramenta. A conversa tem um domínio só.
        return _bloqueio(ctx, "dominio_fora_da_conversa", pedido=str(pedido)[:60])
    dominio = dominios.obter(ctx.dominio)
    adaptador = _adaptador(dominio)

    if nome == "descrever":
        return adaptador.descrever(dominio, ctx)

    try:
        if nome == "amostrar_valores":
            return adaptador.amostrar_valores(
                dominio, str(argumentos.get("dimensao", "")), str(argumentos.get("termo", "")), ctx)

        # consultar_indicador: a chamada lógica é contada ANTES de validar
        inicio = time.perf_counter()
        parametros = argumentos.get("parametros")
        try:
            ctx.nova_consulta_logica((dominio.get("limites") or {}).get("consultas_por_pergunta"))
            resultado = adaptador.consultar(dominio, parametros, ctx)
        except ErroDeFerramenta as erro:
            ctx.registros.append(_registro(ctx, inicio, situacao="bloqueio", motivo=erro.codigo))
            raise
        except EncerrarPergunta as fim:
            ctx.registros.append(_registro(
                ctx, inicio, situacao="erro" if fim.motivo == "indisponivel" else "bloqueio", motivo=fim.motivo))
            raise
        ctx.resultados.append(resultado)
        ctx.registros.append(_registro(
            ctx, inicio, situacao="ok",
            parametros=resultado["parametros_registro"], linhas=resultado["linhas"]))
        return resultado["modelo"]
    except ErroDeFerramenta as erro:
        return erro.como_dict()
