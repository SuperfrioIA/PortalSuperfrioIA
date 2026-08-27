-- Schema `cat_*` da nuvem-ia NO ESTADO FINAL das migrations 0019 → 0024
-- (main, 27/ago/2026), SÓ para o banco de teste desta suíte.
--
-- Isto NÃO é fonte de verdade de schema: a fonte são as migrations do
-- repositório nuvem-ia. Esta cópia existe porque a suíte do Hub não pode
-- depender de outro repositório para rodar, e porque `schema.py` (a verificação
-- de drift) precisa de um banco com a forma esperada para provar que aceita o
-- certo e recusa o errado. Se a nuvem-ia mudar o schema, esta cópia muda junto
-- com `backend/volumetria_catering/contrato.py` — na mesma PR.
--
-- O que ficou de fora, de propósito: `cat_auditoria` e `cat_usuarios` (o Hub
-- nunca as lê; aposentam no H4).

CREATE TABLE cat_unidades (
    sigla_fonte  TEXT PRIMARY KEY,
    sigla        TEXT NOT NULL,
    nome_und     TEXT NOT NULL,
    visto_em     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE cat_clientes (
    raiz_cnpj     TEXT PRIMARY KEY,
    razao_social  TEXT NOT NULL,
    grafias       JSONB NOT NULL DEFAULT '[]',
    visto_em      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE cat_tipos_estoque (
    nome_estoque  TEXT PRIMARY KEY,
    tipo          TEXT NOT NULL,
    regra         TEXT NOT NULL DEFAULT '',
    visto_em      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_cat_tipo CHECK (tipo IN
        ('CONGELADO', 'SECO', 'HORTIFRUTI', 'UTENSILIOS', 'RESFRIADO',
         'NAO_CLASSIFICADO'))
);

CREATE TABLE cat_cargas (
    id                    SERIAL PRIMARY KEY,
    tabela_origem         TEXT NOT NULL,
    iniciada_em           TIMESTAMPTZ NOT NULL DEFAULT now(),
    terminada_em          TIMESTAMPTZ,
    status                TEXT NOT NULL DEFAULT 'rodando',
    linhas_lidas          INTEGER NOT NULL DEFAULT 0,
    linhas_inseridas      INTEGER NOT NULL DEFAULT 0,
    linhas_atualizadas    INTEGER NOT NULL DEFAULT 0,
    max_dw_data_alteracao TIMESTAMP,
    janela_de             DATE,
    janela_ate            DATE,
    erro                  TEXT,
    -- 0020
    fonte                 TEXT NOT NULL DEFAULT 'csv',
    CONSTRAINT ck_cat_carga_status CHECK (status IN
        ('rodando', 'ok', 'erro', 'sem_dado')),
    CONSTRAINT ck_cat_carga_fonte CHECK (fonte IN ('csv', 'oracle'))
);

-- Procedência + dimensões: idêntico nos dois fatos (0019), com `sk_cliente` e
-- `nk_wms_cliente` nuláveis (0024).
CREATE TABLE cat_fato_recebimento (
    id                BIGSERIAL PRIMARY KEY,
    carga_id          INTEGER NOT NULL REFERENCES cat_cargas(id),
    pk_dw             INTEGER NOT NULL,
    dw_processo       TEXT NOT NULL,
    dw_data_inclusao  TIMESTAMP NOT NULL,
    dw_data_alteracao TIMESTAMP NOT NULL,
    sk_calendario     INTEGER NOT NULL,
    sk_instancia      INTEGER NOT NULL,
    sk_empresa        INTEGER NOT NULL,
    sk_filial         INTEGER NOT NULL,
    sk_cliente        INTEGER,
    nk_calendario     DATE NOT NULL,
    nk_instancia      TEXT NOT NULL,
    nk_empresa        TEXT NOT NULL,
    nk_filial         TEXT NOT NULL,
    nk_wms_filial     TEXT NOT NULL,
    nk_qls_filial     TEXT NOT NULL,
    nk_slin_empresa   TEXT NOT NULL,
    nk_slin_filial    TEXT NOT NULL,
    nk_cliente        TEXT NOT NULL,
    nk_wms_cliente    TEXT,
    data_solic        DATE NOT NULL,
    ano_solic         SMALLINT NOT NULL,
    dthr_confirm      TIMESTAMP,
    nome_und          TEXT NOT NULL,
    num_gem           TEXT NOT NULL,
    cnpj_cpf_cli      TEXT NOT NULL,
    raz_social        TEXT NOT NULL,
    descr_oper_wms    TEXT NOT NULL,
    nome_estoque      TEXT NOT NULL,
    status_processo   TEXT NOT NULL,
    flg_interface     TEXT NOT NULL,
    qtde_sku          INTEGER,
    qtde_pallet       INTEGER,
    qtde_vol2         INTEGER,
    qtde_peso2        NUMERIC(18,3),
    qtde_pbrt2        NUMERIC(18,3),
    qtde_vlr          NUMERIC(18,3),
    -- 0023: identidade com ano_solic, restrição nomeada
    CONSTRAINT uq_cat_fato_rec_identidade UNIQUE
        (nk_instancia, nk_wms_filial, num_gem, ano_solic, nome_estoque,
         descr_oper_wms, nk_cliente)
);

CREATE TABLE cat_fato_expedicao (
    id                BIGSERIAL PRIMARY KEY,
    carga_id          INTEGER NOT NULL REFERENCES cat_cargas(id),
    pk_dw             INTEGER NOT NULL,
    dw_processo       TEXT NOT NULL,
    dw_data_inclusao  TIMESTAMP NOT NULL,
    dw_data_alteracao TIMESTAMP NOT NULL,
    sk_calendario     INTEGER NOT NULL,
    sk_instancia      INTEGER NOT NULL,
    sk_empresa        INTEGER NOT NULL,
    sk_filial         INTEGER NOT NULL,
    sk_cliente        INTEGER,
    nk_calendario     DATE NOT NULL,
    nk_instancia      TEXT NOT NULL,
    nk_empresa        TEXT NOT NULL,
    nk_filial         TEXT NOT NULL,
    nk_wms_filial     TEXT NOT NULL,
    nk_qls_filial     TEXT NOT NULL,
    nk_slin_empresa   TEXT NOT NULL,
    nk_slin_filial    TEXT NOT NULL,
    nk_cliente        TEXT NOT NULL,
    nk_wms_cliente    TEXT,
    data_solic        DATE NOT NULL,
    ano_solic         SMALLINT NOT NULL,
    dthr_confirm      TIMESTAMP,
    nome_und          TEXT NOT NULL,
    num_gem           TEXT NOT NULL,
    cnpj_cpf_cli      TEXT NOT NULL,
    raz_social        TEXT NOT NULL,
    descr_oper_wms    TEXT NOT NULL,
    nome_estoque      TEXT NOT NULL,
    status_processo   TEXT NOT NULL,
    flg_interface     TEXT NOT NULL,
    qtde_pedido            INTEGER,
    qtde_sku_solicitado    INTEGER,
    qtde_vol_solicitado    INTEGER,
    qtde_peso_solicitado   NUMERIC(18,3),
    qtde_pbrt_solicitado   NUMERIC(18,3),
    qtde_vlr_solicitado    NUMERIC(18,3),
    qtde_sku_atendido      INTEGER,
    qtde_vol_atendido      INTEGER,
    qtde_peso_atendido     NUMERIC(18,3),
    qtde_pbrt_atendido     NUMERIC(18,3),
    qtde_vlr_atendido      NUMERIC(18,3),
    qtde_sku_separado      INTEGER,
    qtde_vol_separado      INTEGER,
    qtde_peso_separado     NUMERIC(18,3),
    qtde_pbrt_separado     NUMERIC(18,3),
    qtde_vlr_separado      NUMERIC(18,3),
    CONSTRAINT uq_cat_fato_exp_identidade UNIQUE
        (nk_instancia, nk_wms_filial, num_gem, ano_solic, nome_estoque,
         descr_oper_wms, nk_cliente)
);

CREATE INDEX ix_cat_fato_rec_periodo ON cat_fato_recebimento (nk_calendario, nk_wms_filial);
CREATE INDEX ix_cat_fato_exp_periodo ON cat_fato_expedicao (nk_calendario, nk_wms_filial);
