"""Adaptador da Volumetria de Catering (modo A: indicador pronto).

Traduz o que o modelo pede em `service.matriz(filtros)` — **a mesma função que a
tela chama** (DD-9) — e devolve o número que voltou, nunca outro. O que este
adaptador faz além de chamar:

- **valida** cada parâmetro contra o contrato antes de tocar no serviço;
- **resolve nomes para chaves no servidor** (DD-17): o modelo passa o nome do
  cliente, o Hub acha a chave; nome ambíguo volta como erro com candidatos **por
  rótulo**. A chave (raiz do CNPJ) nunca entra num resultado de ferramenta;
- aplica a **faixa padrão `atendido`** (DD-15) quando a pergunta é de saída;
- lê **todas as páginas de unidades** quando precisa ranquear, dentro do limite
  de varredura (DD-20, DD-24);
- calcula tudo que é conta pelas **derivações** (`derivacoes.py`): total do período,
  ranking, variação %, kg -> t. O modelo recebe os valores já prontos;
- monta os **blocos** que a tela exibe, a partir do mesmo resultado que o modelo
  recebeu: o que está na tela é, por construção, o que a ferramenta devolveu.
"""
import calendar
import html
import re
import unicodedata
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from backend.ia import config, derivacoes
from backend.ia.dominios import ContratoInvalido
from backend.ia.politicas import EncerrarPergunta, ErroDeFerramenta
from backend.volumetria_catering import contrato, recorte, service

SLUG = "volumetria-catering"

PARAMETROS = frozenset({
    "de", "ate", "movimento", "lente", "faixa", "unidades", "clientes",
    "tipos_estoque", "operacoes", "dias", "detalhe", "limite", "derivacao",
})
DETALHES = ("total", "unidade", "cliente", "faixa")
DIMENSOES = ("unidade", "cliente", "tipo_estoque", "operacao")

# 4 anos de colunas mensais. O dado existe desde 2023; mais que isso é leitura
# que ninguém faz numa conversa e que incharia o resultado da ferramenta.
MAX_MESES = 48
MAX_CANDIDATOS = 10

# O DW pode ter uma raiz de CNPJ sem razão social: `Dimensoes.rotulo_cliente` cai
# então para a PRÓPRIA raiz, e o "rótulo" passaria a ser a chave do cliente (DD-17).
# Este adaptador nunca devolve um rótulo que seja a chave ou só dígitos.
SEM_NOME = "(cliente sem nome cadastrado)"
_SO_NUMEROS = re.compile(r"^[\d.\-/\s]+$")


def _rotulo_seguro(rotulo, chave) -> str:
    texto = str(rotulo or "").strip()
    if not texto or texto == str(chave) or _SO_NUMEROS.match(texto):
        return SEM_NOME
    return texto


def _clientes_seguros(opcoes: dict) -> list[tuple[str, str]]:
    """`[(chave, rótulo seguro)]` dos clientes de `opcoes()`."""
    return [(c["chave"], _rotulo_seguro(c["rotulo"], c["chave"])) for c in opcoes["clientes"]]

ESCOPO_APLICADO = "integral (indicador sem alcance por usuário)"
MENSAGEM_INDISPONIVEL = (
    "Não consegui consultar os dados agora. A fonte deste domínio não respondeu; "
    "o restante do Hub continua funcionando. Tente novamente em instantes."
)

_MES = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_SO_DIGITOS = re.compile(r"^[\d.\-/\s]{8,}$")
_ROTULO_MOVIMENTO = {"rec": "Entrada", "exp": "Saída", "amb": "Entrada + saída"}


# ===================================================================== contrato
def validar_contrato(dados: dict, origem: str) -> None:
    """Confere o YAML contra o código real: o que não existe lá não vale aqui."""

    def exigir(condicao, mensagem):
        if not condicao:
            raise ContratoInvalido(f"contrato {origem}: {mensagem}")

    exigir(dados["app_hub"] == SLUG, f"app_hub {dados['app_hub']!r} diverge do adaptador ({SLUG!r})")

    # métricas = as lentes do contrato do módulo, com a mesma unidade e o mesmo nome
    metricas = dados["metricas"]
    exigir(set(metricas) == set(contrato.LENTES),
           f"metricas {sorted(metricas)} diverge das lentes do módulo {sorted(contrato.LENTES)}")
    for chave, lente in contrato.LENTES.items():
        m = metricas[chave]
        exigir(m.get("nome") == lente["nome"],
               f"metrica {chave!r}: nome {m.get('nome')!r} diverge de {lente['nome']!r}")
        exigir(m.get("exibicao") == lente["unidade"],
               f"metrica {chave!r}: exibicao {m.get('exibicao')!r} diverge de {lente['unidade']!r}")
        exigir(bool(m.get("so_entrada", False)) == (lente["exp"] is None),
               f"metrica {chave!r}: so_entrada diverge do módulo (pallet só existe na entrada)")
    exigir(dados.get("metrica_padrao", "liq") in contrato.LENTES,
           f"metrica_padrao {dados.get('metrica_padrao')!r} não é uma lente")

    exigir(set(dados.get("faixas", {})) == set(contrato.FAIXAS),
           f"faixas {sorted(dados.get('faixas', {}))} diverge de {sorted(contrato.FAIXAS)}")

    regras = dados.get("regras", {})
    exigir(set(regras.get("movimentos", [])) == set(recorte.MOVIMENTOS_DA_TELA),
           f"regras.movimentos {regras.get('movimentos')} diverge de {list(recorte.MOVIMENTOS_DA_TELA)}")
    campos_do_filtro = {"de", "ate"} | {
        f for f in recorte.Filtros.__dataclass_fields__ if f not in ("pagina", "de", "ate")
    }
    desconhecidos = set(regras.get("filtros_permitidos", [])) - campos_do_filtro
    exigir(not desconhecidos, f"regras.filtros_permitidos tem campo que Filtros não tem: {sorted(desconhecidos)}")
    exigir(regras.get("faixa_padrao") in contrato.FAIXAS,
           f"regras.faixa_padrao {regras.get('faixa_padrao')!r} não é uma faixa")
    exigir(set(regras.get("detalhes_permitidos", [])) <= set(DETALHES),
           f"regras.detalhes_permitidos fora de {list(DETALHES)}")
    top = regras.get("top_n", {})
    exigir(isinstance(top.get("padrao"), int) and isinstance(top.get("teto"), int)
           and 1 <= top["padrao"] <= top["teto"] <= config.TOP_N_TETO,
           f"regras.top_n precisa ter 1 <= padrao <= teto <= {config.TOP_N_TETO}")

    for capacidade in dados["capacidades"]:
        nome_da_funcao = capacidade["funcao"].removeprefix("service.")
        exigir(capacidade["funcao"].startswith("service.") and callable(getattr(service, nome_da_funcao, None)),
               f"capacidade {capacidade['nome']!r}: a função {capacidade['funcao']!r} não existe no serviço")
    exigir(dados.get("fonte", {}).get("modulo") == "backend.volumetria_catering.service",
           "fonte.modulo diverge do serviço que o adaptador chama")


def hoje() -> date:
    """"Hoje" no fuso de exibição do módulo, sem abrir conexão ao DW."""
    return service.hoje()


# =================================================================== descrição
def descrever(dominio, ctx) -> dict:
    """O que o modelo pode saber do domínio. Sem nome de função, caminho de
    arquivo, responsável ou qualquer coisa interna. Traz também o período que
    existe no dado e o frescor, para a IA responder "o dado está atualizado?" —
    se a fonte estiver fora, a descrição sai sem esse bloco (recusar uma pergunta
    não pode depender do DW)."""
    d = dominio.dados
    dados = None
    try:
        opcoes = ctx.opcoes(service.opcoes)
        dados = {"periodo": opcoes["periodo"],
                 "atualizado_ate": {m: _hora_br(v) for m, v in opcoes["atualizado_ate"].items()}}
    except service.VolumetriaIndisponivel:
        pass
    return {
        "dados_disponiveis": dados,
        "dominio": dominio.slug,
        "nome": dominio.nome,
        "area": d.get("area"),
        "grao": d["regras"]["grao"],
        "movimentos": {"rec": "Entrada (recebimento)", "exp": "Saída (expedição)",
                       "amb": "Entrada + saída somadas (movimentação)"},
        "medidas": {k: {"nome": v["nome"], "unidade_exibida": v["exibicao"],
                        "so_na_entrada": bool(v.get("so_entrada", False))}
                    for k, v in d["metricas"].items()},
        "medida_padrao": d.get("metrica_padrao", "liq"),
        "faixas_da_saida": d["faixas"],
        "faixa_padrao": {"valor": d["regras"]["faixa_padrao"],
                         "dizer": d["regras"]["faixa_padrao_dizer"],
                         "nao_e": d["regras"]["faixa_padrao_nao_e"]},
        "parametros": sorted(PARAMETROS),
        "detalhes": list(d["regras"]["detalhes_permitidos"]),
        "top_n": d["regras"]["top_n"],
        "limitacoes": d.get("limitacoes", []),
        "nao_responde": d["nao_atendidas"],
        "sinonimos": d.get("sinonimos", {}),
        "exemplos": d["exemplos"],
        "regra_de_ouro": ("Repita somente os números que a ferramenta devolveu; não some, "
                          "não divida, não ordene, não converta unidade."),
    }


# ================================================================ normalização
def _norm(texto) -> str:
    sem_acento = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", sem_acento.lower())).strip()


def _candidatos(termo: str, rotulos: list[str]) -> list[str]:
    """Exato (normalizado) vence; senão, quem contém o termo."""
    alvo = _norm(termo)
    if not alvo:
        return []
    exatos = [r for r in rotulos if _norm(r) == alvo]
    return exatos or [r for r in rotulos if alvo in _norm(r)]


def _sem_identificador(valores: list, nome: str) -> None:
    for v in valores:
        if _SO_DIGITOS.match(str(v)):
            raise ErroDeFerramenta(
                "identificador_nao_aceito",
                f"{nome}: informe o nome, não um número de identificação. O Hub resolve o resto.",
            )


# ================================================================ dimensões
def amostrar_valores(dominio, dimensao: str, termo: str, ctx) -> dict:
    """Valores válidos de uma dimensão, **só por rótulo** (nunca a chave do cliente)."""
    if dimensao not in DIMENSOES:
        raise ErroDeFerramenta("dimensao_invalida", f"dimensão fora do contrato: {dimensao!r}",
                               dimensoes_validas=list(DIMENSOES))
    opcoes = _opcoes(ctx)
    if dimensao == "unidade":
        universo = list(opcoes["unidades"])
    elif dimensao == "cliente":
        universo = sorted({rotulo for _chave, rotulo in _clientes_seguros(opcoes)})
    elif dimensao == "tipo_estoque":
        universo = list(opcoes["tipos_estoque"])
    else:
        achados = {mov: _filtrar(termo, lista) for mov, lista in opcoes["operacoes"].items()}
        return {"dimensao": dimensao, "termo": termo,
                "valores_por_movimento": {m: v[:MAX_CANDIDATOS] for m, v in achados.items()},
                "truncado": any(len(v) > MAX_CANDIDATOS for v in achados.values())}
    achados = _filtrar(termo, universo)
    return {"dimensao": dimensao, "termo": termo, "valores": achados[:MAX_CANDIDATOS],
            "total_encontrado": len(achados), "truncado": len(achados) > MAX_CANDIDATOS}


def _filtrar(termo: str, universo: list[str]) -> list[str]:
    return sorted(_candidatos(termo, universo) if _norm(termo) else universo, key=str.casefold)


def _com_prazo(funcao):
    """A mesma função do serviço, mas com prazo de EXECUÇÃO no DW (`IA_DW_TIMEOUT_S`): uma
    consulta que não volta termina a pergunta como 'fonte indisponível' em vez de segurar a
    thread e a vaga do usuário. O prazo vale só para a IA; a tela não passa por aqui."""
    def chamar(*args, **kwargs):
        with service.com_limite_de_execucao(config.limite_de_execucao_dw_s()):
            return funcao(*args, **kwargs)
    return chamar


def _opcoes(ctx) -> dict:
    try:
        return ctx.opcoes(_com_prazo(service.opcoes))
    except service.VolumetriaIndisponivel:
        raise EncerrarPergunta("indisponivel", MENSAGEM_INDISPONIVEL) from None


def _resolver(valores, universo: list[str], nome: str) -> list[str]:
    """Cada valor vira exatamente UM rótulo do universo, ou a pergunta volta com
    candidatos. Ambiguidade nunca é resolvida por chute."""
    if not isinstance(valores, list) or not all(isinstance(v, str) and v.strip() for v in valores):
        raise ErroDeFerramenta("parametro_invalido", f"{nome}: precisa ser uma lista de textos")
    _sem_identificador(valores, nome)
    saida = []
    for valor in valores:
        achados = _candidatos(valor, universo)
        if len(achados) == 1:
            saida.append(achados[0])
        elif not achados:
            raise ErroDeFerramenta(
                "nao_encontrado", f"{nome}: não encontrei {valor!r}.",
                parecidos=sorted(universo, key=str.casefold)[:MAX_CANDIDATOS])
        else:
            raise ErroDeFerramenta(
                "ambiguo",
                f"{nome}: {valor!r} corresponde a mais de uma opção. Peça ao usuário para escolher.",
                candidatos=sorted(achados, key=str.casefold)[:MAX_CANDIDATOS])
    return saida


# ===================================================================== pedido
@dataclass
class Pedido:
    de: str
    ate: str
    movimento: str
    lente: str
    faixa: str                 # efetiva (default atendido em saída/conjunta)
    unidades: tuple
    clientes_rotulos: tuple
    clientes_chaves: tuple     # só aqui dentro; nunca sai (DD-17)
    tipos_estoque: tuple
    operacoes: tuple
    dias: tuple
    detalhe: str
    limite: int
    derivacao: dict | None


def _mes_ok(valor, nome: str) -> str:
    if not isinstance(valor, str) or not _MES.match(valor):
        raise ErroDeFerramenta("parametro_invalido", f"{nome}: use AAAA-MM, veio {valor!r}")
    return valor


def _primeiro_dia(mes: str) -> str:
    return f"{mes}-01"


def _ultimo_dia_do_mes(mes: str) -> str:
    ano, numero = (int(p) for p in mes.split("-"))
    return f"{mes}-{calendar.monthrange(ano, numero)[1]:02d}"


def _mes_anterior(mes: str) -> str:
    ano, numero = (int(p) for p in mes.split("-"))
    return f"{ano - 1}-12" if numero == 1 else f"{ano}-{numero - 1:02d}"


def _ler_pedido(dominio, parametros, ctx) -> Pedido:
    if not isinstance(parametros, dict):
        raise ErroDeFerramenta("parametro_invalido", "parametros precisa ser um objeto")
    fora = sorted(set(parametros) - PARAMETROS)
    if fora:
        raise ErroDeFerramenta(
            "parametro_invalido",
            f"parâmetro fora do contrato: {', '.join(fora)}", parametros_validos=sorted(PARAMETROS))

    regras = dominio["regras"]
    derivacao = parametros.get("derivacao")
    if derivacao is not None:
        if not isinstance(derivacao, dict) or derivacao.get("tipo") != "variacao_percentual":
            raise ErroDeFerramenta(
                "parametro_invalido",
                "derivacao.tipo precisa ser 'variacao_percentual' (a soma do período já vem no resultado)")
        if parametros.get("detalhe") not in (None, "total"):
            raise ErroDeFerramenta("parametro_invalido", "variação percentual não combina com detalhe")
        _mes_ok(derivacao.get("mes_base"), "derivacao.mes_base")
        _mes_ok(derivacao.get("mes_atual"), "derivacao.mes_atual")
        if derivacao["mes_base"] == derivacao["mes_atual"]:
            raise ErroDeFerramenta("parametro_invalido", "a variação compara dois meses diferentes")
        extras = set(derivacao) - {"tipo", "mes_base", "mes_atual", "base"}
        if extras:
            raise ErroDeFerramenta("parametro_invalido", f"derivacao: campo fora do contrato: {sorted(extras)}")
        meses = sorted([derivacao["mes_base"], derivacao["mes_atual"]])
        # o mesmo teto do período livre: dois meses distantes montariam todas as colunas entre eles
        (a1, m1), (a2, m2) = ((int(x) for x in m.split("-")) for m in meses)
        if (a2 - a1) * 12 + (m2 - m1) + 1 > MAX_MESES:
            raise ErroDeFerramenta(
                "periodo_longo", f"a comparação abrangeria mais de {MAX_MESES} meses; escolha meses mais próximos.")
        de, ate = _primeiro_dia(meses[0]), _ultimo_dia_do_mes(meses[1])
    else:
        de, ate = parametros.get("de"), parametros.get("ate")
        if not de or not ate:
            raise ErroDeFerramenta("parametro_invalido", "de e ate são obrigatórios (AAAA-MM-DD)")

    movimento = parametros.get("movimento")
    if movimento not in recorte.MOVIMENTOS_DA_TELA:
        raise ErroDeFerramenta("parametro_invalido",
                               f"movimento é obrigatório: {list(recorte.MOVIMENTOS_DA_TELA)}")
    lente = parametros.get("lente") or dominio.get("metrica_padrao", "liq")
    if lente not in contrato.LENTES:
        raise ErroDeFerramenta("parametro_invalido", f"lente fora do contrato: {lente!r}",
                               lentes_validas=list(contrato.LENTES))

    faixa = parametros.get("faixa")
    if faixa is not None and faixa not in contrato.FAIXAS:
        raise ErroDeFerramenta("parametro_invalido", f"faixa fora do contrato: {faixa!r}",
                               faixas_validas=list(contrato.FAIXAS))
    if faixa is None:
        # DD-15: "expedido"/"saiu" sem faixa explícita é atendido, dito como tal.
        faixa = regras["faixa_padrao"] if movimento in ("exp", "amb") else "solicitado"

    detalhe = parametros.get("detalhe") or "total"
    if detalhe not in regras["detalhes_permitidos"]:
        raise ErroDeFerramenta("parametro_invalido", f"detalhe fora do contrato: {detalhe!r}",
                               detalhes_validos=list(regras["detalhes_permitidos"]))

    limite = parametros.get("limite", regras["top_n"]["padrao"])
    if isinstance(limite, bool) or not isinstance(limite, int) or not 1 <= limite <= regras["top_n"]["teto"]:
        raise ErroDeFerramenta("parametro_invalido",
                               f"limite precisa ser inteiro entre 1 e {regras['top_n']['teto']}")

    dias = parametros.get("dias", [])
    if not isinstance(dias, list) or not all(isinstance(x, int) and not isinstance(x, bool) for x in dias):
        raise ErroDeFerramenta("parametro_invalido", "dias precisa ser uma lista de inteiros (1 a 31)")

    opcoes = _opcoes(ctx)
    unidades = tuple(_resolver(parametros.get("unidades", []), list(opcoes["unidades"]), "unidades"))
    chaves_por_rotulo: dict[str, list[str]] = {}
    for chave, rotulo in _clientes_seguros(opcoes):
        chaves_por_rotulo.setdefault(rotulo, []).append(chave)
    clientes = tuple(_resolver(parametros.get("clientes", []), list(chaves_por_rotulo), "clientes"))
    for rotulo in clientes:
        if rotulo == SEM_NOME:
            raise ErroDeFerramenta(
                "cliente_sem_nome",
                "clientes: este cliente não tem nome cadastrado e não pode ser consultado por nome.")
        if len(chaves_por_rotulo[rotulo]) > 1:
            # Juntar dois cadastros de mesmo nome seria unir clientes: decisão de negócio
            # que o Hub ainda não tomou (ver `dimensoes_dw`). Recusa em vez de escolher.
            raise ErroDeFerramenta(
                "ambiguo",
                f"clientes: existem {len(chaves_por_rotulo[rotulo])} cadastros com o nome {rotulo!r}; "
                "o Hub não os une. Peça ao usuário para consultar outro recorte.",
                candidatos=[rotulo])
    # (chave, rótulo) na ordem pedida; `chaves_por_rotulo[r]` tem exatamente uma aqui
    tipos = tuple(_resolver(parametros.get("tipos_estoque", []), list(opcoes["tipos_estoque"]), "tipos_estoque"))

    operacoes_pedidas = parametros.get("operacoes", [])
    if operacoes_pedidas and movimento == "amb":
        raise ErroDeFerramenta(
            "parametro_invalido",
            "operacoes não vale em entrada + saída: as duas tabelas têm listas de operação "
            "diferentes. Use movimento rec ou exp.")
    operacoes = tuple(_resolver(operacoes_pedidas, list(opcoes["operacoes"].get(movimento, [])), "operacoes")) \
        if operacoes_pedidas else ()

    # Pré-condições do detalhe: a árvore da Matriz é unidade > cliente > ..., e
    # somar o mesmo cliente entre unidades é agrupamento fora da árvore (DD-10, DD-21).
    if detalhe == "cliente" and len(unidades) != 1:
        raise ErroDeFerramenta(
            "fora_do_contrato",
            "ranking de clientes exige exatamente uma unidade: somar o mesmo cliente entre unidades "
            "não é atendido neste recorte.")
    if detalhe == "faixa" and (movimento != "exp" or len(unidades) != 1 or len(clientes) != 1):
        raise ErroDeFerramenta(
            "fora_do_contrato", "detalhe por faixa exige movimento exp, uma unidade e um cliente.")

    return Pedido(
        de=de, ate=ate, movimento=movimento, lente=lente, faixa=faixa, unidades=unidades,
        clientes_rotulos=clientes, clientes_chaves=tuple(chaves_por_rotulo[c][0] for c in clientes),
        tipos_estoque=tipos, operacoes=operacoes, dias=tuple(dias), detalhe=detalhe,
        limite=limite, derivacao=derivacao,
    )


def _filtros_do(pedido: Pedido, **troca) -> recorte.Filtros:
    campos = dict(
        de=pedido.de, ate=pedido.ate, movimento=pedido.movimento, lente=pedido.lente,
        faixa=pedido.faixa, unidades=pedido.unidades, clientes=pedido.clientes_chaves,
        tipos_estoque=pedido.tipos_estoque, operacoes=pedido.operacoes, dias=pedido.dias,
    )
    campos.update(troca)
    try:
        return service.filtros_de(**campos)
    except recorte.FiltroInvalido as erro:
        raise ErroDeFerramenta(
            "spec_invalido",
            f"Não consegui montar uma consulta segura para essa pergunta ({erro}).") from None


# ================================================================== leitura
def _ler(ctx, filtros: recorte.Filtros, *, todas_as_paginas: bool) -> list[dict]:
    """Chama o serviço, contando cada chamada, e junta as páginas quando preciso."""
    def uma(f):
        ctx.reservar_chamada_ao_servico(movimento=f.movimento, pagina=True)
        try:
            return _com_prazo(service.matriz)(f)
        except service.VolumetriaIndisponivel:
            raise EncerrarPergunta("indisponivel", MENSAGEM_INDISPONIVEL) from None

    primeira = uma(filtros)
    paginas = [primeira]
    if todas_as_paginas:
        total = primeira["paginacao"]["paginas"]
        ctx.recusar_varredura_grande(total)
        for numero in range(2, total + 1):
            paginas.append(uma(replace(filtros, pagina=numero)))
    return paginas


def _atualizado_ate(opcoes: dict, movimento: str) -> date | None:
    movimentos = ("rec", "exp") if movimento == "amb" else (movimento,)
    datas = [datetime.fromisoformat(opcoes["atualizado_ate"][m]).date()
             for m in movimentos if opcoes["atualizado_ate"].get(m)]
    return min(datas) if datas else None


# ================================================================== exibição
def _v(valor: Decimal | None, unidade: str) -> dict:
    e = derivacoes.exibir(valor, unidade)
    if e["exibido"] is None:
        return {"valor": None}
    return {"valor": f"{e['exibido']} {e['unidade_exibida']}",
            "original": f"{e['original']} {e['unidade_original']}"}


def _data_br(iso: str) -> str:
    return f"{iso[8:10]}/{iso[5:7]}/{iso[0:4]}"


def _hora_br(iso: str | None) -> str | None:
    if not iso:
        return None
    d = datetime.fromisoformat(iso)
    return d.strftime("%d/%m/%Y %H:%M")


def _linhas_do_recorte(pedido: Pedido, unidade: str) -> list[str]:
    lente = contrato.LENTES[pedido.lente]
    linhas = [f"período {_data_br(pedido.de)} a {_data_br(pedido.ate)}",
              f"movimento: {_ROTULO_MOVIMENTO[pedido.movimento]}",
              f"medida: {lente['nome']} ({unidade})"]
    if pedido.movimento in ("exp", "amb") and pedido.lente != "pal":
        linhas.append(f"faixa: {recorte.rotulo_faixa(pedido.faixa).lower()}")
    if pedido.unidades:
        linhas.append("unidades: " + ", ".join(pedido.unidades))
    if pedido.clientes_rotulos:
        linhas.append("clientes: " + ", ".join(pedido.clientes_rotulos))
    if pedido.tipos_estoque:
        linhas.append("tipos de estoque: " + ", ".join(pedido.tipos_estoque))
    if pedido.operacoes:
        linhas.append("operações: " + ", ".join(pedido.operacoes))
    if pedido.dias:
        linhas.append("dias do mês: " + ", ".join(str(d) for d in pedido.dias))
    return linhas


def _largura(valor: Decimal | None, maximo: Decimal) -> int:
    """Largura da barra (0-100). Só geometria do gráfico: não é um número que o
    texto cite."""
    if valor is None or maximo <= 0:
        return 0
    return int((valor / maximo * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


# =================================================================== consulta
def consultar(dominio, parametros, ctx) -> dict:
    """Executa UMA consulta ao indicador. Devolve `{modelo, blocos, parametros_registro, linhas}`."""
    pedido = _ler_pedido(dominio, parametros, ctx)
    opcoes = _opcoes(ctx)
    unidade = contrato.LENTES[pedido.lente]["unidade"]
    atualizado = _atualizado_ate(opcoes, pedido.movimento)

    if pedido.derivacao is not None:
        return _variacao(pedido, ctx, opcoes, atualizado, unidade)

    filtros = _filtros_do(pedido)
    meses_pedidos = recorte.meses_do_periodo(pedido.de, pedido.ate)
    if len(meses_pedidos) > MAX_MESES:
        raise ErroDeFerramenta(
            "periodo_longo", f"o período tem {len(meses_pedidos)} meses; o máximo é {MAX_MESES}.")

    paginas = _ler(ctx, filtros, todas_as_paginas=pedido.detalhe == "unidade")
    matriz = paginas[0]
    meses = matriz["meses"]
    parciais = derivacoes.meses_parciais(meses, atualizado, ctx.hoje)

    por_mes = [{"mes": m, "rotulo": r, "parcial": m in parciais,
                **_v(matriz["total"].get(m), unidade)}
               for m, r in zip(meses, matriz["rotulos_meses"])]
    modelo = {
        "dominio": dominio.slug,
        "capacidade": "matriz",
        "recorte": _linhas_do_recorte(pedido, unidade),
        "medida": contrato.LENTES[pedido.lente]["nome"],
        "unidade_exibida": unidade,
        "faixa_usada": _faixa_dita(pedido, dominio) if pedido.movimento in ("exp", "amb") else None,
        "total_por_mes": por_mes,
        "meses_parciais": {m: d for m, d in parciais.items()},
        "avisos": [html.unescape(a) for a in matriz["avisos"]],
        "atualizado_ate": {m: _hora_br(v) for m, v in opcoes["atualizado_ate"].items()},
        "vazio": all(matriz["total"].get(m) is None for m in meses),
        "escopo": ESCOPO_APLICADO,
    }

    periodo = None
    if len(meses) > 1:
        periodo = derivacoes.total_do_periodo(matriz["total"], meses)
        modelo["total_do_periodo"] = {**_v(periodo["total"], unidade),
                                      "meses_sem_dado": periodo["meses_sem_dado"]}

    itens = _detalhar(pedido, dominio, paginas, meses)
    if itens is not None:
        modelo["detalhe"] = pedido.detalhe
        modelo["itens"] = [_item(i, unidade, meses) for i in itens["itens"]]
        modelo["total_itens"] = itens["total_itens"]
        modelo["truncado"] = itens["truncado"]

    blocos = _blocos_da_consulta(pedido, modelo, matriz, periodo, itens, unidade, meses, opcoes)
    return {"modelo": modelo, "blocos": blocos, "linhas": matriz["total_linhas"],
            "parametros_registro": _parametros_registro(pedido)}


def _faixa_dita(pedido: Pedido, dominio) -> str:
    if pedido.faixa == dominio["regras"]["faixa_padrao"]:
        return dominio["regras"]["faixa_padrao_dizer"]
    return recorte.rotulo_faixa(pedido.faixa).lower()


def _item(item: dict, unidade: str, meses: list[str]) -> dict:
    saida = {"posicao": item["posicao"], "rotulo": item["rotulo"],
             "total_do_periodo": _v(item["total"], unidade)}
    if len(meses) <= 12:
        saida["por_mes"] = {m: _v(item["valores"].get(m), unidade)["valor"] for m in meses}
    return saida


def _detalhar(pedido: Pedido, dominio, paginas: list[dict], meses: list[str]) -> dict | None:
    """Nós de um nível, já ordenados e cortados pelo Hub (DD-20)."""
    teto = dominio["regras"]["top_n"]["teto"]
    if pedido.detalhe == "total":
        return None
    if pedido.detalhe == "unidade":
        nos = [n for p in paginas for n in p["linhas"]]
        return derivacoes.ranking(nos, meses=meses, n=pedido.limite, teto=teto)

    unidades = paginas[0]["linhas"]
    no_unidade = unidades[0] if unidades else None
    if no_unidade is None:
        return {"itens": [], "total_itens": 0, "truncado": False}
    if pedido.detalhe == "cliente":
        # o nó do cliente vem com o rótulo que o DW devolveu, que sem razão social é a
        # própria raiz do CNPJ: troca por um rótulo seguro antes de ranquear
        nos = [{**n, "rotulo": _rotulo_seguro(n["rotulo"], n["chave"])} for n in no_unidade["filhos"]]
        return derivacoes.ranking(nos, meses=meses, n=pedido.limite, teto=teto)

    # faixa: leitura, na ordem do relatório (as três faixas não são ranking)
    cliente = no_unidade["filhos"][0] if no_unidade["filhos"] else None
    faixas = cliente["filhos"] if cliente else []
    itens = [{"posicao": i, "rotulo": recorte.rotulo_faixa(f["chave"]),
              "valores": dict(f["valores"]),
              "total": derivacoes.total_do_periodo(f["valores"], meses)["total"]}
             for i, f in enumerate(faixas, start=1)]
    return {"itens": itens, "total_itens": len(itens), "truncado": False}


def _parametros_registro(pedido: Pedido) -> dict:
    """O que vai para `ia_consultas`: parâmetros resolvidos, em RÓTULOS. A chave do
    cliente não é gravada (DD-17)."""
    return {
        "de": pedido.de, "ate": pedido.ate, "movimento": pedido.movimento, "lente": pedido.lente,
        "faixa": pedido.faixa, "unidades": list(pedido.unidades),
        "clientes": list(pedido.clientes_rotulos), "tipos_estoque": list(pedido.tipos_estoque),
        "operacoes": list(pedido.operacoes), "dias": list(pedido.dias),
        "detalhe": pedido.detalhe, "limite": pedido.limite, "derivacao": pedido.derivacao,
    }


# ===================================================================== blocos
def _fonte(dominio_nome: str, pedido: Pedido, unidade: str, opcoes: dict, linhas: int) -> dict:
    return {
        "tipo": "fonte", "nome": dominio_nome,
        "filtros": _linhas_do_recorte(pedido, unidade),
        "linhas_lidas": linhas,
        "atualizado_ate": {m: _hora_br(v) for m, v in opcoes["atualizado_ate"].items()},
    }


def _blocos_da_consulta(pedido, modelo, matriz, periodo, itens, unidade, meses, opcoes) -> list[dict]:
    blocos: list[dict] = []
    tiles = []
    if len(meses) == 1:
        tiles.append({"n": modelo["total_por_mes"][0]["valor"] or "—", "l": modelo["medida"]})
    elif periodo is not None:
        tiles.append({"n": modelo["total_do_periodo"]["valor"] or "—", "l": "total do período"})
    if itens and itens["itens"] and pedido.detalhe in ("unidade", "cliente"):
        topo = modelo["itens"][0]
        tiles.append({"n": topo["total_do_periodo"]["valor"] or "—", "l": f"{topo['rotulo']} · 1º"})
        tiles.append({"n": str(modelo["total_itens"]), "l": "itens no recorte"})
    if tiles:
        blocos.append({"tipo": "tiles", "itens": tiles})

    if itens and itens["itens"]:
        maximo = max((i["total"] or Decimal(0)) for i in itens["itens"])
        blocos.append({
            "tipo": "barras", "titulo": f"{modelo['medida']} · {pedido.detalhe}",
            "itens": [{"rotulo": i["rotulo"], "exibido": _v(i["total"], unidade)["valor"] or "—",
                       "largura": _largura(i["total"], maximo)} for i in itens["itens"]],
        })
        blocos.append({
            "tipo": "tabela", "colunas": ["#", pedido.detalhe.capitalize(), f"Total ({unidade})"],
            "linhas": [[str(m["posicao"]), m["rotulo"], m["total_do_periodo"]["valor"] or "—"]
                       for m in modelo["itens"]],
        })
    elif len(meses) > 1:
        valores = [matriz["total"].get(m) for m in meses]
        maximo = max((v for v in valores if v is not None), default=Decimal(0))
        blocos.append({
            "tipo": "barras", "titulo": f"{modelo['medida']} · por mês",
            "itens": [{"rotulo": m["rotulo"], "exibido": m["valor"] or "—",
                       "largura": _largura(v, maximo)} for m, v in zip(modelo["total_por_mes"], valores)],
        })
    if modelo["avisos"] or modelo["meses_parciais"]:
        avisos = list(modelo["avisos"])
        for mes, dia in modelo["meses_parciais"].items():
            avisos.append(f"{mes} está incompleto: o dado vai até o dia {dia}." if dia
                          else f"{mes} ainda não tem dado carregado.")
        blocos.append({"tipo": "avisos", "itens": avisos})
    blocos.append(_fonte("Volumetria de Catering · DW", pedido, unidade, opcoes, matriz["total_linhas"]))
    return blocos


# ================================================================== variação
def _variacao(pedido: Pedido, ctx, opcoes: dict, atualizado: date | None, unidade: str) -> dict:
    d = pedido.derivacao
    mes_base, mes_atual = d["mes_base"], d["mes_atual"]
    base = d.get("base")
    if base is not None and not ctx.base_autorizada:
        # DD-11: a IA NÃO consegue pular o passo de perguntar a base. `base` só vale se o
        # usuário a disse na própria pergunta ou se a resposta anterior pediu a escolha.
        raise ErroDeFerramenta(
            "base_nao_autorizada",
            "A base da comparação precisa ser escolhida pelo usuário. Não envie `base`: faça a "
            "consulta sem ela, e o Hub devolve as opções para você perguntar.")
    try:
        parciais = derivacoes.meses_parciais([mes_base, mes_atual], atualizado, ctx.hoje)
        escolha = derivacoes.escolha_de_base(mes_base, mes_atual, parciais, base)
    except ValueError as erro:
        raise ErroDeFerramenta("parametro_invalido", str(erro)) from None

    nucleo = {"dominio": SLUG, "capacidade": "matriz", "recorte": _linhas_do_recorte(pedido, unidade),
              "medida": contrato.LENTES[pedido.lente]["nome"], "unidade_exibida": unidade,
              "atualizado_ate": {m: _hora_br(v) for m, v in opcoes["atualizado_ate"].items()},
              "escopo": ESCOPO_APLICADO}

    if escolha is not None:  # a trava da DD-11: sem base explícita, não existe número
        ctx.pediu_base = True   # a próxima pergunta desta conversa pode trazer `base`
        nucleo["derivacao"] = {"tipo": "variacao_percentual", **escolha}
        return {"modelo": nucleo, "blocos": [{"tipo": "avisos", "itens": [
                    f"{m} está incompleto: o dado vai até o dia {dia}." for m, dia in escolha["meses_parciais"].items()]}],
                "linhas": 0, "parametros_registro": _parametros_registro(pedido)}

    usados = (mes_base, mes_atual)
    dias = pedido.dias
    base_dita = "os meses como estão"
    if base == "so_meses_completos":
        def completo(mes: str) -> bool:
            return mes not in derivacoes.meses_parciais([mes], atualizado, ctx.hoje)

        # O mês atual recua até um mês completo; a base recua até um mês completo
        # E diferente do atual. Setembro (incompleto) contra agosto vira agosto
        # contra julho. O limite de 12 recuos evita laço com dado muito atrasado.
        novo_atual, novo_base = mes_atual, mes_base
        for _ in range(12):
            if completo(novo_atual):
                break
            novo_atual = _mes_anterior(novo_atual)
        for _ in range(12):
            if completo(novo_base) and novo_base != novo_atual:
                break
            novo_base = _mes_anterior(novo_base)
        if not (completo(novo_atual) and completo(novo_base)) or novo_base == novo_atual:
            raise ErroDeFerramenta("parametro_invalido", "sem dois meses completos distintos para comparar")
        usados = (novo_base, novo_atual)
        base_dita = f"somente meses completos ({usados[0]} e {usados[1]})"
    elif base == "mesmos_dias":
        if pedido.dias:
            raise ErroDeFerramenta("parametro_invalido",
                                   "base 'mesmos_dias' não combina com o filtro de dias informado")
        corte = min((dia for dia in parciais.values() if dia), default=0)
        if not corte:
            raise ErroDeFerramenta("parametro_invalido", "não há dia de corte para a base 'mesmos_dias'")
        dias = tuple(range(1, corte + 1))
        base_dita = f"os mesmos dias (1 a {corte}) nos dois meses"
    elif base == "mes_incompleto_vs_inteiro":
        base_dita = "o mês incompleto contra o outro mês inteiro"

    span = sorted(usados)
    refeito = replace(pedido, de=_primeiro_dia(span[0]), ate=_ultimo_dia_do_mes(span[1]), dias=dias)
    matriz = _ler(ctx, _filtros_do(refeito), todas_as_paginas=False)[0]
    valor_base, valor_atual = matriz["total"].get(usados[0]), matriz["total"].get(usados[1])
    calculo = derivacoes.variacao_percentual(valor_base, valor_atual)

    avisos = [html.unescape(a) for a in matriz["avisos"]]
    for mes, dia in parciais.items():
        avisos.append(f"{mes} está incompleto: o dado vai até o dia {dia}." if dia
                      else f"{mes} ainda não tem dado carregado.")
    if calculo["ausente_base"] or calculo["ausente_atual"]:
        avisos.append("Um dos meses não teve registro e foi tratado como zero.")

    nucleo["recorte"] = _linhas_do_recorte(refeito, unidade)
    nucleo["derivacao"] = {
        "tipo": "variacao_percentual", "situacao": calculo["situacao"],
        "mes_base": usados[0], "valor_base": _v(valor_base, unidade),
        "mes_atual": usados[1], "valor_atual": _v(valor_atual, unidade),
        "percentual": f"{calculo['percentual']}%" if calculo["percentual"] else None,
        "sentido": calculo.get("sentido"), "mensagem": calculo.get("mensagem"),
        "base_usada": base_dita,
    }
    nucleo["avisos"] = avisos
    blocos = [{"tipo": "tiles", "itens": [
        {"n": nucleo["derivacao"]["percentual"] or "—", "l": f"variação {usados[0]} → {usados[1]}"},
        {"n": nucleo["derivacao"]["valor_base"]["valor"] or "—", "l": usados[0]},
        {"n": nucleo["derivacao"]["valor_atual"]["valor"] or "—", "l": usados[1]},
    ]}]
    if avisos:
        blocos.append({"tipo": "avisos", "itens": avisos})
    blocos.append(_fonte("Volumetria de Catering · DW", refeito, unidade, opcoes, matriz["total_linhas"]))
    return {"modelo": nucleo, "blocos": blocos, "linhas": matriz["total_linhas"],
            "parametros_registro": _parametros_registro(refeito)}
