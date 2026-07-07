# Como adicionar um novo app ou módulo ao Hub SuperFrio & Icestar

Guia para quem vai integrar um app novo a esta plataforma — sozinho ou com ajuda de um
agente de IA (Claude Code, Cursor, etc.). Se você é uma IA lendo este arquivo para conduzir
essa implementação, a seção abaixo é **obrigatória** e tem prioridade sobre qualquer outro
instinto de "só resolver logo".

---

## Regras obrigatórias para a IA que for implementar isso

Se você é o agente de IA conduzindo esta implementação, siga sem exceção:

1. **Não crie nem altere nenhum arquivo antes de apresentar um plano em texto simples.**
   Diga o que vai ser criado/alterado, em quais arquivos, e por quê — inclusive decisões
   técnicas que a pessoa pode não ter pensado. Exemplo real: se o HTML enviado tem
   `<script>` inline (sem `src=`), ele vai ser bloqueado pelo CSP do portal — avise que
   vai extrair esse código para um `.js` externo, e só faça isso depois de dizer.
2. **Espere um "OK" explícito antes de aplicar qualquer mudança.** Silêncio, "beleza" vago
   ou a pessoa mudando de assunto não contam como aprovação. Se não está claro, pergunte
   de novo.
3. **Rode o checklist de "Segurança e integridade" (mais abaixo) antes de considerar a
   implementação pronta**, e relate o que foi verificado — mesmo que não tenha achado
   problema nenhum.
4. **Antes de criar a branch, pergunte:** "Você vai criar a branch manualmente pelo GitHub,
   ou quer que eu crie e faça o push?" Não presuma nenhuma das duas opções.
5. **No final, explique o passo a passo de como abrir o Pull Request** (seção "Abrindo o
   Pull Request" abaixo) — mesmo que você tenha permissão técnica para rodar `gh pr create`
   sozinho, a pessoa precisa entender o fluxo, não só ver o resultado.

Essas regras existem porque a plataforma é multi-módulo e compartilha banco, autenticação e
CSP entre apps — uma mudança mal calculada em um módulo pode vazar para os outros.

---

## Passo 0 — qual desses 3 casos é o seu app?

| Seu app é... | Caminho |
|---|---|
| HTML/CSS/JS solto, sem backend, sem banco | **Receita 1** — embutir via iframe |
| Precisa de banco de dados e vai cruzar informação com outros módulos do Hub | **Receita 2** — módulo dentro do monólito |
| Sistema independente, com seu próprio banco/deploy, não precisa trocar dado com o Hub | **Receita 3** — app separado, só linkado |

Na dúvida entre Receita 2 e 3: se você não sabe se vai cruzar dado no futuro, comece pela
Receita 3 (mais simples, mais isolado). Migrar de app separado para módulo depois é possível;
o contrário raramente compensa.

---

## Receita 1 — HTML estático embutido (sem sair do portal)

Já existe um exemplo funcionando: `frontend/governanca/` — uma apresentação estática aberta
dentro de um iframe no próprio portal.

1. Copie a pasta do app para `frontend/<nome-do-app>/`, com um `index.html` na raiz da pasta
   (renomeie o arquivo principal se precisar).
2. **Procure por `<script>` sem `src=`** dentro do HTML (script inline). Se existir, mova o
   conteúdo para um arquivo `.js` separado na mesma pasta e troque para
   `<script src="app.js"></script>`. Isso é necessário porque o CSP do portal
   (`script-src 'self'`) bloqueia script inline por padrão — só `/governanca/` tem uma
   exceção documentada em `backend/main.py`, e essa exceção **não deve ser copiada** sem
   necessidade real (ela amplia a superfície de ataque).
3. Cadastre o app na tela **Administração** do portal (ou no seed, se for parte do setup
   inicial): `url = "/<nome-do-app>/"`, `tipo de acesso = iframe`.
4. Abra o app pelo portal e confira se ele funciona. **Atenção (atualizado em 2026-07-07):**
   o sandbox do iframe hoje é `sandbox="allow-scripts allow-same-origin allow-forms allow-popups
   allow-popups-to-escape-sandbox"` — **com** `allow-same-origin`. Isso reverteu uma decisão
   anterior da auditoria de segurança (item A1 em `docs/AUDITORIA_SEGURANCA.md`) porque apps que
   montam um Worker via Blob (ex.: PDF.js) falham com origem opaca dentro do sandbox restrito.
   Na prática, isso significa que **qualquer app embutido via iframe hoje consegue ler
   localStorage/token do portal** — trade-off aceito conscientemente, não trate como bug. Se um
   app novo te preocupar especificamente por esse motivo, chame a Maria antes de cadastrá-lo
   como iframe; a alternativa mais segura (carregar o worker por arquivo real em vez de Blob,
   sem precisar de `allow-same-origin`) está documentada na auditoria, mas não foi aplicada.

---

## Receita 2 — módulo novo dentro do monólito

A plataforma é um **Modular Monolith**: um processo, um banco (Postgres, schema por
domínio), módulos com fronteira lógica. Regra de ouro: **um módulo nunca lê a tabela de
outro módulo direto — só chama o `service.py` do módulo dono.**

1. Crie o pacote `backend/<nome-do-modulo>/` com `__init__.py`, `models.py`, `service.py`,
   `router.py` — siga o padrão de `backend/portal/` ou `backend/usuarios/` como referência.
2. Registre os models novos em `backend/core/migrations/env.py` (import), depois gere a
   migration:
   ```
   .\.venv\Scripts\python.exe -m alembic revision --autogenerate -m "add <modulo> tables"
   ```
   **Revise o arquivo gerado manualmente** antes de aplicar — autogenerate erra em detalhes
   (índices, tipos, nomes de constraint).
3. Rode a migration local e confirme que sobe limpo:
   ```
   .\.venv\Scripts\python.exe -m alembic upgrade head
   ```
4. Registre o router em `backend/main.py` (`app.include_router(...)`), do mesmo jeito que
   os outros módulos.
5. Se outro módulo precisar de dado do seu, exponha uma função em `service.py` — nunca deixe
   o outro módulo importar seu `models.py` para fazer `SELECT` direto.
6. Escreva testes cobrindo o comportamento novo (siga o padrão da suíte já existente).

---

## Receita 3 — app separado, só linkado

Exemplo já em produção: **Contas Recorrentes** — repositório, banco e deploy próprios; o Hub
só cadastra um card.

1. O app vive no repositório e infraestrutura dele — não precisa tocar neste repositório
   além do passo 2.
2. Cadastre o card na tela **Administração** do portal: `url` apontando para onde o app está
   hospedado, `tipo de acesso = url` (abre em nova aba) ou `iframe` (embutido) se o app for
   acessível pela rede e **não depender de sessão/cookie do portal** (mesma restrição de
   sandbox da Receita 1).

---

## Checklist de segurança e integridade

Aplica-se aos 3 caminhos. A IA deve rodar isso antes de dar a implementação como concluída
e relatar o resultado (não só "ok, tudo certo" — diga o que verificou):

- [ ] Nenhum segredo (senha, token, chave de API) commitado no código, em arquivo de
      config ou no histórico do PR.
- [ ] Nenhuma dependência nova (Python ou JS) adicionada sem necessidade clara — checar
      `requirements.txt` / bibliotecas vendored antes de incluir mais uma.
- [ ] CSP respeitado — nenhum `<script>`/`<style>` inline novo sem justificativa explícita
      (ver Receita 1).
- [ ] Se mexeu perto de autenticação/permissões: `require_admin` / `get_current_user`
      continuam sendo chamados onde já eram, nada foi enfraquecido.
- [ ] Se módulo novo (Receita 2): migration revisada manualmente, testada localmente,
      e a regra de ouro (módulo não lê tabela de outro direto) foi respeitada.
- [ ] Suíte de testes existente rodada localmente e verde antes do PR.
- [ ] Nenhum dado real (de produção ou de cliente) usado em teste, seed ou exemplo.

---

## Abrindo o Pull Request

Nada é mergeado direto em `main` — o repositório exige Pull Request revisado por Code
Owner (ver `.github/CODEOWNERS`).

1. Confirme com a pessoa quem cria a branch (regra 4 no topo deste arquivo). Se a IA for
   criar:
   ```
   git checkout -b feat/<nome-do-app-ou-modulo>
   git add <arquivos-da-mudança>
   git commit -m "feat: adiciona <nome-do-app-ou-modulo>"
   git push -u origin feat/<nome-do-app-ou-modulo>
   ```
2. Abra o PR pelo GitHub (botão "Compare & pull request" depois do push) ou via
   `gh pr create`, se a ferramenta estiver instalada.
3. No corpo do PR, inclua:
   - Qual das 3 receitas foi usada.
   - O checklist de segurança e integridade marcado (o template do PR já traz isso).
   - Como testar localmente.
4. A revisão de Code Owner é obrigatória antes de habilitar o botão de merge — isso é
   forçado pela configuração do repositório, não é combinado por confiança.
