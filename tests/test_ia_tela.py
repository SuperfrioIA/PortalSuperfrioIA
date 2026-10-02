"""SuperfrioIA — a tela nativa, verificada por leitura do código (sem navegador).

A validação no navegador (estados, console sem erro de CSP, requisições) é feita à
parte, com Playwright, e vai no relatório do lote. Aqui ficam as garantias que a
leitura estática dá de graça e que uma edição descuidada quebraria: i18n nos dois
idiomas, nada de handler inline (CSP `script-src 'self'`), cache-bust, e dado da API
sempre escapado antes de virar HTML.
"""
import pathlib
import re

FRONT = pathlib.Path(__file__).resolve().parent.parent / "frontend"
HTML = (FRONT / "index.html").read_text(encoding="utf-8")
JS = (FRONT / "js" / "superfrioia.js").read_text(encoding="utf-8")
I18N = (FRONT / "js" / "i18n.js").read_text(encoding="utf-8")
CSS = (FRONT / "css" / "styles.css").read_text(encoding="utf-8")
APP = (FRONT / "js" / "app.js").read_text(encoding="utf-8")


def _chaves_do_dicionario(idioma: str) -> dict[str, str]:
    """As chaves `ia.*` de um bloco do DICT (`pt: {` ou `es: {`)."""
    inicio = I18N.index(f"    {idioma}: {{")
    fim = I18N.index("\n    },", inicio)
    bloco = I18N[inicio:fim]
    return dict(re.findall(r'"(ia\.[a-z_.0-9]+)":\s*"((?:[^"\\]|\\.)*)"', bloco))


def _tela_html() -> str:
    inicio = HTML.index('id="screen-superfrioia"')
    return HTML[inicio:HTML.index("<!-- Modal do Projetos IA", inicio)]


# ================================================================== i18n
def test_as_chaves_ia_existem_nos_dois_idiomas_e_sao_as_mesmas():
    pt, es = _chaves_do_dicionario("pt"), _chaves_do_dicionario("es")
    assert pt and set(pt) == set(es), sorted(set(pt) ^ set(es))
    assert all(v.strip() for v in pt.values()) and all(v.strip() for v in es.values())


def test_texto_novo_nao_e_igual_nos_dois_idiomas_salvo_nome_proprio():
    pt, es = _chaves_do_dicionario("pt"), _chaves_do_dicionario("es")
    iguais = {k for k in pt if pt[k] == es[k]}
    # o nome do produto, e palavras que são iguais em português e espanhol
    assert iguais <= {"ia.title", "ia.ia", "ia.admin.vigentes", "ia.admin.col.motivo", "ia.status.vencida"}, iguais


def test_toda_chave_usada_pela_tela_existe_no_dicionario():
    pt = _chaves_do_dicionario("pt")
    usadas = set(re.findall(r'\bt\("(ia\.[a-z_.0-9]+)"\)', JS)) | set(re.findall(r'\btn\("(ia\.[a-z_.0-9]+)"', JS))
    usadas |= set(re.findall(r'data-i18n="(ia\.[a-z_.0-9]+)"', _tela_html()))
    usadas |= {f"ia.acesso.{c}.{p}" for c in ("sem_concessao", "pendente", "negada", "revogada", "vencida", "sem_ver")
               for p in ("titulo", "texto")}
    usadas |= {f"ia.status.{e}" for e in ("liberado", "sem_concessao", "pendente", "negada", "revogada", "vencida", "sem_ver_sistema")}
    faltando = usadas - set(pt)
    assert not faltando, sorted(faltando)


def test_o_estado_de_acesso_do_servidor_tem_rotulo_traduzido_para_todos_os_valores():
    from backend.ia import permissoes  # noqa: F401  (o conjunto abaixo é o que estado_do_acesso devolve)
    pt = _chaves_do_dicionario("pt")
    for estado in ("liberado", "sem_concessao", "pendente", "negada", "revogada", "vencida", "sem_ver_sistema"):
        assert f"ia.status.{estado}" in pt


# ================================================================== CSP e HTML
def test_a_tela_nao_tem_script_inline_nem_handler_inline():
    html = _tela_html()
    assert "<script" not in html.lower()
    assert not re.search(r"\son[a-z]+\s*=", html, re.I), "handler inline no HTML da tela"
    # o JS monta HTML por template: nenhum atributo de evento dentro dele (usa addEventListener)
    assert not re.search(r"\son(click|change|input|keydown|keyup|submit|load|error|focus|blur|mouse[a-z]*)\s*=", JS, re.I)
    assert "javascript:" not in html.lower() and "javascript:" not in JS.lower()


def test_o_js_nao_usa_eval_nem_escreve_html_cru_de_fora():
    for proibido in ("eval(", "new Function", "document.write", "insertAdjacentHTML", "outerHTML"):
        assert proibido not in JS, proibido
    assert not re.search(r'\bon(click|change|input|keydown|submit)\s*=\s*["\'\\]', JS)


def test_o_html_da_tela_tem_os_ids_que_o_js_usa():
    html = _tela_html()
    for ident in ("screen-superfrioia", "btn-back-from-superfrioia", "ia-body"):
        assert f'id="{ident}"' in html
    for chamado in ('$("ia-body")', '$("btn-back-from-superfrioia")', '$("screen-portal")', '$("screen-superfrioia")'):
        assert chamado in JS
    assert 'class="superfrioia hidden"' in html                 # nasce escondida


def test_o_script_e_carregado_depois_do_app_e_com_versao():
    ordem = [m for m in re.findall(r'<script src="js/([a-z]+)\.js\?v=(\d+[a-z]?)"', HTML)]
    nomes = [n for n, _ in ordem]
    assert nomes.index("superfrioia") > nomes.index("app")
    assert dict(ordem)["superfrioia"] == "20261002a"


def test_cache_bust_foi_subido_nos_assets_que_mudaram():
    """Regra do repositório: mexeu em frontend/css|js, sobe o `?v=` no index.html."""
    assert 'css/styles.css?v=20261001a' in HTML
    assert 'js/i18n.js?v=20261002a' in HTML and 'js/app.js?v=20261001a' in HTML
    # e o que NÃO mudou não foi bumpado à toa
    assert 'js/admin.js?v=20260903a' in HTML and 'js/projetos.js?v=20260730b' in HTML


# ============================================ dado da API é sempre escapado
def test_nenhuma_interpolacao_de_dado_da_api_entra_no_html_sem_escapar():
    """`${m.texto}`, `${d.nome}`... crus são o caminho do XSS: dado vindo do servidor
    (nome de cliente, texto de resposta) só vira HTML dentro de `escapeHtml(...)`,
    `texto(...)` ou `Number(...)`. Interpolação que começa por propriedade de objeto
    da API é reprovada."""
    # só a propriedade crua, sozinha dentro de `${ }`: condicional booleano
    # (`${c.id === x ? " active" : ""}`) e chamada a helper não entram aqui
    cruas = re.findall(r"\$\{\s*[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+\s*\}", JS)
    # as únicas três revistas, todas fora de HTML: cabeçalho Authorization, mensagem de
    # erro "HTTP 500" e chave de dicionário (já dentro de escapeHtml(t(...)))
    revistas = {"${SF.state.token}", "${res.status}", "${d.acesso.estado}"}
    assert [c for c in cruas if c not in revistas] == [], cruas


def test_o_texto_da_resposta_so_vira_html_por_texto_que_escapa_antes():
    corpo = re.search(r"function texto\(s\) \{(.*?)\n  \}", JS, re.S).group(1)
    assert corpo.index("escapeHtml(") < corpo.index("<strong>")        # escapa ANTES de criar a tag
    assert "innerHTML" not in corpo


def test_largura_da_barra_e_numero_limitado_e_nao_texto_da_api():
    assert "Math.max(0, Math.min(100, Number(i.largura) || 0))" in JS


def test_classe_de_aviso_vem_de_lista_branca():
    assert 'const seguros = ["ia-aviso--escopo", "ia-aviso--permissao", "ia-aviso--indisponivel", "ia-aviso--vazio"]' in JS


# ======================================================== CSS e integração
def test_toda_classe_ia_usada_no_js_ou_no_html_existe_no_css():
    usadas = set(re.findall(r'class="(?:[^"$]*\s)?(ia-[a-z-]+)', JS)) | set(re.findall(r'\b(ia-[a-z-]+)\b(?=[^"]*")', _tela_html()))
    usadas |= set(re.findall(r'"(ia-aviso--[a-z]+)"', JS))
    definidas = set(re.findall(r"\.(ia-[a-z-]+)", CSS))
    faltando = {c for c in usadas if c not in definidas and not c.startswith("ia-body")}
    assert not faltando, sorted(faltando)


def test_o_card_abre_a_tela_pelo_slug_e_projetos_ia_continua_abrindo():
    assert 'app.slug === "superfrioia"' in APP and "window.SF.openSuperfrioIa()" in APP
    assert "window.SF.openProjetosIa()" in APP                          # o caminho antigo segue intacto


def test_o_login_e_a_sessao_expirada_escondem_a_tela():
    assert 'tela().classList.add("hidden")' in JS and "SF.logout" in JS


def test_a_tela_responde_em_largura_de_celular():
    assert "@media (max-width: 880px) { .ia-layout { grid-template-columns: 1fr; }" in CSS


# ======================== achados da validação no navegador (Playwright) ========================
def test_erro_de_formulario_usa_classe_que_aparece_sozinha_e_nao_a_form_error():
    """`.form-error` só aparece com a classe `visible`: o erro do pedido de acesso ficava mudo."""
    assert 'class="form-error"' not in JS
    assert 'class="ia-erro"' in JS and ".ia-erro:empty { display: none; }" in CSS


def test_pedir_acesso_sem_motivo_e_barrado_na_tela_com_mensagem_e_foco():
    corpo = JS[JS.index("async function pedirAcesso()"):]
    corpo = corpo[:corpo.index("\n  }\n")]
    assert "if (!motivo)" in corpo and 'ia.acesso.motivo.obrigatorio' in corpo and ".focus()" in corpo
    assert corpo.index("if (!motivo)") < corpo.index("await api(")


def test_o_selo_do_provedor_de_teste_sai_do_dicionario_nao_do_texto_do_servidor():
    """O servidor manda "provedor de teste" em português; em ES o selo tinha que traduzir."""
    assert 'meta.provedor === "falso" ? t("ia.selo.teste")' in JS
    assert 'd.provedor.nome === "falso" ? t("ia.selo.teste")' in JS


def test_conversas_de_acesso_revogado_aparecem_fechadas():
    assert 'class="ia-conversa fechada"' in JS and "c.acesso_revogado" in JS
    assert ".ia-conversa.fechada" in CSS


def test_a_tela_nao_estoura_a_largura_do_celular():
    assert ".ia-layout > *, .ia-painel, .ia-thread, .ia-msg" in CSS and "min-width: 0" in CSS
    assert "grid-template-columns: minmax(0, 1fr)" in CSS
    assert "overflow-x: auto" in CSS


def test_a_bolha_do_usuario_passa_a_mostrar_a_pergunta_ja_mascarada():
    assert "bolha.texto = r.pergunta" in JS


# ================================================= Lote 3: texto retido pelo verificador
def test_texto_retido_pelo_verificador_mostra_aviso_traduzido_e_ainda_mostra_os_blocos_do_hub():
    corpo = JS[JS.index('if (estado === "numero_nao_verificado")'):]
    corpo = corpo[:corpo.index("\n    }\n")]
    assert 't("ia.aviso.verificador")' in corpo and 't("ia.aviso.verificador.texto")' in corpo
    assert "m.blocos" in corpo and "blocoHtml" in corpo
    assert "texto(m.texto)" not in corpo and "${m.texto}" not in corpo   # o texto do modelo não é exibido
    pt, es = _chaves_do_dicionario("pt"), _chaves_do_dicionario("es")
    for chave in ("ia.aviso.verificador", "ia.aviso.verificador.texto"):
        assert pt[chave] and es[chave] and pt[chave] != es[chave]
