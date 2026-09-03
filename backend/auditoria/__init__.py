"""Auditoria funcional — quem fez o quê, quando, com que resultado.

Trilha própria, separada de três coisas que fica fácil confundir com ela:

- **logs técnicos** (stdout do container, `backend.acesso`): o que o processo
  fez, sem retenção longa, sem garantia de imutabilidade;
- **métricas operacionais** (saúde, tempo de resposta, CPU/memória): roadmap,
  não faz parte deste módulo;
- **dados de aderência** (quantas pessoas usam cada app, quantos acessos por
  semana): derivados desta trilha, mas agregados — roadmap também.

Este módulo é só leitura administrativa: expõe `service.registrar()` e
`service.listar()`/`exportar_csv()`. Nenhum caminho de código expõe UPDATE
ou DELETE sobre `auditoria_eventos` — a tabela é append-only também por
trigger de banco (migration 0008), como segunda camada.

Não conhece nenhum módulo de domínio (mesma regra de `core/http.py` e
`core/permissoes.py`): quem chama `registrar()` é sempre o módulo dono do
evento, nunca o contrário.
"""
