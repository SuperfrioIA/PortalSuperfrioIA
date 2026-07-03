# Changelog

## [0.3.0] — 2026-07-02
### Adicionado
- Modularização em Modular Monolith — módulos portal, auth e usuarios independentes (Lote 3)
- Postgres como banco de dados principal na VM (Lote 2)
- SQLAlchemy + Alembic substituem acesso SQLite direto; migrations versionadas (Lote 1)
- Apostila de arquitetura e vault Obsidian documentados no MEMORY.md

## [0.2.1] — 2026-07-01
### Adicionado
- Apresentação Governance TI embutida no portal como overlay em tela cheia

## [0.2.0] — 2026-06-23
### Corrigido
- Tela de admin trata sessão expirada (401) e redireciona automaticamente para o login
- Correção de flash de tela branca na inicialização do portal

## [0.1.3] — 2026-06-22
### Adicionado
- Porta de host configurável via variável HOST_PORT no .env (padrão 8000)
- Documentação interna movida para docs/ e excluída do git
### Segurança
- frame-src do CSP configurável via variável SUPERFRIO_FRAME_SRC — remove wildcard *
### Alterado
- Context manager db() e helpers consolidados no admin; suite de testes integrada

## [0.1.2] — 2026-06-11
### Adicionado
- Vitrine 3D inicializada com Three.js

## [0.1.1] — 2026-06-09
### Alterado
- Identidade visual alinhada à marca IceStar | SuperFrio (tema claro)
- Internacionalização PT/ES com troca de idioma e logo combinado

## [0.1.0] — 2026-05-29
### Adicionado
- Portal SuperFrio POC — hub interno com login JWT, seções, apps, roles e usuários (Lotes 1–4)
