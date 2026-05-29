"""
CRUD admin do Portal SuperFrio.

Princípios:
- Toggle ativo/inativo em vez de DELETE (auditável).
- PATCH é parcial: só atualiza o que vier no body.
- Slug é stable: nunca é editado depois de criado.
- Validações no boundary, erros HTTP claros.
"""
import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.auth import hash_password, require_admin
from backend.database import get_conn

PASSWORD_MIN_LEN = 8

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ============ Helpers ============

def _now_sql() -> str:
    return "datetime('now')"


def _slug_ok(slug: str) -> bool:
    return bool(slug) and all(c.isalnum() or c in "-_" for c in slug) and slug == slug.lower()


def _ensure_slug(slug: str) -> None:
    if not _slug_ok(slug):
        raise HTTPException(
            status_code=400,
            detail="slug deve ser minúsculo, com letras, números, '-' ou '_'",
        )


def _row_or_404(conn, table: str, row_id: int) -> dict:
    row = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"{table} {row_id} não encontrado")
    return dict(row)


# ============ Seções ============

class SecaoCreate(BaseModel):
    slug: str
    nome: str
    descricao: Optional[str] = None
    icone: Optional[str] = None
    ordem: int = 0


class SecaoUpdate(BaseModel):
    nome: Optional[str] = None
    descricao: Optional[str] = None
    icone: Optional[str] = None
    ordem: Optional[int] = None


@router.get("/secoes")
def listar_secoes(_: dict = Depends(require_admin)):
    conn = get_conn()
    try:
        rows = conn.execute(
            """SELECT s.*, COUNT(a.id) AS apps_count
               FROM secoes s
               LEFT JOIN apps a ON a.secao_id = s.id
               GROUP BY s.id
               ORDER BY s.ordem, s.nome"""
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


@router.post("/secoes", status_code=201)
def criar_secao(body: SecaoCreate, _: dict = Depends(require_admin)):
    _ensure_slug(body.slug)
    conn = get_conn()
    try:
        try:
            cur = conn.execute(
                """INSERT INTO secoes (slug, nome, descricao, icone, ordem)
                   VALUES (?, ?, ?, ?, ?)""",
                (body.slug, body.nome, body.descricao, body.icone, body.ordem),
            )
        except sqlite3.IntegrityError as e:
            if "UNIQUE" in str(e):
                raise HTTPException(409, f"slug '{body.slug}' já existe")
            raise
        conn.commit()
        row = conn.execute("SELECT * FROM secoes WHERE id = ?", (cur.lastrowid,)).fetchone()
    finally:
        conn.close()
    return dict(row)


@router.patch("/secoes/{secao_id}")
def atualizar_secao(secao_id: int, body: SecaoUpdate, _: dict = Depends(require_admin)):
    conn = get_conn()
    try:
        _row_or_404(conn, "secoes", secao_id)
        fields = body.model_dump(exclude_unset=True)
        if not fields:
            return _row_or_404(conn, "secoes", secao_id)
        sets = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(f"UPDATE secoes SET {sets} WHERE id = ?", (*fields.values(), secao_id))
        conn.commit()
        return _row_or_404(conn, "secoes", secao_id)
    finally:
        conn.close()


@router.post("/secoes/{secao_id}/toggle")
def toggle_secao(secao_id: int, _: dict = Depends(require_admin)):
    conn = get_conn()
    try:
        row = _row_or_404(conn, "secoes", secao_id)
        novo = 0 if row["ativo"] else 1
        conn.execute("UPDATE secoes SET ativo = ? WHERE id = ?", (novo, secao_id))
        conn.commit()
        return _row_or_404(conn, "secoes", secao_id)
    finally:
        conn.close()


# ============ Apps ============

class AppCreate(BaseModel):
    slug: str
    nome: str
    secao_id: int
    url: str
    descricao: Optional[str] = None
    icone: Optional[str] = None
    tipo_acesso: str = "url"
    badge: Optional[str] = None
    ordem: int = 0


class AppUpdate(BaseModel):
    nome: Optional[str] = None
    descricao: Optional[str] = None
    icone: Optional[str] = None
    secao_id: Optional[int] = None
    url: Optional[str] = None
    tipo_acesso: Optional[str] = None
    badge: Optional[str] = None
    ordem: Optional[int] = None


def _check_tipo_acesso(tipo: Optional[str]) -> None:
    if tipo is not None and tipo not in ("url", "iframe"):
        raise HTTPException(400, "tipo_acesso deve ser 'url' ou 'iframe'")


def _check_url(url: Optional[str]) -> None:
    if url is None:
        return
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "url deve começar com http:// ou https://")


@router.get("/apps")
def listar_apps(_: dict = Depends(require_admin)):
    conn = get_conn()
    try:
        rows = conn.execute(
            """SELECT a.*, s.slug AS secao_slug, s.nome AS secao_nome
               FROM apps a
               JOIN secoes s ON s.id = a.secao_id
               ORDER BY s.ordem, a.ordem, a.nome"""
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


@router.post("/apps", status_code=201)
def criar_app(body: AppCreate, _: dict = Depends(require_admin)):
    _ensure_slug(body.slug)
    _check_tipo_acesso(body.tipo_acesso)
    _check_url(body.url)
    conn = get_conn()
    try:
        _row_or_404(conn, "secoes", body.secao_id)
        try:
            cur = conn.execute(
                """INSERT INTO apps
                   (slug, nome, descricao, icone, secao_id, url, tipo_acesso, badge, ordem)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    body.slug, body.nome, body.descricao, body.icone,
                    body.secao_id, body.url, body.tipo_acesso, body.badge, body.ordem,
                ),
            )
        except sqlite3.IntegrityError as e:
            if "UNIQUE" in str(e):
                raise HTTPException(409, f"slug '{body.slug}' já existe")
            raise
        conn.commit()
        row = conn.execute(
            """SELECT a.*, s.slug AS secao_slug, s.nome AS secao_nome
               FROM apps a JOIN secoes s ON s.id = a.secao_id
               WHERE a.id = ?""",
            (cur.lastrowid,),
        ).fetchone()
    finally:
        conn.close()
    return dict(row)


@router.patch("/apps/{app_id}")
def atualizar_app(app_id: int, body: AppUpdate, _: dict = Depends(require_admin)):
    _check_tipo_acesso(body.tipo_acesso)
    _check_url(body.url)
    conn = get_conn()
    try:
        _row_or_404(conn, "apps", app_id)
        if body.secao_id is not None:
            _row_or_404(conn, "secoes", body.secao_id)
        fields = body.model_dump(exclude_unset=True)
        if not fields:
            return _select_app(conn, app_id)
        fields["atualizado_em"] = None  # placeholder, sobrescrito no SQL abaixo
        sets = ", ".join(
            "atualizado_em = datetime('now')" if k == "atualizado_em" else f"{k} = ?"
            for k in fields
        )
        values = [v for k, v in fields.items() if k != "atualizado_em"]
        conn.execute(f"UPDATE apps SET {sets} WHERE id = ?", (*values, app_id))
        conn.commit()
        return _select_app(conn, app_id)
    finally:
        conn.close()


def _select_app(conn, app_id: int) -> dict:
    row = conn.execute(
        """SELECT a.*, s.slug AS secao_slug, s.nome AS secao_nome
           FROM apps a JOIN secoes s ON s.id = a.secao_id
           WHERE a.id = ?""",
        (app_id,),
    ).fetchone()
    if not row:
        raise HTTPException(404, f"app {app_id} não encontrado")
    return dict(row)


@router.post("/apps/{app_id}/toggle")
def toggle_app(app_id: int, _: dict = Depends(require_admin)):
    conn = get_conn()
    try:
        row = _row_or_404(conn, "apps", app_id)
        novo = 0 if row["ativo"] else 1
        conn.execute(
            "UPDATE apps SET ativo = ?, atualizado_em = datetime('now') WHERE id = ?",
            (novo, app_id),
        )
        conn.commit()
        return _select_app(conn, app_id)
    finally:
        conn.close()


# ============ Roles ============

class RoleCreate(BaseModel):
    slug: str
    nome: str
    descricao: Optional[str] = None
    apps: list[str] = Field(default_factory=list)  # slugs dos apps


class RoleUpdate(BaseModel):
    nome: Optional[str] = None
    descricao: Optional[str] = None
    apps: Optional[list[str]] = None


def _apps_ids_por_slug(conn, slugs: list[str]) -> list[int]:
    if not slugs:
        return []
    placeholders = ",".join("?" * len(slugs))
    rows = conn.execute(
        f"SELECT id, slug FROM apps WHERE slug IN ({placeholders})", slugs
    ).fetchall()
    encontrados = {r["slug"]: r["id"] for r in rows}
    faltando = [s for s in slugs if s not in encontrados]
    if faltando:
        raise HTTPException(400, f"app slug(s) inexistente(s): {', '.join(faltando)}")
    return [encontrados[s] for s in slugs]


def _set_role_apps(conn, role_id: int, app_ids: list[int]) -> None:
    conn.execute("DELETE FROM role_apps WHERE role_id = ?", (role_id,))
    for aid in app_ids:
        conn.execute(
            "INSERT INTO role_apps (role_id, app_id) VALUES (?, ?)", (role_id, aid)
        )


def _select_role(conn, role_id: int) -> dict:
    row = _row_or_404(conn, "roles", role_id)
    app_slugs = [
        r["slug"]
        for r in conn.execute(
            """SELECT a.slug FROM role_apps ra JOIN apps a ON a.id = ra.app_id
               WHERE ra.role_id = ? ORDER BY a.slug""",
            (role_id,),
        ).fetchall()
    ]
    return {**row, "apps": app_slugs}


@router.get("/roles")
def listar_roles(_: dict = Depends(require_admin)):
    conn = get_conn()
    try:
        rows = conn.execute("SELECT * FROM roles ORDER BY nome").fetchall()
        apps_por_role: dict[int, list[str]] = {}
        for ra in conn.execute(
            """SELECT ra.role_id, a.slug
               FROM role_apps ra JOIN apps a ON a.id = ra.app_id
               ORDER BY a.slug"""
        ).fetchall():
            apps_por_role.setdefault(ra["role_id"], []).append(ra["slug"])
        users_por_role: dict[int, int] = {}
        for ur in conn.execute(
            "SELECT role_id, COUNT(*) AS n FROM usuario_roles GROUP BY role_id"
        ).fetchall():
            users_por_role[ur["role_id"]] = ur["n"]
    finally:
        conn.close()
    return [
        {
            **dict(r),
            "apps": apps_por_role.get(r["id"], []),
            "usuarios_count": users_por_role.get(r["id"], 0),
        }
        for r in rows
    ]


@router.post("/roles", status_code=201)
def criar_role(body: RoleCreate, _: dict = Depends(require_admin)):
    _ensure_slug(body.slug)
    conn = get_conn()
    try:
        app_ids = _apps_ids_por_slug(conn, body.apps)
        try:
            cur = conn.execute(
                "INSERT INTO roles (slug, nome, descricao) VALUES (?, ?, ?)",
                (body.slug, body.nome, body.descricao),
            )
        except sqlite3.IntegrityError as e:
            if "UNIQUE" in str(e):
                raise HTTPException(409, f"slug '{body.slug}' já existe")
            raise
        role_id = cur.lastrowid
        _set_role_apps(conn, role_id, app_ids)
        conn.commit()
        return _select_role(conn, role_id)
    finally:
        conn.close()


@router.patch("/roles/{role_id}")
def atualizar_role(role_id: int, body: RoleUpdate, _: dict = Depends(require_admin)):
    conn = get_conn()
    try:
        _row_or_404(conn, "roles", role_id)
        fields = body.model_dump(exclude_unset=True)
        apps = fields.pop("apps", None)
        if fields:
            sets = ", ".join(f"{k} = ?" for k in fields)
            conn.execute(f"UPDATE roles SET {sets} WHERE id = ?", (*fields.values(), role_id))
        if apps is not None:
            app_ids = _apps_ids_por_slug(conn, apps)
            _set_role_apps(conn, role_id, app_ids)
        conn.commit()
        return _select_role(conn, role_id)
    finally:
        conn.close()


@router.post("/roles/{role_id}/toggle")
def toggle_role(role_id: int, _: dict = Depends(require_admin)):
    conn = get_conn()
    try:
        row = _row_or_404(conn, "roles", role_id)
        novo = 0 if row["ativo"] else 1
        conn.execute("UPDATE roles SET ativo = ? WHERE id = ?", (novo, role_id))
        conn.commit()
        return _select_role(conn, role_id)
    finally:
        conn.close()


# ============ Usuários ============

class UsuarioCreate(BaseModel):
    username: str
    senha: str
    nome: Optional[str] = None
    email: Optional[str] = None
    is_admin: bool = False
    roles: list[str] = Field(default_factory=list)  # slugs


class UsuarioUpdate(BaseModel):
    nome: Optional[str] = None
    email: Optional[str] = None
    is_admin: Optional[bool] = None
    roles: Optional[list[str]] = None


class PasswordReset(BaseModel):
    senha: str = Field(min_length=PASSWORD_MIN_LEN)


def _roles_ids_por_slug(conn, slugs: list[str]) -> list[int]:
    if not slugs:
        return []
    placeholders = ",".join("?" * len(slugs))
    rows = conn.execute(
        f"SELECT id, slug FROM roles WHERE slug IN ({placeholders})", slugs
    ).fetchall()
    encontrados = {r["slug"]: r["id"] for r in rows}
    faltando = [s for s in slugs if s not in encontrados]
    if faltando:
        raise HTTPException(400, f"role slug(s) inexistente(s): {', '.join(faltando)}")
    return [encontrados[s] for s in slugs]


def _set_user_roles(conn, user_id: int, role_ids: list[int]) -> None:
    conn.execute("DELETE FROM usuario_roles WHERE usuario_id = ?", (user_id,))
    for rid in role_ids:
        conn.execute(
            "INSERT INTO usuario_roles (usuario_id, role_id) VALUES (?, ?)",
            (user_id, rid),
        )


def _select_usuario(conn, user_id: int) -> dict:
    row = conn.execute(
        """SELECT id, username, nome, email, auth_source, ativo, is_admin,
                  criado_em, atualizado_em
           FROM usuarios WHERE id = ?""",
        (user_id,),
    ).fetchone()
    if not row:
        raise HTTPException(404, f"usuário {user_id} não encontrado")
    roles = [
        r["slug"]
        for r in conn.execute(
            """SELECT r.slug FROM usuario_roles ur JOIN roles r ON r.id = ur.role_id
               WHERE ur.usuario_id = ? ORDER BY r.slug""",
            (user_id,),
        ).fetchall()
    ]
    return {**dict(row), "roles": roles}


@router.get("/usuarios")
def listar_usuarios(_: dict = Depends(require_admin)):
    conn = get_conn()
    try:
        rows = conn.execute(
            """SELECT id, username, nome, email, auth_source, ativo, is_admin,
                      criado_em, atualizado_em
               FROM usuarios ORDER BY username"""
        ).fetchall()
        roles_por_user: dict[int, list[str]] = {}
        for ur in conn.execute(
            """SELECT ur.usuario_id, r.slug
               FROM usuario_roles ur JOIN roles r ON r.id = ur.role_id
               ORDER BY r.slug"""
        ).fetchall():
            roles_por_user.setdefault(ur["usuario_id"], []).append(ur["slug"])
    finally:
        conn.close()
    return [{**dict(r), "roles": roles_por_user.get(r["id"], [])} for r in rows]


@router.post("/usuarios", status_code=201)
def criar_usuario(body: UsuarioCreate, _: dict = Depends(require_admin)):
    if not body.username or not body.username.strip():
        raise HTTPException(400, "username obrigatório")
    if len(body.senha) < PASSWORD_MIN_LEN:
        raise HTTPException(400, f"senha deve ter ao menos {PASSWORD_MIN_LEN} caracteres")
    conn = get_conn()
    try:
        role_ids = _roles_ids_por_slug(conn, body.roles)
        try:
            cur = conn.execute(
                """INSERT INTO usuarios
                   (username, nome, email, password_hash, auth_source, is_admin)
                   VALUES (?, ?, ?, ?, 'local', ?)""",
                (
                    body.username.strip(),
                    body.nome,
                    body.email,
                    hash_password(body.senha),
                    1 if body.is_admin else 0,
                ),
            )
        except sqlite3.IntegrityError as e:
            if "UNIQUE" in str(e):
                raise HTTPException(409, f"username '{body.username}' já existe")
            raise
        user_id = cur.lastrowid
        _set_user_roles(conn, user_id, role_ids)
        conn.commit()
        return _select_usuario(conn, user_id)
    finally:
        conn.close()


@router.patch("/usuarios/{user_id}")
def atualizar_usuario(
    user_id: int,
    body: UsuarioUpdate,
    me: dict = Depends(require_admin),
):
    conn = get_conn()
    try:
        _row_or_404(conn, "usuarios", user_id)
        fields = body.model_dump(exclude_unset=True)
        roles = fields.pop("roles", None)

        # Não permite admin tirar o próprio bit de admin (evita lockout)
        if "is_admin" in fields and user_id == me["id"] and not fields["is_admin"]:
            raise HTTPException(400, "Você não pode remover o próprio acesso de administrador")

        if "is_admin" in fields:
            fields["is_admin"] = 1 if fields["is_admin"] else 0

        if fields:
            fields["__updated"] = None  # marker para o SQL
            sets_parts = []
            values = []
            for k in fields:
                if k == "__updated":
                    sets_parts.append("atualizado_em = datetime('now')")
                else:
                    sets_parts.append(f"{k} = ?")
                    values.append(fields[k])
            conn.execute(f"UPDATE usuarios SET {', '.join(sets_parts)} WHERE id = ?", (*values, user_id))

        if roles is not None:
            role_ids = _roles_ids_por_slug(conn, roles)
            _set_user_roles(conn, user_id, role_ids)

        conn.commit()
        return _select_usuario(conn, user_id)
    finally:
        conn.close()


@router.post("/usuarios/{user_id}/toggle")
def toggle_usuario(user_id: int, me: dict = Depends(require_admin)):
    if user_id == me["id"]:
        raise HTTPException(400, "Você não pode desativar a própria conta")
    conn = get_conn()
    try:
        row = _row_or_404(conn, "usuarios", user_id)
        novo = 0 if row["ativo"] else 1
        conn.execute(
            "UPDATE usuarios SET ativo = ?, atualizado_em = datetime('now') WHERE id = ?",
            (novo, user_id),
        )
        conn.commit()
        return _select_usuario(conn, user_id)
    finally:
        conn.close()


@router.post("/usuarios/{user_id}/password")
def resetar_senha(user_id: int, body: PasswordReset, _: dict = Depends(require_admin)):
    conn = get_conn()
    try:
        _row_or_404(conn, "usuarios", user_id)
        conn.execute(
            """UPDATE usuarios
               SET password_hash = ?,
                   token_version = token_version + 1,
                   atualizado_em = datetime('now')
               WHERE id = ?""",
            (hash_password(body.senha), user_id),
        )
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()
