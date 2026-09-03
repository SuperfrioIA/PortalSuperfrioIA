"""Catálogo de permissões da plataforma — orquestra o catálogo de cada módulo.

Espelha `backend/seed.py`: o core não conhece domínio nenhum, então é aqui, um
nível acima, que a lista de módulos é montada.

Existe por um motivo prático: o catálogo é populado no *import* de cada
`<modulo>/permissoes.py`. Um módulo que ninguém importou some do catálogo, e a
tela de Administração exibiria uma matriz incompleta. Chamar `carregar()` no
startup (e nos testes) elimina essa dependência de ordem de import.

**Ao criar um módulo com permissões, acrescente o import aqui.** O teste
`test_permissoes_catalogo.py::test_todo_modulo_esta_no_agregador` cobra isso.
"""
from backend.integracao_in_out import permissoes as integracao_in_out_permissoes
from backend.processos_abertos import permissoes as processos_abertos_permissoes
from backend.projetos_ia import permissoes as projetos_ia_permissoes
from backend.volumetria_catering import permissoes as volumetria_catering_permissoes
from backend.volumetria_transporte import permissoes as volumetria_transporte_permissoes

_MODULOS = (
    processos_abertos_permissoes,
    integracao_in_out_permissoes,
    projetos_ia_permissoes,
    volumetria_catering_permissoes,
    volumetria_transporte_permissoes,
)


def carregar() -> None:
    """Garante que todos os catálogos de módulo foram registrados.

    O trabalho real acontece no import (no topo deste arquivo); a função existe
    para o startup ter um ponto explícito de chamada em vez de depender de
    import com efeito colateral.
    """
    for modulo in _MODULOS:
        assert modulo.PERMISSOES is not None
