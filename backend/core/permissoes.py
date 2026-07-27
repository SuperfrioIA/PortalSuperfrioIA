"""Catálogo de permissões da plataforma — infra, sem domínio.

Uma permissão é um par **app × ação**, escrita `<app-slug>:<acao>`. O vocabulário
de ações é **fechado**: todo app usa os mesmos verbos. É isso que torna possível a
matriz de acesso da tela de Administração (apps nas linhas, ações nas colunas) —
com verbos livres por módulo não existiriam colunas em comum.

Duas metades, com donos diferentes:

- **`ver`** é implícita: todo app cadastrado tem essa coluna, e ela continua
  gravada em `role_apps` (que é literalmente o que aquela tabela já significa).
  Módulo nenhum declara `ver`.
- **`editar` / `exportar` / `administrar`** são declaradas pelo módulo dono em
  `backend/<modulo>/permissoes.py` e gravadas em `role_permissoes`.

Por que o catálogo vive em código: é o que impede permissão digitada errado.
`require_permissao()` (em `auth/dependencies.py`) valida o slug **no import do
router** — slug inexistente derruba o boot em vez de virar um 403 silencioso em
produção. Foi exatamente esse o problema do antigo `ROLE_EDITOR = "..."`.

Este arquivo não conhece nenhum módulo de domínio (mesma regra do `core/http.py`).
"""
from dataclasses import dataclass
from typing import Mapping

# Coluna implícita da matriz: mora em `role_apps`, não em `role_permissoes`.
ACAO_VER = "ver"

# Ações que um módulo pode declarar. Acrescentar um verbo aqui acrescenta uma
# coluna na tela de Administração — não exige migration.
ACOES_MODULO: dict[str, str] = {
    "editar": "Editar",
    "exportar": "Exportar",
    "administrar": "Administrar",
}

# Vocabulário completo, na ordem em que a matriz exibe as colunas.
ACOES: dict[str, str] = {ACAO_VER: "Ver", **ACOES_MODULO}


@dataclass(frozen=True)
class Permissao:
    """Uma célula declarável da matriz."""

    slug: str        # "processos-abertos:editar"
    app_slug: str    # "processos-abertos" — casa com apps.slug
    acao: str        # "editar"
    nome: str        # "Editar" — rótulo da ação
    descricao: str   # o que ela libera, em português, para a tela
    modulo: str      # nome legível do módulo dono


_CATALOGO: dict[str, Permissao] = {}
_MODULOS: dict[str, str] = {}  # app_slug -> nome legível


def _slug_valido(slug: str) -> bool:
    return bool(slug) and slug == slug.lower() and all(c.isalnum() or c in "-_" for c in slug)


def registrar_modulo(
    app_slug: str, nome: str, acoes: Mapping[str, str]
) -> tuple[Permissao, ...]:
    """Declara as ações que um módulo entende, além de `ver`.

    Chamado no import de `backend/<modulo>/permissoes.py`. Devolve as permissões
    criadas para o módulo exportar como constantes.

    Falha alto e cedo (no import) em qualquer inconsistência: é o ponto que
    substitui a string mágica solta no router.
    """
    if not _slug_valido(app_slug):
        raise ValueError(
            f"app_slug inválido: {app_slug!r} — use minúsculas, números, '-' ou '_'"
        )
    if app_slug in _MODULOS:
        raise RuntimeError(
            f"módulo {app_slug!r} já registrou permissões — dois módulos com o mesmo app_slug?"
        )
    if not acoes:
        raise ValueError(f"módulo {app_slug!r} registrou um catálogo vazio")

    # Monta tudo antes de publicar: uma ação inválida no meio do dicionário não
    # pode deixar o catálogo meio registrado.
    criadas: list[Permissao] = []
    for acao, descricao in acoes.items():
        if acao == ACAO_VER:
            raise ValueError(
                f"{app_slug!r}: '{ACAO_VER}' é implícita para todo app (mora em role_apps) "
                "e não deve ser declarada pelo módulo"
            )
        if acao not in ACOES_MODULO:
            raise ValueError(
                f"{app_slug!r}: ação {acao!r} não existe no vocabulário "
                f"({', '.join(ACOES_MODULO)})"
            )
        criadas.append(
            Permissao(
                slug=f"{app_slug}:{acao}",
                app_slug=app_slug,
                acao=acao,
                nome=ACOES_MODULO[acao],
                descricao=descricao,
                modulo=nome,
            )
        )

    for p in criadas:
        _CATALOGO[p.slug] = p
    _MODULOS[app_slug] = nome
    return tuple(criadas)


def existe(slug: str) -> bool:
    return slug in _CATALOGO


def obter(slug: str) -> Permissao:
    try:
        return _CATALOGO[slug]
    except KeyError:
        raise KeyError(
            f"permissão {slug!r} não existe no catálogo. "
            f"Declare-a em backend/<modulo>/permissoes.py. "
            f"Conhecidas: {', '.join(sorted(_CATALOGO)) or '(nenhuma)'}"
        ) from None


def listar() -> list[Permissao]:
    """Catálogo inteiro, ordenado por app e pela ordem das colunas da matriz."""
    ordem = list(ACOES)
    return sorted(_CATALOGO.values(), key=lambda p: (p.app_slug, ordem.index(p.acao)))


def acoes_por_app() -> dict[str, list[str]]:
    """`{app_slug: [ações além de ver]}` — usado para montar a matriz."""
    fora: dict[str, list[str]] = {}
    for p in listar():
        fora.setdefault(p.app_slug, []).append(p.acao)
    return fora


def validar_slugs(slugs: list[str]) -> list[str]:
    """Devolve os slugs que não existem no catálogo (vazio = tudo certo)."""
    return [s for s in slugs if s not in _CATALOGO]


def limpar_catalogo() -> None:
    """Só para testes — o catálogo é global e populado no import dos módulos."""
    _CATALOGO.clear()
    _MODULOS.clear()
