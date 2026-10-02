"""Provedor de modelo: a interface e o provedor **falso** do Lote 2.

A interface é a que o provedor real (Claude, Lote 3) vai implementar: recebe o
contexto da pergunta e uma função `executar(ferramenta, argumentos)`, e devolve o
texto da resposta. Quem faz o laço de ferramentas é o provedor; **quem aplica os
limites é o `executar`** (ele levanta `EncerrarPergunta` quando a pergunta tem que
parar), então nenhum provedor consegue passar do teto.

## O provedor falso

Determinístico, sem rede e sem chave. Lê a pergunta em português, decide as
chamadas de ferramenta e monta o texto **somente com strings que as ferramentas
devolveram**: não calcula, não arredonda, não converte. Serve para exercitar o
caminho inteiro (contrato, limites, concessão, auditoria, tela) e para o teste
provar que a tela mostra o que a ferramenta entregou. **Não é um modelo**: a tela
marca as respostas dele como "provedor de teste" (risco do plano, Lote 2).
"""
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Protocol

PROMPT_BASE = (
    "Você é o SuperfrioIA, assistente de dados do Hub SuperFrio & Icestar. Responda somente "
    "com números devolvidos pelas ferramentas; nunca some, divida, ordene ou converta. Diga "
    "sempre o recorte, a faixa usada e a data de atualização do dado. Recuse, explicando o "
    "porquê, o que o contrato do domínio não atende."
)


@dataclass
class ContextoDoModelo:
    sistema: str
    historico: list[dict]          # [{"papel": "usuario" | "ia", "texto": str}]
    pergunta: str                  # já mascarada
    ferramentas: list[dict]
    hoje: date
    dominio: str
    # Confere um texto contra o que as ferramentas devolveram até agora e devolve os
    # números reprovados (lista vazia = ok). O provedor real usa para pedir UMA reescrita
    # antes de a resposta ser retida (T-31); o serviço confere de novo no fim, sempre.
    verificar: Callable[[str], list[str]] | None = None


@dataclass
class RespostaDoModelo:
    texto: str
    uso: dict = field(default_factory=dict)  # tokens, custo... (provedor real)


class Provedor(Protocol):
    nome: str
    rotulo: str

    def responder(
        self, contexto: ContextoDoModelo, executar: Callable[[str, dict], dict]
    ) -> RespostaDoModelo: ...


# ================================================================ linguagem
def _norm(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", sem_acento.lower()).strip()


_MESES = {"janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5, "junho": 6, "julho": 7,
          "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12}
_NUMEROS = {"um": 1, "dois": 2, "tres": 3, "quatro": 4, "cinco": 5, "seis": 6, "sete": 7,
            "oito": 8, "nove": 9, "dez": 10}
_RE_MES = re.compile(r"\b(" + "|".join(_MESES) + r")(?:\s+de\s+(\d{4})|\s+(\d{4}))?\b")
_TIPOS = ("congelado", "seco", "hortifruti", "utensilios", "resfriado")

# gatilho -> por que o domínio não responde (a mesma lista do contrato, §5)
_RECUSAS = (
    (("dia da semana",), "O corte por dia da semana não existe: o dado é mensal."),
    (("por dia", "diari", "cada dia", "serie diaria"), "O grão do dado é mensal: não existe série diária."),
    (("previs", "projec"), "Não existe previsão no dado."),
    (("meta", "acima da meta", "abaixo da meta"), "Não existe meta cadastrada neste domínio."),
    (("guia",), "Linha crua de guia não faz parte do que a IA consulta."),
    (("baixe", "baixar", "download", "relatorio", "exporte", "planilha"),
     "Baixar relatório ou planilha não é uma capacidade da IA; use a tela do app."),
    (("participacao", "% do total", "representa", "percentual do total"),
     "Participação percentual não é calculada neste recorte."),
    (("media",), "Média mensal não é calculada neste recorte."),
    (("quem registrou", "quem baixou", "usuario", "quem fez", "quem criou"),
     "O domínio não tem informação sobre pessoas."),
    (("cnpj", "cpf"), "O domínio não responde por documento de cliente."),
    (("integracao", "in/out", "in out", "compar"),
     "Comparar com outro indicador está fora do primeiro recorte."),
    (("cada tipo de estoque", "por tipo de estoque", "tipos de estoque"),
     "Um número por tipo de estoque exigiria mais consultas do que o limite permite."),
)


def _recusa(q: str) -> str | None:
    for gatilhos, motivo in _RECUSAS:
        if any(g in q for g in gatilhos):
            return motivo
    return None


def _meses_citados(q: str, hoje: date) -> list[tuple[int, int]]:
    achados = []
    for m in _RE_MES.finditer(q):
        mes = _MESES[m.group(1)]
        ano = int(m.group(2) or m.group(3) or 0) or (hoje.year if mes <= hoje.month else hoje.year - 1)
        achados.append((ano, mes))
    return achados


def _ultimo(ano: int, mes: int) -> str:
    import calendar
    return f"{ano}-{mes:02d}-{calendar.monthrange(ano, mes)[1]:02d}"


def _mes_anterior(ano: int, mes: int) -> tuple[int, int]:
    return (ano - 1, 12) if mes == 1 else (ano, mes - 1)


def _periodo(q: str, hoje: date) -> tuple[str, str] | None:
    citados = _meses_citados(q, hoje)
    if citados:
        primeiro, ultimo = min(citados), max(citados)
        return f"{primeiro[0]}-{primeiro[1]:02d}-01", _ultimo(*ultimo)
    if "este mes" in q or "mes atual" in q or "ate agora" in q or "mes corrente" in q:
        return f"{hoje.year}-{hoje.month:02d}-01", hoje.isoformat()
    if "trimestre" in q:
        fim = _mes_anterior(hoje.year, hoje.month)
        ini = _mes_anterior(*_mes_anterior(*fim))
        return f"{ini[0]}-{ini[1]:02d}-01", _ultimo(*fim)
    if re.search(r"\b(no ano|este ano|do ano)\b", q):
        return f"{hoje.year}-01-01", hoje.isoformat()
    return None


# ================================================================== o falso
class ProvedorFalso:
    nome = "falso"
    rotulo = "provedor de teste"

    def responder(self, c: ContextoDoModelo, executar) -> RespostaDoModelo:
        q = _norm(c.pergunta)

        if re.search(r"\bo que (voce|vc) (sabe|responde|pode)\b|\bquais perguntas\b|\bajuda\b", q):
            return RespostaDoModelo(self._capacidades(executar, c))

        motivo = _recusa(q)
        if motivo:
            return RespostaDoModelo(self._recusar(executar, c, motivo))

        pergunta_de_frescor = "atualizad" in q or "de quando" in q or ("periodo" in q and "de que" in q)
        if pergunta_de_frescor:
            return RespostaDoModelo(self._frescor(executar, c, q))

        if re.search(r"\b(quais|que) (unidades|filiais)\b", q) or q.startswith("quais unidades"):
            return RespostaDoModelo(self._listar(executar, c, "unidade", "Unidades"))
        if re.search(r"\b(tipos de operacao|operacoes existem|quais operacoes)\b", q):
            return RespostaDoModelo(self._listar(executar, c, "operacao", "Tipos de operação"))

        # a resposta curta a "Qual base você quer?" ("mesmos dias") continua a variação
        base_pendente = bool(c.historico) and c.historico[-1]["papel"] == "ia" \
            and "qual base" in _norm(c.historico[-1]["texto"])
        if "variacao" in q or "variou" in q or base_pendente:
            return RespostaDoModelo(self._variacao(executar, c, q))

        return RespostaDoModelo(self._consultar(executar, c, q))

    # ---------------------------------------------------------- caminhos
    def _capacidades(self, executar, c) -> str:
        executar("listar_capacidades", {})
        d = executar("descrever", {"dominio": c.dominio})
        medidas = ", ".join(m["nome"] for m in d["medidas"].values())
        exemplos = d["exemplos"]["responde"][:3]
        return ("Posso consultar o indicador de **" + d["nome"] + "** (mensal) em: " + medidas + ". "
                "Exemplos:\n" + "\n".join(f"• {e}" for e in exemplos))

    def _recusar(self, executar, c, motivo: str) -> str:
        d = executar("descrever", {"dominio": c.dominio})
        exemplos = d["exemplos"]["responde"][:3]
        return (f"**Isso está fora do que este domínio responde.** {motivo} Posso, por exemplo:\n"
                + "\n".join(f"• {e}" for e in exemplos))

    def _frescor(self, executar, c, q: str) -> str:
        d = executar("descrever", {"dominio": c.dominio})
        dados = d.get("dados_disponiveis")
        if not dados:
            return "Não consegui consultar a data de atualização agora."
        rotulos = {"rec": "entrada", "exp": "saída"}
        linhas = [f"Dado do DW atualizado até {v} ({rotulos.get(m, m)})."
                  for m, v in dados["atualizado_ate"].items() if v]
        per = dados["periodo"]
        if per.get("de"):
            linhas.append(f"O dado existe de {per['de']} a {per['ate']}.")
        return "\n".join(linhas) or "Ainda não há dado carregado."

    def _listar(self, executar, c, dimensao: str, titulo: str) -> str:
        r = executar("amostrar_valores", {"dominio": c.dominio, "dimensao": dimensao, "termo": ""})
        if "valores_por_movimento" in r:
            return "\n".join(f"{titulo} ({m}): " + "; ".join(v) for m, v in r["valores_por_movimento"].items())
        return f"{titulo}: " + ", ".join(r["valores"]) + "."

    # ----------------------------------------------------------- consulta
    def _movimentos(self, q: str) -> list[str]:
        dentro = any(p in q for p in ("entrou", "entraram", "entrada", "recebeu", "receberam", "recebid", "recebimento"))
        fora = any(p in q for p in ("saiu", "sairam", "saida", "expedi", "expedid"))
        if "movimentacao" in q:
            return ["amb"]
        if dentro and fora:
            return ["rec", "exp"]
        return ["exp"] if fora else ["rec"]

    def _lente(self, q: str) -> str:
        if "pallet" in q or "palete" in q:
            return "pal"
        if "volume" in q:
            return "vol"
        if "valor" in q or "r$" in q:
            return "val"
        return "bru" if "bruto" in q else "liq"

    def _unidades(self, executar, c, q: str) -> list[str]:
        candidatos = set(re.findall(r"\b[A-Z][A-Z0-9]{1,7}\b", c.pergunta))
        # "unidade CPS": só sigla em maiúsculas, para "unidade mais" não virar consulta à toa
        candidatos |= set(re.findall(r"\b[Uu]nidade\s+([A-Z][A-Z0-9]{1,7})\b", c.pergunta))
        achadas = []
        for token in sorted(candidatos - {"DW", "IA"}):
            r = executar("amostrar_valores", {"dominio": c.dominio, "dimensao": "unidade", "termo": token})
            if token in r.get("valores", []):
                achadas.append(token)
        return achadas

    def _cliente(self, c) -> str | None:
        m = re.search(
            r"\bcliente\s+(.+?)(?=\s+(?:no|na|em|entre|de|do|da|durante|nos|nas|desde|ate|este|esse|"
            r"recebeu|teve|tem)\b|[?.,;]|$)", c.pergunta, re.I)
        return m.group(1).strip() if m else None

    def _dias(self, q: str) -> list[int]:
        m = re.search(r"primeiros? (\d+|" + "|".join(_NUMEROS) + r") dias", q)
        if not m:
            return []
        n = int(m.group(1)) if m.group(1).isdigit() else _NUMEROS[m.group(1)]
        return list(range(1, n + 1))

    def _tipo(self, q: str) -> list[str]:
        return [t.upper() for t in _TIPOS if t in q]

    def _consultar(self, executar, c, q: str) -> str:
        periodo = _periodo(q, c.hoje)
        if periodo is None:
            return "Qual período você quer consultar? Por exemplo: agosto de 2026."
        movimentos = self._movimentos(q)
        base = {"de": periodo[0], "ate": periodo[1], "lente": self._lente(q)}
        unidades = self._unidades(executar, c, q)
        if unidades:
            base["unidades"] = unidades
        cliente = self._cliente(c)
        if cliente:
            base["clientes"] = [cliente]
        if self._dias(q):
            base["dias"] = self._dias(q)
        if self._tipo(q):
            base["tipos_estoque"] = self._tipo(q)

        # ranking / detalhamento
        if re.search(r"qual (a )?unidade .*(mais|maior)|por unidade|cada unidade|ranking de unidades", q):
            base["detalhe"] = "unidade"
        elif re.search(r"(maiores|principais|maior) clientes?|qual cliente (mais|teve mais)|top \d* ?clientes", q):
            base["detalhe"] = "cliente"
            base.pop("clientes", None)
        elif "cada faixa" in q or "por faixa" in q:
            base["detalhe"] = "faixa"

        if base.get("detalhe") == "cliente" and len(unidades) != 1:
            return self._recusar(
                executar, c, "Ranking de clientes entre todas as unidades não é atendido; "
                "informe uma unidade (por exemplo, \"…da unidade X\").")

        chamadas = []
        faixas_pedidas = [f for f in ("solicitado", "atendido", "separado") if f[:-1] in q]
        if len(faixas_pedidas) == 3:
            movimentos = ["exp"]
            chamadas = [{**base, "movimento": "exp", "faixa": f} for f in faixas_pedidas]
        else:
            faixa = faixas_pedidas[0] if faixas_pedidas else None
            for mov in movimentos:
                p = {**base, "movimento": mov}
                if faixa and mov != "rec":
                    p["faixa"] = faixa
                chamadas.append(p)

        partes = []
        for params in chamadas:
            r = executar("consultar_indicador", {"dominio": c.dominio, "parametros": params})
            partes.append(self._texto_da_consulta(r, params))
        return "\n\n".join(partes)

    def _texto_da_consulta(self, r: dict, params: dict) -> str:
        if "erro" in r:
            return self._texto_do_erro(r)
        nomes = {"rec": "entrada", "exp": "saída", "amb": "movimentação (entrada + saída)"}
        mov = nomes[params["movimento"]]
        linhas = []
        meses = r["total_por_mes"]
        if r.get("vazio"):
            linhas.append(f"Não há valor para {mov} de **{r['medida']}** no recorte pedido.")
        elif len(meses) == 1:
            m = meses[0]
            linhas.append(f"Em {m['rotulo']}, a {mov} de **{r['medida']}** foi de **{m['valor']}**.")
        else:
            linhas.append(f"{mov.capitalize()} de **{r['medida']}** por mês:")
            linhas += [f"• {m['rotulo']}: {m['valor'] or 'sem registro'}" for m in meses]
            if "total_do_periodo" in r:
                linhas.append(f"Total do período: **{r['total_do_periodo']['valor']}**.")
        for item in r.get("itens", []):
            linhas.append(f"{item['posicao']}º **{item['rotulo']}**: {item['total_do_periodo']['valor']}")
        if r.get("truncado"):
            linhas.append(f"(mostrando os {len(r['itens'])} primeiros de {r['total_itens']})")
        if r.get("faixa_usada"):
            extra = (" — é o que o estoque atendeu, não confirmação de embarque ou saída física"
                     if r["faixa_usada"] == "atendido pelo estoque" else "")
            linhas.append(f"Faixa usada: {r['faixa_usada']}{extra}.")
        linhas += [f"Aviso: {a}" for a in r["avisos"]]
        linhas.append(self._fonte(r))
        return "\n".join(linhas)

    def _texto_do_erro(self, r: dict) -> str:
        codigo = r["erro"]
        if codigo == "ambiguo":
            # texto para o USUÁRIO: a mensagem da ferramenta é dirigida ao modelo
            return ("Encontrei mais de uma opção para o que você escreveu. Qual delas? "
                    + "; ".join(r["candidatos"]) + ".")
        if codigo == "nao_encontrado":
            return r["mensagem"] + " Parecidos: " + "; ".join(r.get("parecidos", [])) + "."
        if codigo == "fora_do_contrato":
            return "**Isso está fora do que este domínio responde.** " + r["mensagem"]
        return "Não consegui montar uma consulta segura para essa pergunta."

    def _fonte(self, r: dict) -> str:
        frescor = "; ".join(f"{v}" for v in r["atualizado_ate"].values() if v)
        recorte = " · ".join(r["recorte"])
        return f"Fonte: {r['dominio']} · {recorte} · dado do DW atualizado até {frescor or 'data indisponível'}."

    # ------------------------------------------------------------ variação
    def _variacao(self, executar, c, q: str) -> str:
        meses = _meses_citados(q, c.hoje)
        if len(meses) < 2:  # a base escolhida vem numa resposta curta ("mesmos dias")
            anterior = next((_norm(h["texto"]) for h in reversed(c.historico)
                             if h["papel"] == "usuario" and "variacao" in _norm(h["texto"])), "")
            meses = _meses_citados(anterior, c.hoje)
        if len(meses) < 2:
            return "Quais dois meses você quer comparar? Por exemplo: agosto e setembro."
        if "contra" in q:
            atual, base = meses[0], meses[1]
        else:
            base, atual = meses[0], meses[1]
        params = {"movimento": self._movimentos(q)[0], "lente": self._lente(q),
                  "derivacao": {"tipo": "variacao_percentual",
                                "mes_base": f"{base[0]}-{base[1]:02d}", "mes_atual": f"{atual[0]}-{atual[1]:02d}"}}
        escolha = next((b for b, gatilho in (("mesmos_dias", "mesmos dias"),
                                             ("mes_incompleto_vs_inteiro", "incompleto"),
                                             ("so_meses_completos", "completos")) if gatilho in q), None)
        if escolha:
            params["derivacao"]["base"] = escolha
        unidades = self._unidades(executar, c, q)
        if unidades:
            params["unidades"] = unidades
        cliente = self._cliente(c)
        if cliente:
            params["clientes"] = [cliente]
        r = executar("consultar_indicador", {"dominio": c.dominio, "parametros": params})
        if "erro" in r:
            return self._texto_do_erro(r)
        d = r["derivacao"]
        if d["situacao"] == "requer_escolha":
            opcoes = "; ".join(o["descricao"][:1].upper() + o["descricao"][1:] for o in d["opcoes"])
            parciais = ", ".join(f"{m} (dado até o dia {dia})" for m, dia in d["meses_parciais"].items())
            return (f"Há mês incompleto na comparação: {parciais}. Qual base você quer? {opcoes}.\n"
                    + self._fonte(r))
        if d["percentual"] is None:
            texto = f"Entre {d['mes_base']} ({d['valor_base']['valor']}) e {d['mes_atual']} " \
                    f"({d['valor_atual']['valor']}): {d['mensagem']}."
        else:
            texto = (f"A variação de {d['mes_base']} ({d['valor_base']['valor']}) para {d['mes_atual']} "
                     f"({d['valor_atual']['valor']}) foi de **{d['percentual']}** ({d['sentido']}). "
                     f"Base usada: {d['base_usada']}.")
        avisos = "\n".join(f"Aviso: {a}" for a in r.get("avisos", []))
        return "\n".join(p for p in (texto, avisos, self._fonte(r)) if p)


def obter(nome: str) -> Provedor:
    """O provedor configurado em `IA_PROVEDOR`: `falso` (Lote 2) ou `anthropic` (Lote 3).
    Um nome desconhecido falha alto em vez de cair em outro provedor sem avisar. Criar o
    provedor não toca a rede nem a chave (ver `provedor_anthropic`)."""
    if nome == "falso":
        return ProvedorFalso()
    if nome == "anthropic":
        from backend.ia.provedor_anthropic import ProvedorAnthropic  # import tardio: evita ciclo

        return ProvedorAnthropic()
    raise ValueError(f"provedor {nome!r} não existe (disponíveis: falso, anthropic)")
