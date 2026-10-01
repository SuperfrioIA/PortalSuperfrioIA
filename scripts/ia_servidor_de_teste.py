"""Sobe o Hub localmente com o SuperfrioIA ligado e um DW de MENTIRA.

Para percorrer a tela no navegador (Lote 2) sem DW real: o `service` da volumetria
conecta num DW sintético (`tests/dw_falso.py`), com dados determinísticos de 6
unidades, 4 clientes e 21 meses. O provedor do modelo é o falso. **Nada aqui sai da
máquina**: sem rede, sem chave, sem credencial.

Travas:

- o banco é um SQLite **temporário e descartável** (`SUPERFRIO_DB_PATH`), nunca o
  `data/portal.db`;
- recusa subir com `SUPERFRIO_ENV=prod` ou com `DATABASE_URL` definida;
- ignora `DW_LEITURA_*` do ambiente (a conexão do DW é substituída, então nenhuma
  credencial real seria usada, mas elas são removidas por garantia);
- escuta só em `127.0.0.1`.

Uso (PowerShell, na raiz do projeto):

    .\\.venv\\Scripts\\python.exe scripts\\ia_servidor_de_teste.py [porta]

Padrão: porta 8000. Login: `admin` / `admin123`. Para parar: Ctrl+C. Quem inicia,
encerra e confirma a porta livre (`docs/EXECUCAO_LOCAL.md` §5).

Variáveis opcionais, só para percorrer estados da tela:

    IA_TESTE_DW_FORA=1      o DW de mentira falha na consulta (estado "indisponível")
    IA_TESTE_UNIDADES=20    mais unidades (ranking com mais de uma página)
    IA_COTA_DIA=2           cota pequena (estado "limite diário")
"""
import os
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def main() -> None:
    porta = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    if os.environ.get("SUPERFRIO_ENV", "dev").lower() == "prod":
        sys.exit("recusado: SUPERFRIO_ENV=prod. Este servidor é só para teste local.")
    if os.environ.get("DATABASE_URL"):
        sys.exit("recusado: DATABASE_URL definida. Este servidor usa um SQLite descartável.")

    pasta = tempfile.mkdtemp(prefix="superfrio_ia_dev_")
    os.environ["SUPERFRIO_DB_PATH"] = str(Path(pasta) / "portal.db")   # antes de importar o backend
    os.environ["SUPERFRIO_ENV"] = "dev"
    os.environ["IA_HABILITADO"] = "true"
    os.environ["IA_PROVEDOR"] = "falso"
    for var in ("DW_LEITURA_USUARIO", "DW_LEITURA_SENHA"):
        os.environ.pop(var, None)

    sys.path[:0] = [str(RAIZ), str(RAIZ / "tests")]
    import dw_falso
    from backend.volumetria_catering import conexao_dw, dimensoes_dw

    banco = dw_falso.Banco(n_unidades=int(os.environ.get("IA_TESTE_UNIDADES", "6")))
    if os.environ.get("IA_TESTE_DW_FORA") == "1":
        # simula o DW caindo no meio da consulta (erro com a cara do driver Oracle)
        banco.erro_na_consulta = type("DatabaseError", (Exception,), {"__module__": "oracledb"})("DPY-4011")
    conexao_dw.conectar = banco.conectar
    dimensoes_dw.hoje_no_fuso = lambda: dw_falso.HOJE
    dimensoes_dw._cache["dados"] = dw_falso.dim_ia(6)
    dimensoes_dw._cache["expira_em"] = float("inf")

    print("=" * 72)
    print("SuperfrioIA — servidor de TESTE com DW de mentira (dados sintéticos)")
    print(f"  banco descartável : {os.environ['SUPERFRIO_DB_PATH']}")
    print(f"  endereço          : http://127.0.0.1:{porta}   (login admin / admin123)")
    print(f"  'hoje' fixado em  : {dw_falso.HOJE.isoformat()}")
    print("  Ctrl+C para parar.")
    print("=" * 72, flush=True)

    import uvicorn
    uvicorn.run("backend.main:app", host="127.0.0.1", port=porta, log_level="info")


if __name__ == "__main__":
    main()
