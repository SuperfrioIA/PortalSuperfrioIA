## O que foi feito

<!-- descreva a mudança em 2-3 linhas -->

## Qual caminho da plataforma isso segue?

- [ ] Receita 1 — HTML estático embutido (iframe)
- [ ] Receita 2 — módulo novo dentro do monólito
- [ ] Receita 3 — app separado, só linkado

Ver [CONTRIBUTING.md](../CONTRIBUTING.md) para o detalhe de cada receita.

## Checklist de segurança e integridade

- [ ] Nenhum segredo (senha/token/chave) commitado
- [ ] Nenhuma dependência nova sem necessidade clara
- [ ] **Permissão declarada**: toda rota nova tem guarda explícita (`get_current_user`,
      `require_admin` ou `require_permissao`), e toda ação nova está no catálogo
      (`backend/<modulo>/permissoes.py`). Se a rota é pública de propósito, diga por quê.
- [ ] CSP respeitado (sem `<script>`/`<style>` inline novo sem justificativa)
- [ ] Se módulo novo: migration revisada manualmente e testada localmente (`alembic upgrade head`)
- [ ] Mutação administrativa nova grava evento de auditoria com diff (`backend/auditoria`, ver
      `docs/AUDITORIA_FUNCIONAL.md`); se não grava nenhum evento, o motivo está explicado acima
- [ ] Suíte de testes rodada localmente e verde
- [ ] Regra de ouro respeitada (módulo não lê tabela de outro módulo direto — só via `service.py`)
- [ ] Nenhum dado real de produção usado em teste/seed/exemplo

## Como testar localmente

<!-- comandos/passos para revisar rodar isso -->
