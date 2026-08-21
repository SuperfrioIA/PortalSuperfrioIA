# Hub SuperFrio & Icestar

Antes de adicionar um novo app ou módulo a esta plataforma, leia
[CONTRIBUTING.md](CONTRIBUTING.md) — ele tem as regras obrigatórias para IA (apresentar plano
antes de agir, aguardar aprovação explícita, checklist de segurança, e o fluxo de branch/PR)
e as 3 receitas de integração (HTML estático embutido, módulo dentro do monólito, app
separado só linkado).

Antes de iniciar processos, executar testes ou validar localmente, leia
`docs/EXECUCAO_LOCAL.md` — é a fonte oficial de como subir, testar e encerrar este
repositório no Windows/PowerShell (modos de execução, portas, banco SQLite, e como
identificar e encerrar processos órfãos).

Ao terminar um lote, o deploy é **humano** e o procedimento está em
`docs/DEPLOY_VM.md` — inclusive a regra de quando é preciso rebuildar a imagem (todo
arquivo que é `COPY` no Dockerfile: `backend/`, `frontend/`, `requirements.txt` e o
`CHANGELOG.md`). Entregue sempre o bloco de comandos pronto junto do link do PR; a IA
não executa deploy.

Login com Microsoft Entra ID está **ativo em produção**: operação, diagnóstico das
recusas e rollback em `docs/ATIVACAO_SSO_ENTRA.md`.
