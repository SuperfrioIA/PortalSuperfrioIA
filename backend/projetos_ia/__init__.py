"""Projetos IA — visibilidade executiva do portfólio de projetos de IA.

Dono das tabelas `projetos`, `projeto_fases`, `filiais` e `projeto_rollout`.
Outros módulos acessam esses dados só via `backend.projetos_ia.service` (regra
de ouro: nunca SELECT direto na tabela alheia).

Não é ferramenta de gestão de projetos: sem tarefas, sem dependências. Mostra
em que fase (das 7 macrofases) cada projeto está, o próximo marco e o rollout
por filial — tudo derivado de datas, sem campo de status manual (ver
`service.py`).
"""
