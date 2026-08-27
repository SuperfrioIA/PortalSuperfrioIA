"""Volumetria de catering — consulta SOMENTE LEITURA sobre o banco da nuvem-ia.

Módulo de consulta (Receita 2 do CONTRIBUTING.md, com a fonte de dados num banco
externo). A tela da V3 do projeto nuvem-ia entra no Hub para ganhar o SSO, a
matriz de permissões (`exportar`) e o log de acesso — sem mover o dado.

O que este módulo NÃO é dono de, e por quê (docs/PLANO_VOLUMETRIA_CATERING.md):

- **do schema `cat_*`**: as tabelas e a cadeia de migrations (0019–0024+) ficam
  no repositório nuvem-ia. Aqui vive uma CÓPIA do contrato de colunas
  (`contrato.py`) e uma verificação de drift (`schema.py`) que falha nomeando a
  coluna quando a cópia e o banco divergirem. Mudança de schema é sempre duas
  PRs coordenadas — migration lá, contrato aqui;
- **da escrita**: a carga do DW Oracle roda no cron da VM da nuvem-ia. O Hub
  conecta com um role próprio (`hub_leitura`, só SELECT) e, por cima, abre toda
  conexão com `default_transaction_read_only=on` (`conexao.py`). Um UPDATE
  escrito por engano é recusado pelo banco, não por promessa;
- **do startup do Hub**: a conexão é por request. `VOLUMETRIA_DB_URL` ausente
  ou banco fora do ar degradam SÓ este card (503 com mensagem clara); lifespan e
  `/api/health` não dependem daqui.

A única tabela que este módulo escreve é a dele, no banco do Hub:
`volumetria_downloads` (auditoria de download, migration 0007).

Origem do porte: nuvem-ia `main` em 27/ago/2026 (após o V3.7.3), pasta
`catering/consulta/` + `catering/contrato.py` + endpoints de consulta de
`catering/app.py`.
"""
