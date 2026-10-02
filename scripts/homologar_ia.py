"""Homologação do SuperfrioIA no ambiente de TESTE (Lote 4): roda a lista de verificação contra um Hub no ar.

Quem executa na VM de DEV é a Duda, de um terminal dela: a IA não conecta em ambiente nenhum além do
local. O script só faz chamadas HTTP à API do Hub (nada de SSH, banco ou DW), com `urllib` da
biblioteca padrão, e escreve um relatório em Markdown (`docs/`, ignorado pelo Git).

Passos (escolha com `--passos`, padrão: todos os que não exigem mexer no ambiente):

  saude        o Hub responde `/api/health`
  dominios     o usuário vê o domínio; mostra o provedor (falso ou anthropic) e o estado do acesso
  pergunta     faz uma pergunta e confere que o número do texto é o mesmo do quadro que o Hub montou
  sem-concessao   um usuário SEM concessão é recusado com mensagem neutra (precisa de --sem-concessao-usuario)
  revogacao    (admin) revoga a concessão e confere a recusa IMEDIATA; depois pede e aprova de novo
  auditoria    (admin) confere os eventos `ia.*` na trilha e que nenhum guarda texto de pergunta ou resposta
  gabarito     compara o número da TELA (anotado por você) com o da resposta da IA (precisa de --gabarito)
  desligar     manual: você muda `IA_HABILITADO=false` na VM e reinicia; o script confere o 404 e o card
               sumido, e depois a volta (única parte que não dá para automatizar sem tocar na VM)

Senhas: nunca por argumento. Vêm de `getpass` (digitada, sem eco) ou das variáveis `IA_HOMOLOG_SENHA`,
`IA_HOMOLOG_SENHA_ADMIN`, `IA_HOMOLOG_SENHA_SEM_CONCESSAO`. Nenhuma senha, token ou texto de pergunta vai
para o relatório. O alvo é impresso antes de qualquer chamada e exige `--confirmo-ambiente-de-teste`.

Uso (PowerShell):

    .\\.venv\\Scripts\\python.exe scripts\\homologar_ia.py --url https://<dev> --confirmo-ambiente-de-teste ^
        --usuario <login> --admin-usuario <login-admin> --sem-concessao-usuario <login> ^
        --gabarito docs\\GABARITO_REAL_VOLUMETRIA.yaml
"""
import argparse
import getpass
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

RAIZ = Path(__file__).resolve().parent.parent
DOMINIO = "volumetria-catering"
PERGUNTA_PADRAO = "Quanto de peso líquido entrou em agosto de 2026?"
EVENTOS_ESPERADOS = ("ia.pergunta", "ia.consulta", "ia.resposta")
CHAVES_PROIBIDAS_NA_TRILHA = {"texto", "pergunta", "resposta", "mensagem", "conteudo", "prompt"}
_NUMERO = re.compile(r"(?<![A-Za-z0-9])\d{1,3}(?:\.\d{3})+(?:,\d+)?|(?<![A-Za-z0-9])\d+(?:,\d+)?")


# ====================================================================== HTTP
class Http:
    """`pedir(metodo, caminho, corpo, token) -> (status, json)`. Os testes trocam por um adaptador de TestClient."""

    def __init__(self, base: str, tempo: float = 120.0):
        self.base = base.rstrip("/")
        self.tempo = tempo

    def pedir(self, metodo: str, caminho: str, corpo=None, token: str | None = None, form: dict | None = None):
        dados, cabecalhos = None, {"Accept": "application/json"}
        if form is not None:
            dados = "&".join(f"{k}={urllib.request.quote(str(v), safe='')}" for k, v in form.items()).encode()
            cabecalhos["Content-Type"] = "application/x-www-form-urlencoded"
        elif corpo is not None:
            dados = json.dumps(corpo).encode()
            cabecalhos["Content-Type"] = "application/json"
        if token:
            cabecalhos["Authorization"] = f"Bearer {token}"
        pedido = urllib.request.Request(self.base + caminho, data=dados, method=metodo, headers=cabecalhos)
        try:
            with urllib.request.urlopen(pedido, timeout=self.tempo) as r:
                return r.status, _json(r.read())
        except urllib.error.HTTPError as erro:
            return erro.code, _json(erro.read())


def _json(bruto: bytes):
    try:
        return json.loads(bruto.decode("utf-8") or "null")
    except ValueError:
        return None


# ================================================================= resultado
class Passo:
    def __init__(self, nome: str):
        self.nome, self.situacao, self.evidencias = nome, "PULADO", []

    def ok(self, texto: str):
        self.evidencias.append(f"ok: {texto}")

    def falha(self, texto: str):
        self.situacao = "FALHOU"
        self.evidencias.append(f"FALHA: {texto}")

    def fim(self):
        if self.situacao != "FALHOU":
            self.situacao = "PASSOU"
        return self


def numeros(texto: str) -> list[str]:
    return [m.group(0) for m in _NUMERO.finditer(texto or "")]


def login(http, usuario: str, senha: str) -> str | None:
    status, corpo = http.pedir("POST", "/api/auth/login", form={"username": usuario, "password": senha})
    return corpo.get("access_token") if status == 200 and isinstance(corpo, dict) else None


def perguntar(http, token: str, texto: str, conversa_id=None):
    return http.pedir("POST", "/api/ia/perguntas", {"dominio": DOMINIO, "pergunta": texto, "conversa_id": conversa_id}, token)


# ==================================================================== passos
def passo_saude(http, ctx) -> Passo:
    p = Passo("saude")
    status, corpo = http.pedir("GET", "/api/health")
    (p.ok if status == 200 else p.falha)(f"GET /api/health -> {status}")
    return p.fim()


def passo_dominios(http, ctx) -> Passo:
    p = Passo("dominios")
    status, corpo = http.pedir("GET", "/api/ia/dominios", token=ctx["token"])
    if status != 200 or not corpo:
        p.falha(f"GET /api/ia/dominios -> {status} (chave desligada, sem permissão ou sem o card)")
        return p.fim()
    d = next((x for x in corpo if x["slug"] == DOMINIO), None)
    if d is None:
        p.falha("o domínio da Volumetria de Catering não está na lista")
        return p.fim()
    ctx["provedor"] = d["provedor"]["nome"]
    p.ok(f"provedor = {d['provedor']['nome']} ({d['provedor']['rotulo']}); acesso = {d['acesso']['estado']}")
    if d["acesso"]["estado"] != "liberado":
        p.falha(f"o usuário não tem concessão ativa (estado: {d['acesso']['estado']})")
    if ctx.get("exigir_provedor") and d["provedor"]["nome"] != ctx["exigir_provedor"]:
        p.falha(f"esperava o provedor {ctx['exigir_provedor']}, o Hub usa {d['provedor']['nome']}")
    return p.fim()


def _numeros_dos_quadros(blocos: list) -> list[str]:
    achados = []
    for b in blocos or []:
        for item in b.get("itens", []) if b.get("tipo") == "tiles" else []:
            achados += numeros(str(item.get("n", "")))
    return achados


def passo_pergunta(http, ctx) -> Passo:
    p = Passo("pergunta")
    status, r = perguntar(http, ctx["token"], ctx.get("pergunta", PERGUNTA_PADRAO))
    if status != 200:
        p.falha(f"POST /api/ia/perguntas -> {status}")
        return p.fim()
    m = r["mensagem"]
    p.ok(f"estado = {r['estado']}; provedor = {m['meta'].get('provedor')}; duração = {m['meta'].get('duracao_ms')} ms")
    if r["estado"] != "ok":
        p.falha(f"a pergunta terminou em '{r['estado']}'")
        return p.fim()
    quadro, texto = _numeros_dos_quadros(m["blocos"]), set(numeros(m["texto"]))
    if not quadro:
        p.falha("a resposta não trouxe quadro de números montado pelo Hub")
    elif not set(quadro) & texto:
        p.falha("nenhum número do texto é o do quadro do Hub (o texto não repete o dado consultado)")
    else:
        p.ok(f"o número do texto é o do quadro do Hub ({sorted(set(quadro) & texto)[0]})")
    if "uso" in m["meta"]:
        p.falha("a resposta ao usuário traz `uso` (gasto e custo são de operação e não voltam à tela)")
    ctx["conversa_de_teste"] = r["conversa_id"]
    return p.fim()


def passo_sem_concessao(http, ctx) -> Passo:
    p = Passo("sem-concessao")
    if not ctx.get("token_sem"):
        p.evidencias.append("pulado: sem --sem-concessao-usuario")
        return p
    status, r = perguntar(http, ctx["token_sem"], ctx.get("pergunta", PERGUNTA_PADRAO))
    if status in (401, 403):
        p.ok(f"recusado com {status}")
    else:
        p.falha(f"esperava 401/403 e veio {status}")
    texto = json.dumps(r, ensure_ascii=False).lower()
    if any(marca in texto for marca in ("concessão", "concessao", "<app_hub>", "volumetria-catering:ver")):
        p.falha("a mensagem de recusa diz qual porta falhou (deveria ser neutra)")
    else:
        p.ok("a mensagem de recusa é neutra")
    return p.fim()


def passo_revogacao(http, ctx) -> Passo:
    p = Passo("revogacao")
    if not ctx.get("token_admin"):
        p.evidencias.append("pulado: sem --admin-usuario")
        return p
    status, lista = http.pedir("GET", f"/api/ia/administracao/concessoes?dominio={DOMINIO}&status=ativa", token=ctx["token_admin"])
    if status != 200:
        p.falha(f"listar concessões -> {status}")
        return p.fim()
    minha = next((c for c in lista if c.get("username") == ctx["usuario"]), None)
    if minha is None:
        p.falha("o usuário de teste não tem concessão ativa para revogar")
        return p.fim()
    status, _ = http.pedir("POST", f"/api/ia/administracao/concessoes/{minha['id']}/revogar",
                           {"motivo": "homologação do SuperfrioIA"}, ctx["token_admin"])
    (p.ok if status == 200 else p.falha)(f"revogar -> {status}")
    status, _ = perguntar(http, ctx["token"], ctx.get("pergunta", PERGUNTA_PADRAO))
    (p.ok if status == 403 else p.falha)(f"pergunta logo depois da revogação -> {status} (esperado 403, sem esperar nada)")
    status, pedido = http.pedir("POST", "/api/ia/concessoes/pedidos",
                                {"dominio": DOMINIO, "motivo": "homologação do SuperfrioIA: voltar ao teste"}, ctx["token"])
    if status == 201:
        status, _ = http.pedir("POST", f"/api/ia/administracao/concessoes/{pedido['id']}/aprovar", {}, ctx["token_admin"])
        (p.ok if status == 200 else p.falha)(f"aprovar o novo pedido -> {status}")
        status, _ = perguntar(http, ctx["token"], ctx.get("pergunta", PERGUNTA_PADRAO))
        (p.ok if status == 200 else p.falha)(f"pergunta depois de aprovar de novo -> {status}")
    else:
        p.falha(f"pedir a concessão de novo -> {status}")
    return p.fim()


def passo_auditoria(http, ctx) -> Passo:
    p = Passo("auditoria")
    if not ctx.get("token_admin"):
        p.evidencias.append("pulado: sem --admin-usuario")
        return p
    de = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    status, corpo = http.pedir("GET", f"/api/admin/auditoria?app_slug=superfrioia&de={de}&por_pagina=200", token=ctx["token_admin"])
    if status != 200:
        p.falha(f"GET /api/admin/auditoria -> {status}")
        return p.fim()
    eventos = corpo.get("eventos") or corpo.get("itens") or corpo.get("items") or []
    acoes = {e["acao"] for e in eventos}
    p.ok(f"{len(eventos)} eventos do SuperfrioIA hoje; ações: {sorted(acoes)}")
    for esperado in EVENTOS_ESPERADOS:
        (p.ok if esperado in acoes else p.falha)(f"evento {esperado} {'presente' if esperado in acoes else 'AUSENTE'}")
    if ctx.get("revogou"):
        (p.ok if "ia.concessao.revogada" in acoes else p.falha)("evento ia.concessao.revogada")
    vazou = [e["acao"] for e in eventos if CHAVES_PROIBIDAS_NA_TRILHA & set((e.get("detalhes") or {}))]
    (p.falha(f"eventos com campo de texto: {sorted(set(vazou))}") if vazou else p.ok("nenhum evento guarda texto de pergunta ou resposta"))
    return p.fim()


def passo_gabarito(http, ctx) -> Passo:
    """Cada entrada: `pergunta` e `tela` (o número como a TELA mostra, anotado por você, com a unidade)."""
    p = Passo("gabarito")
    caminho = ctx.get("gabarito")
    if not caminho:
        p.evidencias.append("pulado: sem --gabarito")
        return p
    import yaml

    entradas = [e for e in yaml.safe_load(Path(caminho).read_text(encoding="utf-8")) or [] if e.get("tela")]
    if not entradas:
        p.falha("o gabarito não tem nenhuma entrada com `tela` preenchida")
        return p.fim()
    for e in entradas:
        status, r = perguntar(http, ctx["token"], e["pergunta"])
        if status != 200 or r["estado"] != "ok":
            p.falha(f"{e['id']}: a pergunta não terminou ok ({status}/{r.get('estado') if isinstance(r, dict) else '?'})")
            continue
        esperado = set(numeros(str(e["tela"])))
        no_texto, no_quadro = set(numeros(r["mensagem"]["texto"])), set(_numeros_dos_quadros(r["mensagem"]["blocos"]))
        if esperado <= no_texto and esperado <= no_quadro:
            p.ok(f"{e['id']}: tela = IA ({e['tela']})")
        else:
            p.falha(f"{e['id']}: a tela mostra {e['tela']}; a IA mostrou texto={sorted(no_texto)[:6]} quadro={sorted(no_quadro)[:6]}")
    return p.fim()


def passo_desligar(http, ctx) -> Passo:
    p = Passo("desligar")
    if not ctx.get("interativo"):
        p.evidencias.append("pulado: exige você na VM (use --passos desligar, em terminal interativo)")
        return p
    print("\n>> Na VM: coloque IA_HABILITADO=false no .env e rode `docker compose up -d`. Depois tecle ENTER.")
    input()
    status, _ = http.pedir("GET", "/api/ia/dominios", token=ctx["token"])
    (p.ok if status == 404 else p.falha)(f"/api/ia/dominios com a chave desligada -> {status} (esperado 404)")
    status, home = http.pedir("GET", "/api/portal/home", token=ctx["token"])
    cartoes = json.dumps(home, ensure_ascii=False) if home else ""
    (p.falha("o card do SuperfrioIA continua na home") if "superfrioia" in cartoes else p.ok("o card sumiu da home"))
    print(">> Agora volte IA_HABILITADO=true, rode `docker compose up -d` de novo e tecle ENTER.")
    input()
    status, _ = http.pedir("GET", "/api/ia/dominios", token=ctx["token"])
    (p.ok if status == 200 else p.falha)(f"/api/ia/dominios depois de religar -> {status} (esperado 200)")
    return p.fim()


PASSOS = {"saude": passo_saude, "dominios": passo_dominios, "pergunta": passo_pergunta,
          "sem-concessao": passo_sem_concessao, "revogacao": passo_revogacao, "auditoria": passo_auditoria,
          "gabarito": passo_gabarito, "desligar": passo_desligar}
PADRAO = ["saude", "dominios", "pergunta", "sem-concessao", "revogacao", "auditoria", "gabarito"]


# =================================================================== relatório
def relatorio(url: str, ctx: dict, passos: list[Passo]) -> str:
    linhas = [f"# Homologação do SuperfrioIA — {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC", "",
              f"- alvo: `{urlparse(url).netloc}` (confirmado como ambiente de teste por quem rodou)",
              f"- provedor visto: `{ctx.get('provedor', '?')}`",
              "- NÃO contém senha, token, texto de pergunta nem resposta", "",
              "| Passo | Situação |", "|---|---|"]
    linhas += [f"| {p.nome} | **{p.situacao}** |" for p in passos]
    for p in passos:
        linhas += ["", f"### {p.nome}", ""] + [f"- {e}" for e in p.evidencias]
    falhou = [p.nome for p in passos if p.situacao == "FALHOU"]
    linhas += ["", "## Conclusão", "",
               ("**NÃO aprovado**: falharam " + ", ".join(falhou)) if falhou else
               "Nenhum passo executado falhou. Passos PULADOS não foram verificados; a aprovação é da responsável técnica."]
    return "\n".join(linhas) + "\n"


def executar(http, args, senha_de, interativo=False) -> tuple[list[Passo], dict]:
    ctx: dict = {"usuario": args.usuario, "pergunta": args.pergunta, "gabarito": args.gabarito,
                 "exigir_provedor": args.exigir_provedor, "interativo": interativo}
    passos: list[Passo] = []
    escolhidos = [p.strip() for p in args.passos.split(",")] if args.passos else PADRAO
    desconhecidos = [p for p in escolhidos if p not in PASSOS]
    if desconhecidos:
        raise SystemExit(f"passos desconhecidos: {desconhecidos}. Válidos: {sorted(PASSOS)}")
    if any(p != "saude" for p in escolhidos):
        ctx["token"] = login(http, args.usuario, senha_de("usuario"))
        if not ctx["token"]:
            falhou = Passo("login")
            falhou.falha("o login do usuário de teste falhou (senha errada, conta inexistente ou bloqueada)")
            return [falhou.fim()], ctx
        if args.admin_usuario:
            ctx["token_admin"] = login(http, args.admin_usuario, senha_de("admin"))
        if args.sem_concessao_usuario:
            ctx["token_sem"] = login(http, args.sem_concessao_usuario, senha_de("sem"))
    for nome in escolhidos:
        passo = PASSOS[nome](http, ctx)
        if nome == "revogacao" and passo.situacao != "PULADO":
            ctx["revogou"] = True
        passos.append(passo)
    return passos, ctx


def main() -> None:
    ap = argparse.ArgumentParser(description="Homologação do SuperfrioIA (ambiente de teste)")
    ap.add_argument("--url", required=True)
    ap.add_argument("--confirmo-ambiente-de-teste", action="store_true", required=True)
    ap.add_argument("--usuario", required=True)
    ap.add_argument("--admin-usuario", default="")
    ap.add_argument("--sem-concessao-usuario", default="")
    ap.add_argument("--passos", default="")
    ap.add_argument("--pergunta", default=PERGUNTA_PADRAO)
    ap.add_argument("--gabarito", default="")
    ap.add_argument("--exigir-provedor", default="", choices=["", "falso", "anthropic"])
    ap.add_argument("--saida", default="")
    args = ap.parse_args()

    alvo = urlparse(args.url)
    if alvo.scheme not in ("http", "https") or not alvo.netloc:
        sys.exit("URL inválida")
    print(f"ALVO: {alvo.scheme}://{alvo.netloc}  (você confirmou que é ambiente de TESTE; nenhuma chamada fez ainda)")

    def senha_de(quem: str) -> str:
        variavel = {"usuario": "IA_HOMOLOG_SENHA", "admin": "IA_HOMOLOG_SENHA_ADMIN", "sem": "IA_HOMOLOG_SENHA_SEM_CONCESSAO"}[quem]
        return os.environ.get(variavel) or getpass.getpass(f"Senha de {quem} (não aparece): ")

    passos, ctx = executar(Http(args.url), args, senha_de, interativo=sys.stdin.isatty())
    destino = Path(args.saida) if args.saida else RAIZ / "docs" / f"HOMOLOGACAO_IA_{datetime.now(timezone.utc):%Y%m%d_%H%M}.md"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(relatorio(args.url, ctx, passos), encoding="utf-8")
    for p in passos:
        print(f"  {p.nome:<14} {p.situacao}")
    print(f"\nRelatório: {destino}")
    sys.exit(1 if any(p.situacao == "FALHOU" for p in passos) else 0)


if __name__ == "__main__":
    main()
