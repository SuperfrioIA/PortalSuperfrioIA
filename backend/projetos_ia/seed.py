"""Seed do catálogo de filiais — as 59 filiais de produção (23 ativas).

Origem: `docs/exemplos/filiais_prod.csv` do Conciliador de Estoque, que é o
cadastro mestre. A lista está em código (e não como CSV lido em runtime) para a
imagem Docker não depender de um arquivo de dados no `COPY`.

Duas coisas derivadas na geração, porque o Conciliador não tem esses campos:

- `regiao` vem da UF (a tela de rollout agrupa as filiais por região);
- `cidade` foi padronizada em caixa mista — o CSV mistura ARAPONGAS e Cascavel.

`responsavel` e a B.U ficam vazios: não existem no CSV de origem. São cadastro
manual na tela Administração › Filiais.

Idempotente e conservador: casa por `codigo` e **não toca em filial que já
existe** — inativar, renomear ou vincular uma B.U pela tela nunca é desfeito
pelo próximo boot.
"""
from sqlalchemy import insert, select, update

from backend.projetos_ia.models import Filial

# Geradas de filiais_prod.csv (ver docstring). `ativo` espelha o status de lá.
FILIAIS = [
    {"codigo": "1001", "nome": "VGS", "cidade": "Vargem Grande do Sul", "uf": "SP", "regiao": "Sudeste", "ativo": 1},
    {"codigo": "1002", "nome": "MGG", "cidade": "Mogi Guaçu", "uf": "SP", "regiao": "Sudeste", "ativo": 1},
    {"codigo": "1003", "nome": "RPI", "cidade": "Ribeirão Preto", "uf": "SP", "regiao": "Sudeste", "ativo": 1},
    {"codigo": "1004", "nome": "TVGS", "cidade": "Vargem Grande do Sul", "uf": "SP", "regiao": "Sudeste", "ativo": 0},
    {"codigo": "1005", "nome": "RPII", "cidade": "Ribeirao Preto", "uf": "SP", "regiao": "Sudeste", "ativo": 1},
    {"codigo": "1006", "nome": "RPIII", "cidade": "Ribeirao Preto", "uf": "SP", "regiao": "Sudeste", "ativo": 0},
    {"codigo": "1007", "nome": "JAC", "cidade": "Jacarei", "uf": "SP", "regiao": "Sudeste", "ativo": 0},
    {"codigo": "1008", "nome": "EJAC", "cidade": "Jacarei", "uf": "SP", "regiao": "Sudeste", "ativo": 0},
    {"codigo": "1009", "nome": "EVGS", "cidade": "Vargem Grande do Sul", "uf": "SP", "regiao": "Sudeste", "ativo": 0},
    {"codigo": "1010", "nome": "ARP", "cidade": "Arapongas", "uf": "PR", "regiao": "Sul", "ativo": 1},
    {"codigo": "1012", "nome": "MLA", "cidade": "Vera Cruz", "uf": "SP", "regiao": "Sudeste", "ativo": 1},
    {"codigo": "1013", "nome": "LDN", "cidade": "Cambe", "uf": "PR", "regiao": "Sul", "ativo": 0},
    {"codigo": "1014", "nome": "MIR", "cidade": "Mirassol", "uf": "SP", "regiao": "Sudeste", "ativo": 0},
    {"codigo": "1015", "nome": "RPV", "cidade": "Ribeirao Preto", "uf": "SP", "regiao": "Sudeste", "ativo": 0},
    {"codigo": "1016", "nome": "SFMAQ", "cidade": "Mairinque", "uf": "SP", "regiao": "Sudeste", "ativo": 0},
    {"codigo": "1017", "nome": "CGD", "cidade": "Campo Grande", "uf": "MS", "regiao": "Centro-Oeste", "ativo": 1},
    {"codigo": "1018", "nome": "CVDI", "cidade": "Campo Verde", "uf": "MT", "regiao": "Centro-Oeste", "ativo": 1},
    {"codigo": "1019", "nome": "LDNII", "cidade": "Cambe", "uf": "PR", "regiao": "Sul", "ativo": 1},
    {"codigo": "1020", "nome": "RMSPI", "cidade": "São Paulo", "uf": "SP", "regiao": "Sudeste", "ativo": 1},
    {"codigo": "1021", "nome": "CCV", "cidade": "Cascavel", "uf": "PR", "regiao": "Sul", "ativo": 1},
    {"codigo": "1022", "nome": "XAP", "cidade": "Chapeco", "uf": "SC", "regiao": "Sul", "ativo": 0},
    {"codigo": "1023", "nome": "CGB", "cidade": "Cuiabá", "uf": "MT", "regiao": "Centro-Oeste", "ativo": 1},
    {"codigo": "1024", "nome": "MAO", "cidade": "Manaus", "uf": "AM", "regiao": "Norte", "ativo": 0},
    {"codigo": "1025", "nome": "CWBII", "cidade": "São José dos Pinhais", "uf": "PR", "regiao": "Sul", "ativo": 1},
    {"codigo": "1026", "nome": "BEL", "cidade": "Benevides", "uf": "PA", "regiao": "Norte", "ativo": 0},
    {"codigo": "1027", "nome": "POAI", "cidade": "Nova Santa Rita", "uf": "RS", "regiao": "Sul", "ativo": 1},
    {"codigo": "1028", "nome": "CNF", "cidade": "Ribeirão das Neves", "uf": "MG", "regiao": "Sudeste", "ativo": 0},
    {"codigo": "1029", "nome": "CWBIII", "cidade": "São José dos Pinhais", "uf": "PR", "regiao": "Sul", "ativo": 1},
    {"codigo": "1030", "nome": "ITA", "cidade": "Garuva", "uf": "SC", "regiao": "Sul", "ativo": 1},
    {"codigo": "1031", "nome": "POAII", "cidade": "Canoas", "uf": "RS", "regiao": "Sul", "ativo": 1},
    {"codigo": "1032", "nome": "ARPI", "cidade": "Arapongas", "uf": "PR", "regiao": "Sul", "ativo": 0},
    {"codigo": "1033", "nome": "ITAII", "cidade": "Garuva", "uf": "SC", "regiao": "Sul", "ativo": 0},
    {"codigo": "2001", "nome": "COPACKER", "cidade": "Vargem Grande do Sul", "uf": "SP", "regiao": "Sudeste", "ativo": 0},
    {"codigo": "2002", "nome": "MGG", "cidade": "Mogi Guaçu", "uf": "SP", "regiao": "Sudeste", "ativo": 0},
    {"codigo": "3001", "nome": "MULT", "cidade": "Ribeirao Preto", "uf": "SP", "regiao": "Sudeste", "ativo": 0},
    {"codigo": "3002", "nome": "BAIXADA", "cidade": "Vargem Grande do Sul", "uf": "SP", "regiao": "Sudeste", "ativo": 0},
    {"codigo": "4001", "nome": "MAQ", "cidade": "Mairinque", "uf": "SP", "regiao": "Sudeste", "ativo": 1},
    {"codigo": "4003", "nome": "MAQII", "cidade": "Mairinque", "uf": "SP", "regiao": "Sudeste", "ativo": 1},
    {"codigo": "5001", "nome": "ITA", "cidade": "Garuva", "uf": "SC", "regiao": "Sul", "ativo": 0},
    {"codigo": "6001", "nome": "CCV", "cidade": "Cascavel", "uf": "PR", "regiao": "Sul", "ativo": 0},
    {"codigo": "7001", "nome": "SSA", "cidade": "Simoes Filho", "uf": "BA", "regiao": "Nordeste", "ativo": 0},
    {"codigo": "8001", "nome": "RMSPII", "cidade": "Barueri", "uf": "SP", "regiao": "Sudeste", "ativo": 1},
    {"codigo": "8002", "nome": "RMSPIII", "cidade": "Barueri", "uf": "SP", "regiao": "Sudeste", "ativo": 0},
    {"codigo": "8003", "nome": "RMSPIV", "cidade": "Barueri", "uf": "SP", "regiao": "Sudeste", "ativo": 1},
    {"codigo": "8004", "nome": "RMRJ", "cidade": "Duque de Caxias", "uf": "RJ", "regiao": "Sudeste", "ativo": 1},
    {"codigo": "8005", "nome": "FOR", "cidade": "Fortaleza", "uf": "CE", "regiao": "Nordeste", "ativo": 0},
    {"codigo": "8006", "nome": "REC", "cidade": "Recife", "uf": "PE", "regiao": "Nordeste", "ativo": 0},
    {"codigo": "8007", "nome": "BAIXADA", "cidade": "Barueri", "uf": "SP", "regiao": "Sudeste", "ativo": 0},
    {"codigo": "9001", "nome": "SSAII", "cidade": "Simoes Filho", "uf": "BA", "regiao": "Nordeste", "ativo": 0},
    {"codigo": "10001", "nome": "BSB", "cidade": "Brasilia", "uf": "DF", "regiao": "Centro-Oeste", "ativo": 1},
    {"codigo": "10002", "nome": "CGH", "cidade": "São Paulo", "uf": "SP", "regiao": "Sudeste", "ativo": 0},
    {"codigo": "10003", "nome": "GYN", "cidade": "Aparecida de Goiania", "uf": "GO", "regiao": "Centro-Oeste", "ativo": 0},
    {"codigo": "10004", "nome": "UDI", "cidade": "Uberlandia", "uf": "MG", "regiao": "Sudeste", "ativo": 0},
    {"codigo": "10005", "nome": "UDIII", "cidade": "Contagem", "uf": "MG", "regiao": "Sudeste", "ativo": 0},
    {"codigo": "10006", "nome": "GYNII", "cidade": "Aparecida de Goiania", "uf": "GO", "regiao": "Centro-Oeste", "ativo": 0},
    {"codigo": "11001", "nome": "SPF", "cidade": "São Paulo", "uf": "SP", "regiao": "Sudeste", "ativo": 0},
    {"codigo": "12001", "nome": "POAIII", "cidade": "Canoas", "uf": "RS", "regiao": "Sul", "ativo": 0},
    {"codigo": "13001", "nome": "VIA", "cidade": "São Paulo", "uf": "SP", "regiao": "Sudeste", "ativo": 0},
    {"codigo": "MAQ", "nome": "MAQ", "cidade": "Mairinque", "uf": "SP", "regiao": "Sudeste", "ativo": 0},
]


def seed(session) -> None:
    for f in FILIAIS:
        ja_existe = session.execute(
            select(Filial.id).where(Filial.codigo == f["codigo"])
        ).scalar_one_or_none()
        if ja_existe is not None:
            continue

        # Filial cadastrada à mão antes de `codigo` existir: adota em vez de
        # duplicar. Só preenche o que está vazio — nome, região e `ativo` são
        # de quem cadastrou.
        adotavel = session.execute(
            select(Filial.id)
            .where(Filial.nome == f["nome"], Filial.codigo.is_(None))
            .order_by(Filial.id)
        ).scalars().first()
        if adotavel is not None:
            session.execute(
                update(Filial)
                .where(Filial.id == adotavel)
                .values(codigo=f["codigo"])
            )
            session.execute(
                update(Filial)
                .where(Filial.id == adotavel, Filial.cidade.is_(None))
                .values(cidade=f["cidade"])
            )
            session.execute(
                update(Filial)
                .where(Filial.id == adotavel, Filial.uf.is_(None))
                .values(uf=f["uf"])
            )
            continue

        session.execute(insert(Filial).values(**f))
