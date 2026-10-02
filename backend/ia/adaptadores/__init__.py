"""Adaptadores de domínio do SuperfrioIA.

Um adaptador por domínio, e **só ele** fala com o módulo dono do dado (`service.py`
do domínio). O resto de `backend/ia` não importa `conexao_dw`, `oracledb`,
`psycopg` nem abre cursor — o teste AST de `test_ia_seguranca.py` cobra isso.

Contrato mínimo de um adaptador (`dominios/__init__.py` o exige no boot):

- `validar_contrato(dados, origem)`: confere o YAML contra o código real do módulo
  dono e levanta `ContratoInvalido` nomeando o erro;
- `descrever(dominio)`: o que o modelo pode saber do domínio (sem nomes de função
  nem caminhos de arquivo);
- `amostrar_valores(dominio, dimensao, termo, ctx)`: valores válidos de uma
  dimensão, **por rótulo**;
- `consultar(dominio, parametros, ctx)`: executa uma consulta ao indicador.
"""
