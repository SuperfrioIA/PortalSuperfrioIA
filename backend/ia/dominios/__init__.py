"""Catálogo de domínios do SuperfrioIA: o contrato em YAML, validado no boot.

Cada `*.yaml` desta pasta é o contrato de um domínio (perguntas atendidas, métricas,
filtros permitidos, escopo, limitações, responsável). Mesmo padrão de
`registrar_modulo` (`backend/core/permissoes.py`): **contrato inconsistente derruba
a subida** do Hub com uma mensagem que nomeia o arquivo e o campo, em vez de virar
uma resposta errada em produção. A validação roda mesmo com `IA_HABILITADO`
desligada: é nesse estado que o deploy acontece, e é melhor falhar nele.

A validação tem duas camadas:

1. **estrutural**, aqui: campos obrigatórios, tipos, permissão de aprovação
   existente no catálogo;
2. **do domínio**, em `adaptadores/<adaptador>.py::validar_contrato`: métrica,
   faixa, filtro e função conferidos contra o código real do módulo dono.

O YAML descreve; quem executa é o adaptador. Nada neste pacote conhece SQL, cursor
ou DW (teste AST em `test_ia_seguranca.py`).
"""
import importlib
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from backend.core import permissoes as catalogo_de_permissoes

PASTA = Path(__file__).resolve().parent
_SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_NOME_DE_ADAPTADOR = re.compile(r"^[a-z][a-z0-9_]*$")


class ContratoInvalido(Exception):
    """O contrato de um domínio não bate com o código. A mensagem nomeia o erro."""


@dataclass(frozen=True)
class Dominio:
    slug: str
    nome: str
    adaptador: str
    app_hub: str
    permissao_de_aprovacao: str
    classificacao: str
    dados: dict = field(repr=False)  # o YAML inteiro, já validado

    def __getitem__(self, chave):
        return self.dados[chave]

    def get(self, chave, padrao=None):
        return self.dados.get(chave, padrao)


_cache: dict[str, Dominio] | None = None


def _exigir(condicao: bool, origem: str, mensagem: str) -> None:
    if not condicao:
        raise ContratoInvalido(f"contrato {origem}: {mensagem}")


def _validar_estrutura(dados: dict, origem: str, esperado: str) -> None:
    _exigir(isinstance(dados, dict), origem, "o arquivo precisa ser um mapa YAML")
    for chave in ("dominio", "nome", "adaptador", "app_hub", "classificacao", "modo",
                  "responsavel", "escopo_usuario", "metricas", "capacidades",
                  "nao_atendidas", "exemplos"):
        _exigir(chave in dados, origem, f"campo obrigatório ausente: {chave!r}")
    _exigir(_SLUG.match(str(dados["dominio"])) is not None, origem,
            f"dominio inválido: {dados['dominio']!r}")
    _exigir(dados["dominio"] == esperado, origem,
            f"dominio {dados['dominio']!r} diverge do nome do arquivo ({esperado!r})")
    _exigir(dados["modo"] == "A", origem,
            f"modo {dados['modo']!r} não existe neste lote (só 'A', indicador pronto)")
    _exigir(_NOME_DE_ADAPTADOR.match(str(dados["adaptador"])) is not None, origem,
            f"adaptador inválido: {dados['adaptador']!r}")

    escopo = dados["escopo_usuario"]
    _exigir(isinstance(escopo, dict) and escopo.get("tipo") and escopo.get("justificativa"),
            origem, "escopo_usuario precisa de 'tipo' e 'justificativa' (DD-5): "
            "'nenhum' também exige justificar")

    responsavel = dados["responsavel"]
    _exigir(isinstance(responsavel, dict), origem, "responsavel precisa ser um mapa")
    for chave in ("contrato", "tecnico", "acesso"):
        _exigir(responsavel.get(chave), origem, f"responsavel.{chave} ausente")
    _exigir(catalogo_de_permissoes.existe(responsavel["acesso"]), origem,
            f"responsavel.acesso {responsavel['acesso']!r} não existe no catálogo de permissões "
            "(declare em backend/<modulo>/permissoes.py)")

    _exigir(isinstance(dados["metricas"], dict) and dados["metricas"], origem,
            "metricas vazia")
    capacidades = dados["capacidades"]
    _exigir(isinstance(capacidades, list) and capacidades, origem, "capacidades vazia")
    nomes = [c.get("nome") for c in capacidades if isinstance(c, dict)]
    _exigir(all(nomes) and len(nomes) == len(set(nomes)) == len(capacidades), origem,
            "cada capacidade precisa de um 'nome' único")
    for capacidade in capacidades:
        _exigir(capacidade.get("funcao"), origem, f"capacidade {capacidade['nome']!r} sem 'funcao'")
        _exigir(isinstance(capacidade.get("parametros"), list), origem,
                f"capacidade {capacidade['nome']!r}: 'parametros' precisa ser uma lista")

    responde = (dados["exemplos"] or {}).get("responde")
    _exigir(isinstance(responde, list) and responde, origem, "exemplos.responde vazio")

    limite = (dados.get("limites") or {}).get("consultas_por_pergunta")
    _exigir(limite is None or (isinstance(limite, int) and limite > 0), origem,
            "limites.consultas_por_pergunta precisa ser um inteiro positivo")


def _importar_adaptador(nome: str, origem: str):
    try:
        return importlib.import_module(f"backend.ia.adaptadores.{nome}")
    except ModuleNotFoundError:
        raise ContratoInvalido(
            f"contrato {origem}: adaptador {nome!r} não existe em backend/ia/adaptadores/"
        ) from None


def validar(dados: dict, origem: str, esperado: str) -> Dominio:
    """Valida um contrato já lido do YAML. `origem` é só para a mensagem."""
    _validar_estrutura(dados, origem, esperado)
    adaptador = _importar_adaptador(dados["adaptador"], origem)
    adaptador.validar_contrato(dados, origem)  # levanta ContratoInvalido
    return Dominio(
        slug=dados["dominio"], nome=dados["nome"], adaptador=dados["adaptador"],
        app_hub=dados["app_hub"], permissao_de_aprovacao=dados["responsavel"]["acesso"],
        classificacao=dados["classificacao"], dados=dados,
    )


def carregar(forcar: bool = False) -> dict[str, Dominio]:
    """Lê e valida todos os contratos da pasta. Cacheado: o conteúdo é código
    versionado e só muda com deploy."""
    global _cache
    if _cache is not None and not forcar:
        return _cache
    carregados: dict[str, Dominio] = {}
    for arquivo in sorted(PASTA.glob("*.yaml")):
        origem = arquivo.name
        try:
            dados = yaml.safe_load(arquivo.read_text(encoding="utf-8"))
        except yaml.YAMLError as erro:
            raise ContratoInvalido(f"contrato {origem}: YAML ilegível — {erro}") from None
        dominio = validar(dados, origem, arquivo.stem)
        carregados[dominio.slug] = dominio
    _cache = carregados
    return carregados


def obter(slug: str) -> Dominio | None:
    return carregar().get(slug)


def limpar_cache() -> None:
    """Só para testes."""
    global _cache
    _cache = None
