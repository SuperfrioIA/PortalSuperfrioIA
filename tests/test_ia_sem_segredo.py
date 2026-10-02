"""Nenhuma chave, e nenhuma saída de rede, no código do SuperfrioIA (Lote 3).

Duas varreduras baratas que valem como o "varredura do diff por padrão de chave = 0" do
plano, e uma trava de rede: a suíte inteira roda sem sair da máquina.
"""
import pathlib
import re
import socket

RAIZ = pathlib.Path(__file__).resolve().parent.parent
# montado por partes para este arquivo não casar com a própria busca
PADRAO_DE_CHAVE = re.compile("sk-" + r"ant-[A-Za-z0-9_\-]{6,}")
PASTAS = ("backend", "frontend", "scripts", "tests")
SUFIXOS = {".py", ".js", ".html", ".css", ".yaml", ".yml", ".md", ".json", ".txt", ".example", ".ps1"}


def _arquivos_versionaveis():
    for pasta in PASTAS:
        for caminho in (RAIZ / pasta).rglob("*"):
            if caminho.is_file() and caminho.suffix in SUFIXOS and "__pycache__" not in caminho.parts \
                    and "node_modules" not in caminho.parts:
                yield caminho
    for nome in (".env.example", "requirements.txt", "requirements-dev.txt", "CHANGELOG.md"):
        if (RAIZ / nome).exists():
            yield RAIZ / nome


def test_nenhum_arquivo_do_repositorio_tem_chave_da_anthropic():
    achados = [str(c.relative_to(RAIZ)) for c in _arquivos_versionaveis()
               if PADRAO_DE_CHAVE.search(c.read_text(encoding="utf-8", errors="ignore"))]
    assert achados == []


def test_o_env_de_exemplo_nao_traz_valor_para_a_chave_nem_para_o_cambio():
    linhas = (RAIZ / ".env.example").read_text(encoding="utf-8").splitlines()
    ativas = {l.split("=", 1)[0]: l.split("=", 1)[1].strip() for l in linhas if "=" in l and not l.lstrip().startswith("#")}
    assert ativas["ANTHROPIC_API_KEY"] == ""
    assert ativas["IA_HABILITADO"] == "false" and ativas["IA_PROVEDOR"] == "falso"
    assert not any(k.startswith("IA_PRECO") or k == "IA_CAMBIO_USD_BRL" for k in ativas), "preço inventado vira custo medido"


def test_o_env_local_com_a_chave_esta_no_gitignore():
    ignorados = (RAIZ / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env.local" in ignorados and ".env" in ignorados


def test_a_suite_nao_consegue_abrir_conexao_para_fora_da_maquina():
    """A trava de `conftest.py` vale: tentar conectar fora do loopback falha na hora."""
    import pytest

    with pytest.raises(AssertionError, match="rede bloqueada"):
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("203.0.113.7", 443))
