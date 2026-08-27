"""A tela da volumetria — o que dá para provar sem navegador.

Nenhum destes testes abre a tela de verdade: validação visual e de fluxo é
humana, e está declarada como tal no fechamento do lote H2. O que eles pegam é a
classe de bug que **não aparece em nenhum log e não quebra nenhum teste de
backend** — a tela abre em branco, ou abre e não fala com o servidor:

- `<script>` inline: o CSP do portal é `script-src 'self'`. Inline não roda, o
  navegador reclama só no console, e a tela fica muda;
- prefixo da API divergindo do router: 404 em tudo, tela vazia;
- slug de permissão escrito errado: o botão de download desaparece para sempre,
  em silêncio, porque `includes()` nunca casa;
- sobra do porte (`/api/eu`, `/logout`, `#sair`): endpoint que não existe neste
  Hub, e a tela morre na inicialização;
- `Cache-Control` ausente no HTML embutido: depois do deploy o iframe continua
  servindo a versão antiga (já custou um diagnóstico inteiro — ver
  docs/TROUBLESHOOTING_APPS_IFRAME.md);
- back-link ausente: app nosso aberto pelo card abre em tela cheia SEM a barra
  do overlay, então sem ele a única saída é a tecla Esc.
"""
import re
from pathlib import Path

import pytest

from backend.portal.seed import APPS
from backend.volumetria_catering.permissoes import APP_SLUG, EXPORTAR
from backend.volumetria_catering.router import router

TELA = Path(__file__).resolve().parent.parent / "frontend" / "volumetria-catering"
HTML = TELA / "index.html"
JS = TELA / "app.js"


@pytest.fixture(scope="module")
def html():
    return HTML.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def js():
    return JS.read_text(encoding="utf-8")


def test_a_tela_existe_onde_o_card_aponta():
    """O card do seed e o diretório servido têm que ser a mesma coisa: com a URL
    errada o card responde 404 e não há erro em lugar nenhum."""
    app = next(a for a in APPS if a["slug"] == APP_SLUG)
    assert app["url"] == f"/{TELA.name}/"
    assert HTML.is_file()
    assert JS.is_file()


def test_nenhum_script_inline(html):
    """`script-src 'self'`: todo `<script>` desta tela tem que ter `src`.

    Comentários HTML saem antes da varredura: o cabeçalho do arquivo explica
    esta regra e cita a tag ao explicá-la, e comentário não executa."""
    sem_comentarios = re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)
    tags = re.findall(r"<script\b[^>]*>", sem_comentarios)
    assert tags, "a tela precisa carregar o app.js"
    for tag in tags:
        assert "src=" in tag, f"script inline não roda sob o CSP do portal: {tag}"


def test_o_js_entra_com_marca_de_versao(html):
    """Sem o `?v=`, o navegador serve o app.js do cache depois do deploy — o
    HTML revalida (Cache-Control: no-cache), o asset não."""
    assert re.search(r'<script src="app\.js\?v=\d+"></script>', html)


def test_a_tela_tem_saida_para_o_hub(html):
    """A barra do overlay não aparece para app nosso: o back-link é a saída."""
    assert 'href="/" target="_top"' in html
    assert "Voltar ao hub" in html


@pytest.mark.parametrize(
    "sobra",
    ["/api/eu", "/logout", "#sair", "eu-nome", "eu-papel", "link-admin", '"/logo.png"'],
)
def test_nao_sobrou_sessao_da_v3(html, js, sobra):
    """Identidade, logout e link de Administração são da shell do portal. Na V3
    eles viviam no cabeçalho da própria tela, e chamavam endpoints que este Hub
    não tem."""
    assert sobra not in html
    # o comentário do topo do app.js explica a troca e cita `/api/eu` de
    # propósito; o que não pode é sobrar CHAMADA
    assert f"'{sobra}'" not in js
    assert f'"{sobra}"' not in js


def test_o_prefixo_da_api_e_o_do_router(js):
    """Uma cópia do prefixo em JavaScript é inevitável; ela divergir do router
    não é. Trocar o prefixo sem mexer aqui daria 404 em tudo."""
    achado = re.search(r"const API = '([^']+)'", js)
    assert achado, "a tela precisa declarar a base da API num lugar só"
    assert achado.group(1) == router.prefix


def test_a_permissao_do_botao_e_a_do_catalogo(js):
    """Slug errado aqui esconde o download para sempre, sem erro: `includes()`
    simplesmente nunca casa."""
    achado = re.search(r"const PERMISSAO_EXPORTAR = '([^']+)'", js)
    assert achado
    assert achado.group(1) == EXPORTAR


def test_a_tela_baixa_pelo_ticket_e_nao_pelo_header(js):
    """Navegação não carrega `Authorization`. Se a tela voltar a navegar direto
    para /download sem ticket, o download volta a dar 401 na cara do usuário."""
    assert "/download/ticket?" in js
    rotas = {r.path for r in router.routes}
    assert f"{router.prefix}/download/ticket" in rotas
    assert re.search(r"window\.location = API \+ '/download\?' \+ p\.toString\(\)", js)
    assert "p.set('ticket', ticket)" in js


def test_os_tres_bloqueios_tem_mensagem_propria(js):
    """401, 403 e 503 não podem cair no "Recorte recusado", que manda a pessoa
    mexer nos filtros para resolver sessão expirada ou banco fora do ar."""
    for status in ("401", "403", "503"):
        assert status in js
    assert "mostraBloqueio" in js
    # e 401 NÃO navega para o login: dentro do iframe daria frame em branco (a
    # página de login é X-Frame-Options: DENY). O comentário do topo cita o
    # caminho ao explicar a decisão; o que não pode voltar é a NAVEGAÇÃO.
    assert "'/login'" not in js and '"/login"' not in js


def test_o_html_embutido_nao_fica_em_cache_e_pode_ser_iframe(client):
    r = client.get(f"/{TELA.name}/")
    assert r.status_code == 200
    assert r.headers["Cache-Control"] == "no-cache"
    assert r.headers["X-Frame-Options"] == "SAMEORIGIN"
    csp = r.headers["Content-Security-Policy"]
    assert "frame-ancestors 'self'" in csp
    assert "script-src 'self'" in csp  # continua sem 'unsafe-inline'
