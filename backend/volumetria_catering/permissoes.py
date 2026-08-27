"""Permissões do módulo Volumetria de Catering.

`ver` não aparece aqui: é implícita para todo app cadastrado e mora em
`role_apps` (ver `backend/core/permissoes.py`). É ela que libera a consulta —
Matriz, planilha e opções de filtro exigem login + `ver` do app.

`exportar` é a única ação declarada: baixar o recorte em CSV/xlsx. Na tela
antiga (V3, porta 8003) o download era liberado para qualquer pessoa logada;
aqui ele passa a ser uma célula da matriz de acesso, que foi um dos motivos de
trazer a tela para o Hub.
"""
from backend.core.permissoes import registrar_modulo

APP_SLUG = "volumetria-catering"

PERMISSOES = registrar_modulo(
    APP_SLUG,
    nome="Volumetria de Catering",
    acoes={
        "exportar": (
            "Baixar o recorte da volumetria de catering em CSV ou xlsx — a linha "
            "inteira do DW, no recorte dos filtros da tela. Consultar a Matriz e a "
            "planilha exige só o acesso ao app."
        ),
    },
)

EXPORTAR = f"{APP_SLUG}:exportar"
