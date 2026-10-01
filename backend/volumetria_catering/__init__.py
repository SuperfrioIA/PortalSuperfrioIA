"""Volumetria de catering — consulta SOMENTE LEITURA sobre o DW Oracle.

Módulo de consulta (Receita 2 do CONTRIBUTING.md, com a fonte de dados num banco
externo). A tela da V3 do projeto nuvem-ia entra no Hub para ganhar o SSO, a
matriz de permissões (`exportar`) e o log de acesso — e, desde o lote C6 do
plano (`docs/PLANO_VOLUMETRIA_DW_DIRETO.md`), lê o DW direto, sem o Postgres
intermediário da nuvem-ia.

O que este módulo NÃO é dono de, e por quê:

- **do schema do DW**: as tabelas `FATO_VOL_*_CAT_V01` e o processo que as
  alimenta são do lado do DW. Aqui vive uma CÓPIA do contrato de colunas
  (`contrato.py`) e uma verificação de drift (`schema_dw.py`) que falha nomeando
  a coluna quando a cópia e o DW divergirem;
- **da escrita**: o Hub conecta com um usuário de leitura (`DW_LEITURA_USUARIO`)
  e nunca emite comando que não seja `SELECT` (`conexao_dw.py`, com a guarda
  estática e a de runtime nos testes). Escrita impedida de verdade é o GRANT do
  lado do DW;
- **do startup do Hub**: a conexão é por request. Credencial ausente ou DW fora
  do ar degradam SÓ este card (503 com mensagem clara); lifespan e
  `/api/health` não dependem daqui.

A única tabela que este módulo escreve é a dele, no banco do Hub:
`volumetria_downloads` (auditoria de download, migration 0007).

Origem do porte: nuvem-ia `main` em 27/ago/2026 (após o V3.7.3), pasta
`catering/consulta/` + `catering/contrato.py` + endpoints de consulta de
`catering/app.py`.
"""
