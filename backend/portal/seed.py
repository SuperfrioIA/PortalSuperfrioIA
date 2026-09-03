"""Seed do catálogo (seções e apps) — idempotente, insere só o que não existe."""
from sqlalchemy import insert, select, update

from backend.portal.models import App, Secao

SECOES = [
    {
        "slug": "armazem",
        "nome": "Armazém",
        "nome_es": "Almacén",
        "descricao": "Operações de armazém, integrações WMS e inventário.",
        "descricao_es": "Operaciones de almacén, integraciones WMS e inventario.",
        "icone": "warehouse",
        "ordem": 1,
    },
    {
        "slug": "backoffice",
        "nome": "Backoffice",
        "nome_es": "Backoffice",
        "descricao": "Processos administrativos, financeiro e suporte interno.",
        "descricao_es": "Procesos administrativos, finanzas y soporte interno.",
        "icone": "briefcase",
        "ordem": 2,
    },
    {
        "slug": "inovacao",
        "nome": "Inovação",
        "nome_es": "Innovación",
        "descricao": "Portfólio de projetos de IA e iniciativas de inovação.",
        "descricao_es": "Portafolio de proyectos de IA e iniciativas de innovación.",
        "icone": "radar",
        "ordem": 3,
    },
    {
        "slug": "tecnologia",
        "nome": "Tecnologia",
        "nome_es": "Tecnología",
        "descricao": "Documentos e mapas da área de tecnologia.",
        "descricao_es": "Documentos y mapas del área de tecnología.",
        "icone": "chip",
        # 90, não 4: produção tem seção criada à mão (QHSE) cuja `ordem` este
        # repositório não conhece. Um número alto evita empate — e Tecnologia
        # como última do menu é ordem razoável. Reordenar é edição de cadastro.
        "ordem": 90,
    },
]

APPS = [
    # Armazém
    {
        "secao": "armazem",
        "slug": "faq-blueyonder",
        "nome": "FAQ BlueYonder",
        "nome_es": "FAQ BlueYonder",
        "descricao": "Perguntas frequentes e procedimentos do WMS BlueYonder.",
        "descricao_es": "Preguntas frecuentes y procedimientos del WMS BlueYonder.",
        "icone": "book",
        "url": "https://example.internal/faq-blueyonder",
        "tipo_acesso": "url",
        "badge": None,
        "ordem": 1,
    },
    {
        "secao": "armazem",
        "slug": "faq-slin",
        "nome": "FAQ Slin",
        "nome_es": "FAQ Slin",
        "descricao": "Base de conhecimento do sistema Slin.",
        "descricao_es": "Base de conocimiento del sistema Slin.",
        "icone": "book",
        "url": "https://example.internal/faq-slin",
        "tipo_acesso": "url",
        "badge": None,
        "ordem": 2,
    },
    {
        "secao": "armazem",
        "slug": "conciliacao-estoque",
        "nome": "Conciliação de Estoque",
        "nome_es": "Conciliación de Inventario",
        "descricao": "Comparação WMS x Protheus e tratativas de divergência.",
        "descricao_es": "Comparación WMS x Protheus y tratamiento de divergencias.",
        "icone": "scale",
        "url": "https://example.internal/conciliacao-estoque",
        "tipo_acesso": "url",
        "badge": "NEW",
        "ordem": 3,
    },
    {
        # Único app do seed que existe de verdade neste repositório
        # (frontend/processos-abertos/, Receita 1) — os demais são exemplos.
        # Precisa estar cadastrado para aparecer como linha na matriz de acesso:
        # é o app dono da permissão `processos-abertos:editar`.
        "secao": "armazem",
        "slug": "processos-abertos",
        "nome": "Processos Abertos",
        "nome_es": "Procesos Abiertos",
        "descricao": "Acompanhamento semanal de recebimento, expedição e portaria em aberto.",
        "descricao_es": "Seguimiento semanal de recepción, expedición y portería abiertos.",
        "icone": "document",
        "url": "/processos-abertos/",
        "tipo_acesso": "iframe",
        "tipo_conteudo": "indicador",
        "badge": None,
        "ordem": 4,
    },
    {
        # Também existe de verdade neste repositório (frontend/integracao-in-out/,
        # Receita 1) — dono da permissão `integracao-in-out:editar`.
        "secao": "armazem",
        "slug": "integracao-in-out",
        "nome": "Integração In/Out",
        "nome_es": "Integración In/Out",
        "descricao": "Pedidos integrados vs. manuais por unidade, mês a mês.",
        "descricao_es": "Pedidos integrados vs. manuales por unidad, mes a mes.",
        "icone": "truck",
        "url": "/integracao-in-out/",
        "tipo_acesso": "iframe",
        "tipo_conteudo": "indicador",
        "badge": "NEW",
        "ordem": 5,
    },
    {
        # Também existe de verdade neste repositório (frontend/gerador-qrcode/,
        # Receita 1) — sem backend, sem banco, só gera e imprime a etiqueta.
        "secao": "armazem",
        "slug": "gerador-qrcode",
        "nome": "Gerador de QR Code (Bipagem)",
        "nome_es": "Generador de Código QR (Escaneo)",
        "descricao": "Gera e imprime a etiqueta de QR Code usada na bipagem.",
        "descricao_es": "Genera e imprime la etiqueta de código QR usada en el escaneo.",
        "icone": "document",
        "url": "/gerador-qrcode/",
        "tipo_acesso": "iframe",
        "badge": None,
        "ordem": 6,
    },
    {
        # Também existe de verdade neste repositório (backend/volumetria_catering/,
        # Receita 2 com a fonte num banco externo) — dono da permissão
        # `volumetria-catering:exportar`, que precisa desta linha para existir na
        # matriz de acesso. A TELA (frontend/volumetria-catering/) é o lote H2: até
        # lá nenhuma role recebe `ver` pelo seed, então só admin vê o card, e a
        # URL responde 404. Ver docs/PLANO_VOLUMETRIA_CATERING.md.
        "secao": "armazem",
        "slug": "volumetria-catering",
        "nome": "Volumetria de Catering",
        "nome_es": "Volumetría de Catering",
        "descricao": "Recebimento e expedição de catering por unidade, cliente e mês, lidos do DW.",
        "descricao_es": "Recepción y expedición de catering por unidad, cliente y mes, leídos del DW.",
        "icone": "scale",
        "url": "/volumetria-catering/",
        "tipo_acesso": "iframe",
        "tipo_conteudo": "indicador",
        "badge": "NEW",
        "ordem": 7,
    },
    {
        # Também existe de verdade (backend/volumetria_transporte/, Receita 2,
        # fonte no DW Oracle direto — sem Postgres intermediário, diferente do
        # catering hoje). Dono de `volumetria-transporte:exportar`. Nenhuma
        # role recebe `ver` pelo seed: só admin vê o card até a Maria decidir
        # quem tem acesso. Ver docs/PLANO_VOLUMETRIA_TRANSPORTE_ESTOQUE.md.
        "secao": "armazem",
        "slug": "volumetria-transporte",
        "nome": "Transporte de Catering",
        "nome_es": "Transporte de Catering",
        "descricao": "Viagens de transporte de catering por unidade, cliente e mês, lidas do DW.",
        "descricao_es": "Viajes de transporte de catering por unidad, cliente y mes, leídos del DW.",
        "icone": "truck",
        "url": "/volumetria-transporte/",
        "tipo_acesso": "iframe",
        "tipo_conteudo": "indicador",
        "badge": "NEW",
        "ordem": 8,
    },
    # Backoffice
    {
        "secao": "backoffice",
        "slug": "duvidas-financeiro",
        "nome": "Dúvidas Financeiro",
        "nome_es": "Consultas Finanzas",
        "descricao": "Canal de dúvidas e tratativas com o financeiro.",
        "descricao_es": "Canal de consultas y tratativas con finanzas.",
        "icone": "chat",
        "url": "https://example.internal/duvidas-financeiro",
        "tipo_acesso": "url",
        "badge": None,
        "ordem": 1,
    },
    {
        "secao": "backoffice",
        "slug": "compras-2-0",
        "nome": "Compras 2.0",
        "nome_es": "Compras 2.0",
        "descricao": "Fluxo renovado de solicitação e aprovação de compras.",
        "descricao_es": "Flujo renovado de solicitud y aprobación de compras.",
        "icone": "cart",
        "url": "https://example.internal/compras-2-0",
        "tipo_acesso": "url",
        "badge": "BETA",
        "ordem": 2,
    },
    {
        "secao": "backoffice",
        "slug": "conciliafat",
        "nome": "ConciliaFAT",
        "nome_es": "ConciliaFAT",
        "descricao": "Conciliação automatizada de notas fiscais de transporte.",
        "descricao_es": "Conciliación automatizada de facturas de transporte.",
        "icone": "document",
        "url": "https://example.internal/conciliafat",
        "tipo_acesso": "url",
        "badge": None,
        "ordem": 3,
    },
    {
        "secao": "backoffice",
        "slug": "controle-recebimento",
        "nome": "Controle de Recebimento",
        "nome_es": "Control de Recepción",
        "descricao": "Acompanhamento de recebimentos e pendências.",
        "descricao_es": "Seguimiento de recepciones y pendientes.",
        "icone": "truck",
        "url": "https://example.internal/controle-recebimento",
        "tipo_acesso": "url",
        "badge": None,
        "ordem": 4,
    },
    # Inovação
    {
        # App real (frontend/projetos-ia/ ou tela nativa do SPA — ver
        # backend/projetos_ia/). Precisa estar cadastrado para aparecer na
        # matriz de acesso: é o app dono da permissão `projetos-ia:editar`.
        # tipo_acesso "interno": abre uma tela nativa do portal, não iframe/URL
        # externa — o valor de `url` é só um identificador, o front reconhece
        # pelo tipo_acesso em `openApp()`.
        "secao": "inovacao",
        "slug": "projetos-ia",
        "nome": "Projetos IA",
        "nome_es": "Proyectos IA",
        "descricao": "Visibilidade executiva do portfólio de projetos de IA: fase, próximo marco e rollout por filial.",
        "descricao_es": "Visibilidad ejecutiva del portafolio de proyectos de IA: fase, próximo hito y despliegue por filial.",
        "icone": "radar",
        "url": "/projetos-ia",
        "tipo_acesso": "interno",
        "badge": None,
        "ordem": 1,
    },
    # Tecnologia
    {
        # Existiam como botão fixo na sidebar, fora do catálogo — ou seja, sem
        # linha na matriz de acesso e sem jeito de controlar quem vê. Viraram app
        # (Receita 1, `frontend/governanca/` e `frontend/mapa-ia/`) justamente
        # para a visibilidade passar a ser dado, não código.
        #
        # Governance TI era visível a qualquer pessoa logada: o grant de `ver`
        # para todas as roles existentes é feito UMA VEZ, na criação do app, em
        # `backend/usuarios/seed.py` — senão quem não é admin perderia o acesso
        # na virada.
        "secao": "tecnologia",
        "slug": "governanca-ti",
        "nome": "Governance TI",
        "nome_es": "Governance TI",
        "descricao": "Apresentação da governança de TI: estrutura, papéis e diretrizes.",
        "descricao_es": "Presentación de la gobernanza de TI: estructura, roles y directrices.",
        "icone": "presentation",
        "url": "/governanca/",
        "tipo_acesso": "iframe",
        "badge": None,
        "ordem": 1,
    },
    {
        # Sem grant nenhum de propósito: só admin enxerga (admin passa por cima
        # da matriz). Atenção: isso esconde o CARD, não fecha a URL — apps
        # estáticos são servidos sem login (ver docs/PERMISSIONAMENTO_HOJE.md).
        "secao": "tecnologia",
        "slug": "mapa-ia",
        "nome": "Mapa IA",
        "nome_es": "Mapa IA",
        "descricao": "Mapa do ecossistema de IA: sistemas, integrações e iniciativas.",
        "descricao_es": "Mapa del ecosistema de IA: sistemas, integraciones e iniciativas.",
        "icone": "network",
        "url": "/mapa-ia/",
        "tipo_acesso": "iframe",
        "badge": None,
        "ordem": 2,
    },
]


def seed(session) -> set[str]:
    """Semeia seções e apps. Devolve os slugs de app CRIADOS nesta execução.

    Quem precisa reagir à criação de um app (o grant inicial de `ver`, em
    `backend/usuarios/seed.py`) usa esse retorno para agir só na virada — nunca
    a cada boot, senão o seed desfaria uma revogação feita pelo administrador.
    """
    criados: set[str] = set()

    for s in SECOES:
        existe = session.execute(
            select(Secao.id).where(Secao.slug == s["slug"])
        ).scalar_one_or_none()
        if existe is None:
            session.execute(
                insert(Secao).values(
                    slug=s["slug"], nome=s["nome"], nome_es=s["nome_es"],
                    descricao=s["descricao"], descricao_es=s["descricao_es"],
                    icone=s["icone"], ordem=s["ordem"],
                )
            )
        # Backfill ES em bancos já seedados (não sobrescreve edição do admin)
        session.execute(
            update(Secao)
            .where(Secao.slug == s["slug"], Secao.nome_es.is_(None))
            .values(nome_es=s["nome_es"], descricao_es=s["descricao_es"])
        )

    secao_id = {
        slug: id_ for id_, slug in session.execute(select(Secao.id, Secao.slug))
    }

    for a in APPS:
        existe = session.execute(
            select(App.id).where(App.slug == a["slug"])
        ).scalar_one_or_none()
        if existe is None:
            session.execute(
                insert(App).values(
                    slug=a["slug"], nome=a["nome"], nome_es=a["nome_es"],
                    descricao=a["descricao"], descricao_es=a["descricao_es"],
                    icone=a["icone"], secao_id=secao_id[a["secao"]],
                    url=a["url"], tipo_acesso=a["tipo_acesso"],
                    # Só os indicadores declaram: 'sistema' é o caso comum e o
                    # default da coluna (migration 0006).
                    tipo_conteudo=a.get("tipo_conteudo", "sistema"),
                    badge=a["badge"], ordem=a["ordem"],
                )
            )
            criados.add(a["slug"])
        # Backfill ES em bancos já seedados (não sobrescreve edição do admin)
        session.execute(
            update(App)
            .where(App.slug == a["slug"], App.nome_es.is_(None))
            .values(nome_es=a["nome_es"], descricao_es=a["descricao_es"])
        )

    return criados
