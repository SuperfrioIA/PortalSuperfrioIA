"""Permissões do módulo Processos Abertos.

`ver` não aparece aqui: é implícita para todo app cadastrado e mora em
`role_apps` (ver `backend/core/permissoes.py`).

Importar as constantes daqui é o que garante que o catálogo foi registrado antes
de `require_permissao()` validar o slug — por isso o router importa `EDITAR`
em vez de escrever a string na mão.
"""
from backend.core.permissoes import registrar_modulo

PERMISSOES = registrar_modulo(
    "processos-abertos",
    nome="Processos Abertos",
    acoes={
        "editar": (
            "Enviar uma semana nova e substituir a existente no histórico compartilhado."
        ),
    },
)

EDITAR = "processos-abertos:editar"
