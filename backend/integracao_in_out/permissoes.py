"""Permissões do módulo Integração In/Out.

`ver` não aparece aqui: é implícita para todo app cadastrado e mora em
`role_apps` (ver `backend/core/permissoes.py`).

Mesmo padrão de `backend/processos_abertos/permissoes.py` — o router importa a
constante `EDITAR` em vez de escrever a string, e é esse import que garante que
o catálogo foi registrado antes de `require_permissao()` validar o slug.
"""
from backend.core.permissoes import registrar_modulo

PERMISSOES = registrar_modulo(
    "integracao-in-out",
    nome="Integração In/Out",
    acoes={
        "editar": (
            "Enviar o relatório do JDA e substituir os meses correspondentes na base "
            "compartilhada do dashboard."
        ),
    },
)

EDITAR = "integracao-in-out:editar"
