"""A-4 (DD-28): a tela e a IA arredondam igual? Compara o `fmt` REAL da tela com o `Decimal` da IA.

A tela (`frontend/volumetria-catering/app.js`, função `fmt`) formata no `double` do JavaScript;
a IA (`backend/ia/derivacoes.py`, `exibir`) arredonda em `Decimal`, meio para cima. O contrato diz
que as duas mostram o mesmo número. Este script mede, em vez de afirmar:

1. extrai o texto de `fmt` do `app.js` (nunca uma cópia reescrita aqui);
2. gera uma grade grande de valores como a API os envia (string de `Decimal`: o DW manda kg com
   até 3 casas): inteiros, empates exatos (`x,x50` kg), aleatórios e valores grandes e negativos;
3. roda o `fmt` no Node e, se existirem na máquina, no Chrome e no Edge (headless, `--dump-dom`);
4. chama `derivacoes.exibir` para os mesmos valores e lista TODA divergência.

Uso (PowerShell, raiz do projeto):

    .\\.venv\\Scripts\\python.exe scripts\\comparar_exibicao.py            # grade completa (Node) + navegadores
    .\\.venv\\Scripts\\python.exe scripts\\comparar_exibicao.py --rapido    # grade pequena

Não toca banco, rede nem DW. Os navegadores abrem sozinhos e se encerram sozinhos (`--dump-dom`); o script
NÃO os monitora: quem roda confere, pela linha de comando (`--user-data-dir=...comparar_exibicao_br_...`) e
nunca por nome, que nada ficou. Aos navegadores vai uma AMOSTRA da grade (1 em 13, ~209 mil valores); a
grade inteira roda só no Node. Sai com código 1 se houver divergência.
"""
import argparse
import html
import json
import random
import re
import shutil
import subprocess
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
APP_JS = RAIZ / "frontend" / "volumetria-catering" / "app.js"
sys.path.insert(0, str(RAIZ))

NAVEGADORES = {
    "chrome": [Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")],
    "edge": [Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
             Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe")],
}


def fonte_do_fmt() -> str:
    """O texto de `const fmt = ...;` do app.js, exatamente como a tela o executa."""
    texto = APP_JS.read_text(encoding="utf-8")
    achado = re.search(r"const fmt = \(valor, unidade\) => \{.*?\n\};", texto, re.S)
    if not achado:
        raise SystemExit("não achei `const fmt` em app.js: a função mudou de forma, atualize o extrator")
    return achado.group(0)


# ======================================================================= a grade
def _texto(valor: Decimal) -> str:
    return format(valor, "f")


def _ordem_de_grandeza(r: random.Random) -> Decimal:
    """Valor de 0,001 a ~1e13 com no máximo 3 casas, como o DW devolve (NUMBER(18,3))."""
    return Decimal(str(round(10 ** r.uniform(-3, 13), 3)))


def grade(tamanho: str, semente: int = 20261002) -> list[tuple[str, str]]:
    """`[(unidade, valor_como_a_API_envia)]`. Unidades: `t` (a fonte manda kg) e `R$`, `UA`, `cx`."""
    r = random.Random(semente)
    grande = tamanho == "grande"
    inteiros = 400_000 if grande else 20_000
    aleatorios = 200_000 if grande else 10_000
    saida: list[tuple[str, str]] = []

    def em(unidade, valores):
        saida.extend((unidade, _texto(v)) for v in valores)

    # peso: kg -> t com 1 casa. Todo kg inteiro; todo empate exato (x,x50 kg = x,xx5 t); 3 casas
    em("t", (Decimal(k) for k in range(0, inteiros + 1)))
    em("t", (Decimal(k * 100 + 50) for k in range(0, inteiros * 3, 997)))
    em("t", (Decimal(k * 100 + 50) / 1000 * 1000 + Decimal("0.000") for k in range(1, inteiros // 4)))
    em("t", (Decimal(r.randrange(0, 5_000_000_000_000)) / 1000 for _ in range(aleatorios)))      # kg com 3 casas
    em("t", (_ordem_de_grandeza(r) for _ in range(aleatorios)))                                  # várias ordens de grandeza
    em("t", (-Decimal(r.randrange(1, 2_000_000_000)) / 1000 for _ in range(aleatorios // 4)))    # negativos
    # R$, UA, cx: 0 casas. Todo inteiro; todo meio exato (x,500); aleatórios; grandes; negativos
    for unidade in ("R$", "UA", "cx"):
        n = inteiros if unidade == "R$" else inteiros // 4
        em(unidade, (Decimal(k) for k in range(0, n + 1)))
        em(unidade, (Decimal(k) + Decimal("0.5") for k in range(0, n)))
        em(unidade, (Decimal(r.randrange(0, 5_000_000_000_000)) / 1000 for _ in range(aleatorios // 2)))
        em(unidade, (_ordem_de_grandeza(r) for _ in range(aleatorios // 2)))
        em(unidade, (-Decimal(r.randrange(1, 2_000_000_000)) / 1000 for _ in range(aleatorios // 8)))
    # os empates do registro anterior (DD-28), por escrito
    em("t", (Decimal(v) for v in ("50", "150", "250", "1050", "1150", "999950", "12345650", "0", "49", "51")))
    return list(dict.fromkeys(saida))


# ===================================================================== a tela
_PREAMBULO = "const $ = () => null;\n"


def rodar_no_node(entradas: list[tuple[str, str]]) -> list[str]:
    node = shutil.which("node")
    if not node:
        raise SystemExit("node não encontrado no PATH")
    pasta = Path(tempfile.mkdtemp(prefix="comparar_exibicao_"))
    try:
        (pasta / "entradas.json").write_text(json.dumps(entradas), encoding="utf-8")
        (pasta / "rodar.js").write_text(
            _PREAMBULO + fonte_do_fmt() + "\n"
            "const fs = require('fs');\n"
            f"const e = JSON.parse(fs.readFileSync({json.dumps(str(pasta / 'entradas.json'))}, 'utf8'));\n"
            f"fs.writeFileSync({json.dumps(str(pasta / 'saida.json'))}, JSON.stringify(e.map(([u, v]) => fmt(v, u))));\n",
            encoding="utf-8")
        subprocess.run([node, str(pasta / "rodar.js")], check=True, timeout=600)
        return json.loads((pasta / "saida.json").read_text(encoding="utf-8"))
    finally:
        shutil.rmtree(pasta, ignore_errors=True)


def rodar_no_navegador(exe: Path, entradas: list[tuple[str, str]]) -> list[str]:
    pasta = Path(tempfile.mkdtemp(prefix="comparar_exibicao_br_"))
    try:
        pagina = pasta / "pagina.html"
        pagina.write_text(
            "<!doctype html><meta charset='utf-8'><pre id='out'></pre><script>\n"
            + _PREAMBULO + fonte_do_fmt() + "\n"
            f"const e = {json.dumps(entradas)};\n"
            "document.getElementById('out').textContent = JSON.stringify(e.map(([u, v]) => fmt(v, u)));\n"
            "</script>", encoding="utf-8")
        perfil = pasta / "perfil"
        proc = subprocess.run(
            [str(exe), "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
             f"--user-data-dir={perfil}", "--dump-dom", pagina.as_uri()],
            capture_output=True, text=True, timeout=300, encoding="utf-8")
        achado = re.search(r"<pre id=\"out\">(.*?)</pre>", proc.stdout, re.S)
        if not achado:
            raise RuntimeError(f"{exe.name}: saída sem o resultado (código {proc.returncode})")
        return json.loads(html.unescape(achado.group(1)))
    finally:
        shutil.rmtree(pasta, ignore_errors=True)


def versao_do_navegador(exe: Path) -> str:
    try:
        saida = subprocess.run(["powershell", "-NoProfile", "-Command", f"(Get-Item '{exe}').VersionInfo.ProductVersion"],
                               capture_output=True, text=True, timeout=30).stdout.strip()
        return saida or "?"
    except Exception:
        return "?"


# ================================================================ a IA e o relatório
def da_ia(entradas: list[tuple[str, str]]) -> list[str]:
    from backend.ia import derivacoes

    return [derivacoes.exibir(Decimal(valor), unidade)["exibido"] for unidade, valor in entradas]


def divergencias(entradas, tela, ia):
    return [(u, v, t, i) for (u, v), t, i in zip(entradas, tela, ia) if t != i]


def main() -> None:
    parser = argparse.ArgumentParser(description="A-4: tela x IA na exibição")
    parser.add_argument("--rapido", action="store_true")
    parser.add_argument("--sem-navegador", action="store_true")
    parser.add_argument("--json", default="")
    args = parser.parse_args()

    entradas = grade("pequena" if args.rapido else "grande")
    print(f"grade: {len(entradas)} valores ({sum(1 for u, _ in entradas if u == 't')} de peso)", flush=True)
    ia = da_ia(entradas)

    motores: dict[str, list[str]] = {"node " + subprocess.run(["node", "--version"], capture_output=True, text=True).stdout.strip():
                                     rodar_no_node(entradas)}
    if not args.sem_navegador:
        amostra = entradas if args.rapido else entradas[::13]          # a página carrega a grade inteira no DOM
        ia_amostra = ia if args.rapido else ia[::13]
        for nome, caminhos in NAVEGADORES.items():
            exe = next((c for c in caminhos if c.exists()), None)
            if exe is None:
                print(f"  {nome}: não instalado, não testado")
                continue
            try:
                motores[f"{nome} {versao_do_navegador(exe)} ({len(amostra)} valores)"] = rodar_no_navegador(exe, amostra)
            except Exception as erro:
                print(f"  {nome}: FALHOU ao rodar ({type(erro).__name__}: {erro})")

    total = 0
    resultado = {}
    for motor, saida in motores.items():
        base = ia if len(saida) == len(ia) else ia_amostra
        ref = entradas if len(saida) == len(ia) else amostra
        difs = divergencias(ref, saida, base)
        total += len(difs)
        resultado[motor] = {"valores": len(saida), "divergencias": len(difs), "exemplos": difs[:25]}
        print(f"\n== {motor}: {len(saida)} valores, {len(difs)} divergência(s) ==")
        for u, v, t, i in difs[:25]:
            print(f"   {u:>3}  entrada={v:<24} tela={t!r:<20} ia={i!r}")
    if args.json:
        Path(args.json).write_text(json.dumps(resultado, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nTOTAL: {total} divergência(s) em {len(motores)} motor(es).")
    sys.exit(1 if total else 0)


if __name__ == "__main__":
    main()
