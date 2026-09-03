"""Volumetria de Estoque de Catering — módulo de consulta somente leitura
sobre `DM_VOLUMETRIA.FATO_VOL_EST_CAT_V01`, no DW Oracle.

Irmão de `backend/volumetria_transporte/` (mesmo padrão: sem base comum,
cada módulo com sua cópia de conexão/ticket/download). A diferença real
está em `matriz.py`: aqui a Matriz agrega em modo **posição** (a foto do
último dia com dado de cada mês), não soma — porque a tabela é um saldo
diário, não um fluxo. Ver "Estoque é saldo" e "Resultado do T0" em
`docs/PLANO_VOLUMETRIA_TRANSPORTE_ESTOQUE.md`.
"""
