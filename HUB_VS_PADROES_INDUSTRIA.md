# Hub SuperFrio × padrões da indústria

Documento de referência para apresentar ao time CSC **onde o Hub se encaixa** no que
as grandes empresas fazem, o que ele já cumpre, e o que foi deliberadamente deixado
para depois. Serve de material de governança: mostra que a POC não é improviso — segue
uma categoria de software reconhecida, só que na escala certa para hoje.

> Leitura única. Linguagem para o time CSC, não para devs.

---

## 1. Esse tipo de portal tem nome

O que o Hub faz — uma tela central com os "azulejos" dos sistemas internos, cada um
levando ao app certo, com controle de quem vê o quê — é uma **categoria reconhecida**.
Ela se divide em três sabores, conforme a quem serve:

| Sabor | Para quem | Exemplos no mercado | O Hub se encaixa? |
|---|---|---|---|
| **App Launchpad / SSO Dashboard** | usuário final | Microsoft Entra "My Apps", Okta Dashboard, Google Workspace | **Sim — é o coração do Hub** |
| **Internal Developer Portal (IDP)** | time técnico | Backstage (Spotify) | Em miniatura (a tela de Administração) |
| **Intranet / Portal do Funcionário** | empresa toda | SharePoint, portais de RH | Não é o foco |

**Conclusão:** o Hub é um *App Launchpad* (sabor A) com um toque de *catálogo de
software* (sabor B). Essa mistura é exatamente a "vitrine de governança" que a POC
quer demonstrar.

---

## 2. O que o Hub JÁ cumpre dos padrões

Cada linha abaixo é uma prática que as grandes empresas usam — e que o Hub já tem
implementada hoje.

| Conceito da indústria | O que o Hub tem | Equivale a… |
|---|---|---|
| **Catálogo de apps** | tabela `apps` + seções + CRUD pela tela Admin | "Software Catalog" do Backstage |
| **Launchpad / azulejos** | cards por seção que abrem o app (`url` ou `iframe`) | Entra My Apps / Okta Dashboard |
| **RBAC (permissão por papel)** | roles agrupam apps; usuários recebem roles; `is_admin` libera tudo | modelo padrão de portal corporativo |
| **Boundary de autenticação** | `authenticate_user()` único; campo `auth_source` já no schema | ponto de plugar SSO/AD depois sem reescrever |
| **Governança = deploy reprodutível** | Docker + Git + tags; "o que está na VM = o que está na `main`" | GitOps / Infraestrutura como Código |
| **Auditabilidade de cadastro** | toggle ativo/inativo em vez de DELETE; `atualizado_em` carimbado | trilha de mudanças, padrão de governança |
| **Hardening de segurança** | CSP, security headers, rate limit (slowapi), JWT + bcrypt | o básico bem-feito que muita POC pula |
| **Migração segura** | `init_db()` idempotente, seed com `INSERT OR IGNORE` | rodar 2× sem corromper estado |

Isso é bastante coisa **certa**. A arquitetura não é de brinquedo — ela apenas roda
em escala menor.

---

## 3. Onde o Hub diverge — e por que está correto

Estas **não são falhas**: são escolhas de escala conscientes (várias estão escritas
como "fora de escopo" no `MEMORY.md`). O importante é que cada uma tem uma **porta de
saída** já preparada na arquitetura.

| Divergência | Como é nas grandes | Por que está OK na POC | Porta de saída já aberta |
|---|---|---|---|
| **Banco = SQLite (arquivo)** | servidor de banco dedicado (PostgreSQL/SQL Server) | dezenas de usuários internos: SQLite dá conta | `SUPERFRIO_DB_PATH` é variável → troca pra SQL Server |
| **Login próprio (sem SSO)** | login único corporativo (Entra/Okta) | POC valida o portal antes do esforço de SSO | boundary `authenticate_user()` + `auth_source` prontos |
| **1 VM, 1 container** | réplicas, alta disponibilidade, balanceamento | uso interno de CSC não exige | deploy por Docker escala de 1 pra N apps |
| **Apps são links/iframes** | metadados ricos (dono, docs, versão, saúde) | listar e permissionar já cumpre o objetivo | schema de apps pode ganhar campos depois |
| **Sem auditoria de cliques** | rastreio de quem abriu o quê e quando | marcado como "próxima POC" | padrão `historico_*` da casa encaixa direto |

> **A regra que separa POC boa de protótipo descartável:** a arquitetura deixou as
> portas abertas. O Hub deixou — auth num boundary único, caminho do banco em variável,
> deploy por Git/Docker. Cada degrau de crescimento está destravado, não precisa
> reescrever.

---

## 4. Resumo de uma frase para a apresentação

> O Hub segue os mesmos **princípios** das plataformas das grandes empresas — catálogo
> de apps, controle de acesso por papel, governança por deploy reprodutível — na
> **escala certa para o CSC hoje**, e com **rota de upgrade** clara para cada degrau
> que as grandes usam. É exatamente o que uma POC de governança deveria provar.

O caminho de evolução degrau a degrau está em [ROADMAP_EVOLUCAO.md](ROADMAP_EVOLUCAO.md).

---

## 5. Para estudar / referência

**O "launchpad" corporativo (pra onde o Hub cresce no mundo Microsoft):**
- Microsoft Entra — My Apps portal: https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/myapps-overview
- Okta — Employee SSO to Apps: https://www.okta.com/solutions/employee-sso-to-apps/

**O catálogo de software (a parte "governança"):**
- Backstage (Spotify, open-source): https://backstage.io/
- Backstage no GitHub: https://github.com/backstage/backstage
- Conceito de Internal Developer Portal: https://internaldeveloperplatform.org/developer-portals/backstage/

**Arquitetura e banco em sistemas grandes (a primeira dúvida — "onde mora o banco"):**
- ByteByteGo — system-design-101 (visual, gratuito): https://github.com/ByteByteGoHq/system-design-101
- Designing Data-Intensive Applications — Martin Kleppmann (o livro de referência): https://www.oreilly.com/library/view/designing-data-intensive-applications/9781098119058/
- Matheus Fidelis — System Design: Databases (em português): https://fidelissauro.dev/databases/
