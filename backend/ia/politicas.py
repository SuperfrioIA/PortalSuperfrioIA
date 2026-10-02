"""Políticas do SuperfrioIA: o que é recusado, mascarado e contado.

Três assuntos, todos independentes de provedor e de domínio:

1. **Dado pessoal na pergunta** (D-17, opção b): CPF, CNPJ, e-mail e telefone são
   **mascarados antes de qualquer persistência ou envio**. Nome de pessoa não tem
   detector confiável; a proteção é o domínio não ter campo de pessoa.
2. **Exceções de domínio**: o vocabulário com que as camadas de baixo falam com as de
   cima, sem HTTP e sem FastAPI.
3. **Limites por pergunta** (DD-16, DD-24): `ContextoDaPergunta` conta as chamadas
   **lógicas** ao indicador (o que o teto de 3 limita) e, **à parte**, o trabalho
   interno no banco (o que o limite independente limita). Dois contadores, de
   propósito: uma única chamada lógica pode varrer várias páginas.
"""
import re
from dataclasses import dataclass, field
from datetime import date

from backend.ia import config

# ------------------------------------------------------------------ máscara
# Ordem importa: o mais específico primeiro (CNPJ antes de CPF antes de telefone),
# para um CNPJ não ser mascarado em pedaços como se fosse telefone.
_PADROES = (
    ("CNPJ", re.compile(r"(?<!\d)\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}(?!\d)")),
    ("CPF", re.compile(r"(?<!\d)\d{3}\.?\d{3}\.?\d{3}-?\d{2}(?!\d)")),
    ("EMAIL", re.compile(r"[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)+")),
    ("TELEFONE", re.compile(r"(?<!\d)(?:\+?55[\s\-]?)?(?:\(?\d{2}\)?[\s\-]?)?9?\d{4}[\s\-]?\d{4}(?!\d)")),
)
# "CNPJ 12.345" / "cpf: 1234": o número depois da palavra é identificador mesmo
# quando curto ou mal formatado (a raiz de 8 dígitos é a chave do cliente, DD-17).
_APOS_PALAVRA = re.compile(r"(?i)\b(cnpj|cpf)\b(\s*[:\-]?\s*)[\d./\-]{4,}")


_BASE_NA_PERGUNTA = re.compile(
    r"mesmos? dias|meses? completos?|mes incompleto|mes inteiro|ate o dia \d+|\bdia 1 a \d+|\b1 a \d+\b|primeiros? \w+ dias"
)


def mencionou_a_base(texto: str) -> bool:
    """A pergunta do usuário já diz a base da comparação ("mesmos dias", "só meses
    completos", "1 a 15")? Então o modelo pode mandar `base` sem perguntar de volta
    (DD-11: pergunta que já diz a base é calculada direto)."""
    import unicodedata
    plano = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()
    return bool(_BASE_NA_PERGUNTA.search(plano))


def mascarar(texto: str) -> tuple[str, list[str]]:
    """Troca dado pessoal por `[CPF]`, `[CNPJ]`, `[EMAIL]`, `[TELEFONE]`.

    Devolve o texto mascarado e os **tipos** achados (sem os valores), para a
    resposta avisar "removi dado pessoal da pergunta" e a auditoria contar.
    """
    achados: list[str] = []

    def _marca(tipo):
        def _troca(_m):
            achados.append(tipo)
            return f"[{tipo}]"
        return _troca

    texto = _APOS_PALAVRA.sub(
        lambda m: (achados.append(m.group(1).upper()), f"{m.group(1)}{m.group(2)}[{m.group(1).upper()}]")[1],
        texto,
    )
    for tipo, padrao in _PADROES:
        texto = padrao.sub(_marca(tipo), texto)
    return texto, achados


# --------------------------------------------------------------- exceções
class ErroDeFerramenta(Exception):
    """A ferramenta recusou os parâmetros, mas a pergunta continua. Volta ao modelo
    como resultado de erro, com `codigo` estável e uma mensagem que diz o que
    corrigir (e, quando faz sentido, candidatos por rótulo)."""

    def __init__(self, codigo: str, mensagem: str, **extra):
        super().__init__(mensagem)
        self.codigo = codigo
        self.mensagem = mensagem
        self.extra = extra

    def como_dict(self) -> dict:
        return {"erro": self.codigo, "mensagem": self.mensagem, **self.extra}


class EncerrarPergunta(Exception):
    """A pergunta termina aqui, sem devolver a palavra ao modelo: limite estourado
    ou fonte indisponível. O orquestrador responde com texto fixo — o modelo não
    improvisa sobre um dado que não leu."""

    def __init__(self, motivo: str, mensagem: str):
        super().__init__(mensagem)
        self.motivo = motivo
        self.mensagem = mensagem


class ErroDoProvedor(Exception):
    """O provedor do modelo falhou (sem chave, rede, limite, resposta inválida...). A
    pergunta termina com a mensagem **neutra** do serviço; o `tipo` (uma palavra, nunca o
    texto do erro nem corpo de requisição ou resposta) vai para a trilha."""

    def __init__(self, tipo: str, *, status: int | None = None, tipo_api: str | None = None):
        super().__init__(tipo)
        self.tipo = tipo
        # diagnóstico do primeiro erro real: o status HTTP e o `error.type` da API, que são
        # palavras de um conjunto fixo. A MENSAGEM do erro nunca entra (pode trazer a requisição)
        self.status = status
        self.tipo_api = tipo_api


class Recusa(Exception):
    """Recusa na porta de entrada (antes de qualquer ferramenta), com o status HTTP
    que a rota deve devolver."""

    def __init__(self, status: int, motivo: str, mensagem: str):
        super().__init__(mensagem)
        self.status = status
        self.motivo = motivo
        self.mensagem = mensagem


# ----------------------------------------------------- contexto da pergunta
@dataclass
class ContextoDaPergunta:
    """Estado de UMA pergunta: quem, em que dia, e quanto trabalho já foi feito.

    Dois contadores independentes (DD-24):

    - `consultas_logicas`: chamadas a `consultar_indicador` pedidas pelo modelo,
      contadas **todas**, inclusive as recusadas por parâmetro inválido — um
      modelo que erra em laço não pode ficar de graça;
    - `chamadas_servico` / `paginas_lidas` / `consultas_dw`: o que o Hub fez de
      fato. `consultas_dw` é uma estimativa por movimento lido (a conjunta lê
      dois), contada pelo adaptador sem tocar no cursor.
    """

    usuario: dict
    dominio: str
    hoje: date
    consultas_logicas: int = 0
    passos: int = 0
    chamadas_servico: int = 0
    paginas_lidas: int = 0
    consultas_dw: int = 0
    limite_interno_atingido: bool = False
    # contadores no fim do último registro de consulta: o trabalho feito por outras
    # ferramentas (amostrar valores, descrever) entre duas consultas é atribuído à
    # consulta SEGUINTE, para a soma dos registros bater com o que o DW viu
    marca: tuple = (0, 0, 0)
    # Trava da DD-11 contra o MODELO (não só contra o parâmetro ausente): `base` na
    # variação percentual só vale se o usuário a escolheu. `base_autorizada` é decidida
    # pelo orquestrador (pergunta que menciona a base, ou resposta anterior que a pediu);
    # `pediu_base` marca que ESTA resposta pediu, para a próxima pergunta herdar.
    base_autorizada: bool = False
    pediu_base: bool = False
    # TUDO que as ferramentas devolveram ao modelo nesta pergunta (inclusive `descrever`
    # e `amostrar_valores`): é a fonte dos números que o texto pode citar (verificador)
    saidas: list = field(default_factory=list)
    # o que as ferramentas devolveram com sucesso, para montar os blocos exibidos
    resultados: list = field(default_factory=list)
    # uma linha por consulta ao indicador, para `ia_consultas`
    registros: list = field(default_factory=list)
    # recusas pedidas pelo modelo (domínio trocado, ferramenta inexistente...), para
    # o orquestrador auditar como `ia.bloqueio`
    bloqueios: list = field(default_factory=list)
    _opcoes: dict | None = None

    # -- passos e consultas lógicas -----------------------------------------
    def novo_passo(self) -> None:
        self.passos += 1
        if self.passos > config.max_passos_do_provedor():
            raise EncerrarPergunta(
                "passos",
                "A pergunta pediu mais etapas do que o limite permite. Tente uma pergunta mais direta.",
            )

    def nova_consulta_logica(self, limite_do_contrato: int | None = None) -> None:
        limite = config.max_consultas_por_pergunta()
        if limite_do_contrato is not None:
            limite = min(limite, limite_do_contrato)
        self.consultas_logicas += 1
        if self.consultas_logicas > limite:
            raise EncerrarPergunta(
                "limite_consultas",
                f"Esta pergunta exigiria mais de {limite} consultas ao indicador. "
                "Divida em perguntas menores.",
            )

    # -- trabalho interno ----------------------------------------------------
    def reservar_chamada_ao_servico(self, *, movimento: str | None = None, pagina: bool = False) -> None:
        """Chamar ANTES de cada `service.*`. Estoura o limite independente."""
        if self.chamadas_servico + 1 > config.max_operacoes_dw_por_pergunta():
            self.limite_interno_atingido = True
            raise EncerrarPergunta(
                "limite_interno",
                "Esta pergunta é ampla demais e exigiria ler dados demais de uma vez. "
                "Restrinja o período ou a unidade e pergunte de novo.",
            )
        self.chamadas_servico += 1
        if pagina:
            self.paginas_lidas += 1
        if movimento is not None:
            self.consultas_dw += 2 if movimento == "amb" else 1

    def recusar_varredura_grande(self, paginas: int) -> None:
        """Um ranking que precisaria de mais páginas que o limite de varredura."""
        if paginas > config.max_paginas_por_varredura():
            self.limite_interno_atingido = True
            raise EncerrarPergunta(
                "limite_interno",
                f"Esta pergunta abrangeria {paginas} páginas de unidades, acima do limite de "
                f"{config.max_paginas_por_varredura()}. Restrinja o recorte e pergunte de novo.",
            )

    def totais(self) -> dict:
        """O trabalho da pergunta inteira, para a trilha e para `ia_mensagens.meta`."""
        return {
            "consultas_logicas": self.consultas_logicas, "passos": self.passos,
            "chamadas_servico": self.chamadas_servico, "paginas_lidas": self.paginas_lidas,
            "consultas_dw": self.consultas_dw, "limite_interno_atingido": self.limite_interno_atingido,
        }

    # -- opções (cache por pergunta) ----------------------------------------
    def opcoes(self, buscar) -> dict:
        """`buscar()` é `service.opcoes`. Chamada uma vez por pergunta, e conta
        como uma operação efetiva."""
        if self._opcoes is None:
            self.reservar_chamada_ao_servico()
            self._opcoes = buscar()
        return self._opcoes
