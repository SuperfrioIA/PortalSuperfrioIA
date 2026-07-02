"""Portal — catálogo de seções e apps + home filtrada por permissão.

Dono das tabelas `secoes` e `apps`. Outros módulos acessam apps SÓ via
`backend.portal.service` (regra de ouro: nunca SELECT na tabela alheia).
"""
