"""Permissões do módulo Projetos IA.

`ver` não aparece aqui: é implícita para todo app cadastrado e mora em
`role_apps` (ver `backend/core/permissoes.py`). A tela é de visibilidade
executiva — qualquer usuário logado enxerga; o que se restringe é `editar`.

Importar a constante daqui é o que garante que o catálogo foi registrado antes
de `require_permissao()` validar o slug — por isso o router importa `EDITAR`
em vez de escrever a string na mão.
"""
from backend.core.permissoes import registrar_modulo

PERMISSOES = registrar_modulo(
    "projetos-ia",
    nome="Projetos IA",
    acoes={
        "editar": (
            "Criar projetos, editar dados/fases e gerenciar o rollout por filial."
        ),
    },
)

EDITAR = "projetos-ia:editar"
