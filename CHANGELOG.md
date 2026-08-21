# Changelog

## [0.6.0] — 2026-08-21
### Adicionado
- Entrar com Microsoft — login com a conta corporativa (Entra ID), sem senha nova para decorar. Em máquina corporativa já autenticada, entra sem pedir senha
- Filial no cadastro de usuário — cada pessoa passa a ter lotação, e a filial do CSC entrou no catálogo
- Filtros em toda a Administração — busca por texto e situação em todas as abas, mais filial e role em Usuários e região e unidade de negócio em Filiais
- Cabeçalho padrão nos apps embutidos — Mapa IA e Governance TI agora têm "Voltar ao hub" à esquerda e a marca à direita, como as outras telas
### Corrigido
- App embutido abrindo em branco — acontecia quando a URL era cadastrada sem a barra no fim, caso do Mapa Estatístico
- Duas barras de rolagem — a página de trás continuava rolando junto com o app aberto em tela cheia
- "Voltar ao hub" não funcionava — o link estava sendo bloqueado silenciosamente em todo app aberto pelo portal
- Login de todos podia ser bloqueado por um minuto — as tentativas erradas de uma pessoa contavam para a empresa inteira
- Tela branca com texto técnico — aparecia ao usar o botão Voltar do navegador depois de entrar pela Microsoft
- Acesso desativado dava erro de sistema — agora a pessoa lê que o acesso está desativado e a quem pedir
### Alterado
- Cadastro sem senha para quem usa a Microsoft — o e-mail passou a ser obrigatório, porque é ele que liga a pessoa à conta corporativa
- Primeiro acesso exige cadastro prévio — sem cadastro, a pessoa recebe orientação para pedir acesso ao administrador
- Lista de usuários mais enxuta — as colunas "Roles" e "O que isso dá de acesso" viraram uma só, com os nomes das roles no detalhe
- Login local virou acesso administrativo — fica recolhido na tela de entrada, para emergência

## [0.5.0] — 2026-07-26
### Adicionado
- Matriz de acesso na tela de Administração — apps nas linhas, ações nas colunas (Ver, Editar, Exportar, Administrar), com marcação por coluna e por seção
- Catálogo de permissões declarado em código — cada módulo declara suas ações e um slug errado passa a derrubar o boot em vez de virar erro silencioso
- Endpoint único `GET /api/auth/me/permissoes` para o frontend consultar tudo que o usuário pode fazer, no lugar de um `/pode-editar` por app
- Coluna "Permissões de ação" na lista de roles e coluna "O que isso dá de acesso" na lista de usuários
- Passo obrigatório de declaração de permissão no guia de contribuição e no template de PR
### Corrigido
- Desativar uma role não revogava o acesso aos apps — a checagem ignorava `roles.ativo` e mantinha os cards visíveis para quem já tinha a role
### Alterado
- Processos Abertos passou a exigir a permissão `processos-abertos:editar` no lugar de uma role de nome fixo; ambientes que já tinham a role antiga são migrados automaticamente
- `GET /api/processos-abertos/pode-editar` está depreciado e será removido depois que o app embutido estiver no endpoint global

## [0.4.0] — 2026-07-07
### Adicionado
- Timeline de changelog e sistemas no portal — nova tela "Novidades" com o histórico de mudanças em linha do tempo
- Guia de contribuição e CODEOWNERS documentados no repositório
### Corrigido
- Changelog não aparecia na tela Novidades em produção — CHANGELOG.md agora incluído na imagem Docker
- Espaçamento entre os cards da timeline de novidades
- Clipping das bordas nas timelines de changelog e sistemas

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
