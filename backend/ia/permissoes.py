"""Autorização do SuperfrioIA: as portas e a concessão de uso do domínio.

Uma consulta só acontece quando **todas** estas dizem sim, revalidadas a cada
pergunta e a cada leitura de histórico (arquitetura §14.4):

1. **identidade** — login do Hub (JWT, usuário ativo, `token_version`), feito por
   `get_current_user` antes de chegar aqui;
2. **autorização do sistema** — `<app_hub>:ver` do domínio (D-L2a, DD-23): é o
   acesso do próprio app Volumetria de Catering, que não é copiado nem substituído;
3. **concessão de IA vigente** para o domínio (DD-2): "pode usar IA neste domínio",
   aprovada por quem tem `<app_hub>:administrar` (DD-13).

Ver o card (`superfrioia:ver`) é só visibilidade, exigida na porta da rota. O
alcance dentro do domínio é do sistema dono; aqui ele é `integral` por contrato
(`escopo_usuario: nenhum`) e isso fica registrado em cada consulta.

## A concessão

Uma tabela, quatro estados (`ia_concessoes`): `pendente`, `ativa`, `negada`,
`revogada`. **Vencida não é estado**: é `ativa` com `validade_ate` no passado,
decidido na leitura, então o vencimento vale no segundo exato, sem job.

- um pedido `pendente` por (usuário, domínio) e uma `ativa` por (usuário,
  domínio) — o banco garante com índice único parcial;
- aprovar uma renovação revoga a anterior (`motivo_revogacao` "substituída");
- revogar vale **na próxima pergunta** e também para o histórico (§14.4);
- autoaprovação (admin aprovando o próprio pedido) é permitida na PoC e marcada
  `autoaprovacao: true`; `IA_AUTOAPROVACAO=false` a proíbe, e **tem que estar
  assim antes do piloto** (DD-13).
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError

from backend.auth.dependencies import usuario_pode
from backend.core.database import _now, db
from backend.ia import auditoria, config
from backend.ia.models import IaConcessao
from backend.ia.politicas import Recusa, mascarar

_T = IaConcessao.__table__
_NEUTRA = "Você não tem acesso a este domínio."
MOTIVO_MAXIMO = 500
VALIDADE_MAXIMA_DIAS = 365
LISTA_MAXIMA = 200


def _agora_mais(dias: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=dias)).strftime("%Y-%m-%d %H:%M:%S")


def _linha(row) -> dict:
    d = dict(row)
    agora = _now()
    d["vencida"] = d["status"] == "ativa" and bool(d["validade_ate"]) and d["validade_ate"] <= agora
    d["vigente"] = d["status"] == "ativa" and not d["vencida"]
    d["vence_em_30_dias"] = bool(
        d["vigente"] and d["validade_ate"] and d["validade_ate"] <= _agora_mais(30)
    )
    d["autoaprovacao"] = bool(d["autoaprovacao"])
    return d


# ------------------------------------------------------------------ leitura
def concessao_vigente(session, usuario_id: int, dominio: str) -> dict | None:
    row = session.execute(
        select(_T).where(_T.c.usuario_id == usuario_id, _T.c.dominio == dominio,
                         _T.c.status == "ativa", _T.c.validade_ate > _now())
    ).mappings().fetchone()
    return _linha(row) if row else None


def estado_do_acesso(user: dict, dominio) -> dict:
    """O estado que a tela mostra para este usuário neste domínio. Nunca vaza
    detalhe técnico: o mesmo `estado` serve para a tela e para o teste."""
    if not usuario_pode(user, f"{dominio.app_hub}:ver"):
        return {"estado": "sem_ver_sistema"}
    with db() as session:
        if concessao_vigente(session, user["id"], dominio.slug):
            return {"estado": "liberado"}
        ultima = session.execute(
            select(_T).where(_T.c.usuario_id == user["id"], _T.c.dominio == dominio.slug)
            .order_by(_T.c.id.desc()).limit(1)
        ).mappings().fetchone()
    if ultima is None:
        return {"estado": "sem_concessao"}
    ultima = _linha(ultima)
    if ultima["status"] == "pendente":
        return {"estado": "pendente", "pedido_em": ultima["pedido_em"]}
    if ultima["status"] == "negada":
        return {"estado": "negada", "motivo": ultima["motivo_decisao"]}
    if ultima["status"] == "revogada":
        return {"estado": "revogada"}
    return {"estado": "vencida", "validade_ate": ultima["validade_ate"]}


def exigir_acesso(user: dict, dominio) -> None:
    """As portas 2 e 3, revalidadas agora. Levanta `Recusa(403)` com mensagem neutra."""
    if not usuario_pode(user, f"{dominio.app_hub}:ver"):
        raise Recusa(403, "sem_ver_sistema", _NEUTRA)
    with db() as session:
        if concessao_vigente(session, user["id"], dominio.slug) is None:
            raise Recusa(403, "sem_concessao", _NEUTRA)


def pode_administrar(user: dict, dominio) -> bool:
    return usuario_pode(user, dominio.permissao_de_aprovacao)


# ------------------------------------------------------------------- pedido
def _tem_pendente(session, usuario_id: int, dominio: str) -> bool:
    return session.execute(
        select(_T.c.id).where(_T.c.usuario_id == usuario_id, _T.c.dominio == dominio, _T.c.status == "pendente")
    ).first() is not None


def pedir_acesso(user: dict, dominio, motivo: str, ip: str | None) -> dict:
    motivo, _ = mascarar((motivo or "").strip())
    if not motivo:
        raise Recusa(400, "motivo_vazio", "Informe o motivo do pedido.")
    if len(motivo) > MOTIVO_MAXIMO:
        raise Recusa(400, "motivo_longo", f"O motivo pode ter até {MOTIVO_MAXIMO} caracteres.")
    if not usuario_pode(user, f"{dominio.app_hub}:ver"):
        # Sem o acesso ao próprio app, a concessão de IA não ajudaria: o caminho é pedir o app.
        raise Recusa(403, "sem_ver_sistema", _NEUTRA)

    with db() as session:
        if concessao_vigente(session, user["id"], dominio.slug):
            raise Recusa(409, "ja_liberado", "Você já tem acesso a este domínio.")
        if _tem_pendente(session, user["id"], dominio.slug):
            raise Recusa(409, "pedido_pendente", "Já existe um pedido seu em análise para este domínio.")
        try:
            novo = session.execute(insert(IaConcessao).values(
                usuario_id=user["id"], username=user["username"], dominio=dominio.slug,
                status="pendente", motivo_pedido=motivo, pedido_em=_now(), autoaprovacao=0,
            )).inserted_primary_key[0]
        except IntegrityError:
            # duplo clique / dois dispositivos: o índice único parcial barrou o segundo
            raise Recusa(409, "pedido_pendente", "Já existe um pedido seu em análise para este domínio.") from None
        auditoria.concessao(session, "pedida", user, ip, dominio=dominio.slug,
                            concessao_id=novo, usuario=user["username"], detalhes={"motivo": motivo})
        return _linha(session.execute(select(_T).where(_T.c.id == novo)).mappings().one())


def minhas_concessoes(user: dict) -> list[dict]:
    with db() as session:
        rows = session.execute(
            select(_T).where(_T.c.usuario_id == user["id"]).order_by(_T.c.id.desc()).limit(LISTA_MAXIMA)
        ).mappings().all()
    return [_linha(r) for r in rows]


# -------------------------------------------------------------- administração
def listar(dominio, status: str | None = None) -> list[dict]:
    consulta = select(_T).where(_T.c.dominio == dominio.slug)
    if status:
        consulta = consulta.where(_T.c.status == status)
    with db() as session:
        rows = session.execute(consulta.order_by(_T.c.id.desc()).limit(LISTA_MAXIMA)).mappings().all()
    return [_linha(r) for r in rows]


def _carregar(session, concessao_id: int) -> dict:
    row = session.execute(select(_T).where(_T.c.id == concessao_id)).mappings().fetchone()
    if row is None:
        raise Recusa(404, "nao_encontrada", "Pedido não encontrado.")
    return dict(row)


def _exigir_uma_linha(resultado) -> None:
    """O `UPDATE ... WHERE status = <esperado>` mudou exatamente uma linha? Se não, outra
    decisão chegou primeiro (dois aprovadores ao mesmo tempo): o último NÃO vence, a
    transação inteira é desfeita (inclusive a auditoria) e quem chegou depois leva 409."""
    if resultado.rowcount != 1:
        raise Recusa(409, "ja_decidido", "Este pedido já foi decidido por outra pessoa. Atualize a lista.")


def aprovar(admin: dict, concessao_id: int, *, motivo: str | None, validade_dias: int | None, ip: str | None) -> dict:
    dias = validade_dias if validade_dias is not None else config.validade_concessao_dias()
    if not 1 <= dias <= VALIDADE_MAXIMA_DIAS:
        raise Recusa(400, "validade_invalida", f"A validade vai de 1 a {VALIDADE_MAXIMA_DIAS} dias.")
    with db() as session:
        atual = _carregar(session, concessao_id)
        if atual["status"] != "pendente":
            raise Recusa(409, "nao_pendente", "Este pedido já foi decidido.")
        autoaprovacao = atual["usuario_id"] == admin["id"]
        if autoaprovacao and not config.autoaprovacao_permitida():
            raise Recusa(403, "autoaprovacao_proibida",
                         "Você não pode aprovar o seu próprio pedido. Peça a outra pessoa.")
        # renovação: a concessão anterior sai de cena antes de a nova virar ativa
        session.execute(update(_T).where(
            _T.c.usuario_id == atual["usuario_id"], _T.c.dominio == atual["dominio"], _T.c.status == "ativa",
        ).values(status="revogada", revogado_por=admin["username"], revogado_em=_now(),
                 motivo_revogacao="substituída por renovação"))
        validade = _agora_mais(dias)
        try:
            feito = session.execute(update(_T).where(_T.c.id == concessao_id, _T.c.status == "pendente").values(
                status="ativa", decidido_por=admin["username"], decidido_em=_now(),
                motivo_decisao=(motivo or None), validade_ate=validade, autoaprovacao=int(autoaprovacao)))
        except IntegrityError:
            raise Recusa(409, "nao_pendente", "Este pedido já foi decidido.") from None
        _exigir_uma_linha(feito)   # alguém decidiu entre a leitura e a escrita: desfaz tudo (rollback)
        auditoria.concessao(session, "aprovada", admin, ip, dominio=atual["dominio"], concessao_id=concessao_id,
                            usuario=atual["username"], detalhes={
                                "aprovador": admin["username"], "validade_ate": validade, "validade_dias": dias,
                                "motivo": motivo, "autoaprovacao": autoaprovacao})
        return _linha(_carregar(session, concessao_id))


def negar(admin: dict, concessao_id: int, *, motivo: str, ip: str | None) -> dict:
    if not (motivo or "").strip():
        raise Recusa(400, "motivo_vazio", "Informe o motivo da negativa.")
    with db() as session:
        atual = _carregar(session, concessao_id)
        if atual["status"] != "pendente":
            raise Recusa(409, "nao_pendente", "Este pedido já foi decidido.")
        feito = session.execute(update(_T).where(_T.c.id == concessao_id, _T.c.status == "pendente").values(
            status="negada", decidido_por=admin["username"], decidido_em=_now(), motivo_decisao=motivo.strip()))
        _exigir_uma_linha(feito)
        auditoria.concessao(session, "negada", admin, ip, dominio=atual["dominio"], concessao_id=concessao_id,
                            usuario=atual["username"],
                            detalhes={"aprovador": admin["username"], "motivo": motivo.strip()})
        return _linha(_carregar(session, concessao_id))


def revogar(admin: dict, concessao_id: int, *, motivo: str, ip: str | None) -> dict:
    if not (motivo or "").strip():
        raise Recusa(400, "motivo_vazio", "Informe o motivo da revogação.")
    with db() as session:
        atual = _carregar(session, concessao_id)
        if atual["status"] != "ativa":
            raise Recusa(409, "nao_ativa", "Só uma concessão ativa pode ser revogada.")
        feito = session.execute(update(_T).where(_T.c.id == concessao_id, _T.c.status == "ativa").values(
            status="revogada", revogado_por=admin["username"], revogado_em=_now(),
            motivo_revogacao=motivo.strip()))
        _exigir_uma_linha(feito)
        auditoria.concessao(session, "revogada", admin, ip, dominio=atual["dominio"], concessao_id=concessao_id,
                            usuario=atual["username"],
                            detalhes={"aprovador": admin["username"], "motivo": motivo.strip()})
        return _linha(_carregar(session, concessao_id))


def dominio_da_concessao(concessao_id: int) -> str | None:
    """O domínio de uma concessão, para a rota conferir `administrar` DAQUELE domínio
    antes de decidir (um aprovador de um domínio não decide o de outro)."""
    with db() as session:
        return session.execute(select(_T.c.dominio).where(_T.c.id == concessao_id)).scalar_one_or_none()
