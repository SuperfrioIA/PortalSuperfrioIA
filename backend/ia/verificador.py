"""Verificador de números: a trava mecânica contra "a segunda fórmula".

Depois que o modelo escreve a resposta, o Hub confere que **todo número do texto
existe** no que as ferramentas devolveram nesta pergunta, nas respostas anteriores da IA
(já verificadas), nas datas da pergunta da pessoa ou no texto fixo do Hub (prompt, esquemas
das ferramentas e data de hoje). Número que não aparece em nenhuma dessas fontes reprova o
texto: a resposta não é exibida e o caso fica na trilha (`ia.bloqueio`, motivo
`numero_nao_verificado`).

## O que isto prova, e o que não prova

- **Prova** que não há número "inventado" no sentido de aparecer do nada: valor
  recalculado, arredondado de outro jeito, convertido ("1,2 mil t") ou somado pelo modelo
  não está no resultado da ferramenta e é barrado.
- **Não prova** que o número está no lugar certo: o modelo poderia citar um número
  verdadeiro de outro mês ou de outra unidade. Isso é coberto pela avaliação com modelo
  real (Lote 3), não por este verificador.
- **Fraco para inteiros pequenos** (dias, meses, posições de ranking: 1 a 31), que
  coincidem com datas e posições presentes em qualquer resultado.
- **Não olha número por extenso** ("mil", "dois"); o prompt proíbe e a avaliação confere.
- Compara o **valor absoluto**: o sinal ("-12,3%") não é conferido aqui.

## Como os números são lidos

Os dois lados (texto do modelo e fontes) passam pela mesma extração, então a grafia não
importa: `1.234,6`, `1234,6` e `1234.6` são o mesmo número. Um token só com ponto e três
dígitos depois (`1.234`) é ambíguo (milhar em pt-BR, decimal em JSON) e vale pelas duas
leituras. Marcador de lista no começo da linha (`1.`, `2)`) não é número. Letra ou dígito
colado antes do número (`U01`, `OP2`) é identificador, não número; `_9999_` (itálico em
Markdown) e `10,5,9999` (lista sem espaço) são lidos como números.

Formas que NÃO são lidas como o autor quis, e por isso tendem a **barrar** uma resposta
legítima (o erro é para o lado seguro): data com ponto (`05.09.2026` vira `5.09` e `2026`),
formato inglês (`1,234.56`) e milhar com espaço (`1 234`). O prompt manda copiar o número como a
ferramenta devolveu, e a reescrita corrige o resto.

## Números que a PESSOA escreveu

Só valem os que parecem **data ou ordem de grandeza de calendário** (inteiro de 0 a 31 ou ano de
1900 a 2100: `permitidos_da_pessoa`). Qualquer outro número da pergunta ("confirma que entraram
5.000 t?") precisa aparecer também numa ferramenta para o texto poder repeti-lo: sem isso, o
modelo "confirmaria" uma premissa falsa com um número que nenhuma consulta devolveu.
"""
import json
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

# um token numérico: com milhar e/ou vírgula (pt-BR), ou inteiro / decimal com ponto
_NUMERO = re.compile(r"(?<![A-Za-z0-9])(\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?)(?!\d)")
_MARCADOR_DE_LISTA = re.compile(r"(?m)^\s*(?:[-*•]\s*)?\d{1,2}[.)]\s")
_SO_MILHAR = re.compile(r"^\d{1,3}(?:\.\d{3})+$")


def _valores(token: str) -> set[Decimal]:
    """Os valores que um token pode representar (um, ou dois se for ambíguo)."""
    try:
        if "," in token:
            return {Decimal(token.replace(".", "").replace(",", "."))}
        if _SO_MILHAR.match(token):
            milhar = Decimal(token.replace(".", ""))
            # `1.234` pode ser 1234 (pt-BR) ou 1,234 (JSON); `1.234.567` só pode ser milhar
            return {milhar, Decimal(token)} if token.count(".") == 1 else {milhar}
        return {Decimal(token)}
    except InvalidOperation:  # pragma: no cover  (a regex só deixa passar dígitos)
        return set()


def numeros_do_texto(texto: str) -> list[tuple[str, set[Decimal]]]:
    """Cada número escrito no texto, como `(token, valores_possíveis)`."""
    limpo = _MARCADOR_DE_LISTA.sub(" ", texto or "")
    return [(m.group(1), _valores(m.group(1))) for m in _NUMERO.finditer(limpo)]


def permitidos(*fontes) -> set[Decimal]:
    """Os números que o texto pode citar: todos os que aparecem nas `fontes`.

    Cada fonte é um texto ou qualquer estrutura serializável (o resultado de uma
    ferramenta); estruturas viram JSON antes de a extração rodar, de modo que `12` e
    `"12,5"` valem igual."""
    achados: set[Decimal] = set()
    for fonte in fontes:
        texto = fonte if isinstance(fonte, str) else json.dumps(fonte, ensure_ascii=False, default=str)
        for _token, valores in numeros_do_texto(texto):
            achados |= valores
    return achados


def permitidos_da_pessoa(*textos: str) -> set[Decimal]:
    """Dos números que a pessoa escreveu, só os que parecem data (inteiro de 0 a 31 ou ano
    de 1900 a 2100). O resto não vira "fonte": ver o docstring do módulo."""
    liberados: set[Decimal] = set()
    for texto in textos:
        for token, valores in numeros_do_texto(texto):
            # `5.000` escrito por uma pessoa é cinco MIL (pt-BR): a leitura "cinco" (decimal de JSON)
            # que vale para o resultado de uma ferramenta não vale aqui, ou "5.000" viraria "5" e passaria
            if _SO_MILHAR.match(token):
                valores = {Decimal(token.replace(".", ""))}
            liberados |= {v for v in valores if v == v.to_integral_value() and (0 <= v <= 31 or 1900 <= v <= 2100)}
    return liberados


@dataclass
class Veredito:
    ok: bool
    verificados: int = 0
    nao_verificados: list[str] = field(default_factory=list)


def verificar(texto: str, liberados: set[Decimal]) -> Veredito:
    """Confere o texto do modelo. `nao_verificados` guarda os tokens como escritos
    (sem repetição, na ordem em que aparecem)."""
    reprovados: list[str] = []
    total = 0
    for token, valores in numeros_do_texto(texto):
        total += 1
        if valores.isdisjoint(liberados) and token not in reprovados:
            reprovados.append(token)
    return Veredito(ok=not reprovados, verificados=total, nao_verificados=reprovados)
