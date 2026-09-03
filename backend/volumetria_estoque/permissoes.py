"""Permissões do módulo Volumetria de Estoque.

`ver` não aparece aqui — implícita em `role_apps`, libera Matriz/planilha.
`exportar` é a única ação declarada: baixar o recorte em CSV/xlsx.
"""
from backend.core.permissoes import registrar_modulo

APP_SLUG = "volumetria-estoque"

PERMISSOES = registrar_modulo(
    APP_SLUG,
    nome="Volumetria de Estoque",
    acoes={
        "exportar": (
            "Baixar o recorte da volumetria de estoque em CSV ou xlsx — o "
            "recorte da tela, lido do DW. Consultar a Matriz e a planilha exige "
            "só o acesso ao app."
        ),
    },
)

EXPORTAR = f"{APP_SLUG}:exportar"
