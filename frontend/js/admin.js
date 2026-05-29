/* Portal SuperFrio — tela administrativa (apps, seções, roles, usuários) */
(() => {
  const SF = window.SF;
  if (!SF) {
    console.error("admin.js carregado antes de app.js");
    return;
  }
  const escapeHtml = SF.escapeHtml;
  const iconSvg = SF.iconSvg;

  const ADM = {
    tab: "apps",
    secoes: [],
    apps: [],
    roles: [],
    usuarios: [],
    editing: null,   // {entity, record} ou null
  };

  /* ---------- HTTP helper ---------- */
  async function api(method, path, body) {
    const opts = {
      method,
      headers: { Authorization: `Bearer ${SF.state.token}` },
    };
    if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    const res = await fetch(path, opts);
    if (!res.ok) {
      let detail = `HTTP ${res.status}`;
      try {
        const j = await res.json();
        if (j && j.detail) detail = j.detail;
      } catch {}
      throw new Error(detail);
    }
    if (res.status === 204) return null;
    return res.json();
  }

  /* ---------- Load all ---------- */
  async function loadAll() {
    const [secoes, apps, roles, usuarios] = await Promise.all([
      api("GET", "/api/admin/secoes"),
      api("GET", "/api/admin/apps"),
      api("GET", "/api/admin/roles"),
      api("GET", "/api/admin/usuarios"),
    ]);
    ADM.secoes = secoes;
    ADM.apps = apps;
    ADM.roles = roles;
    ADM.usuarios = usuarios;
  }

  /* ---------- Open / close ---------- */
  async function openAdmin() {
    document.getElementById("screen-portal").classList.add("hidden");
    document.getElementById("screen-admin").classList.remove("hidden");
    setActiveTab(ADM.tab);
    try {
      await loadAll();
      renderActiveTab();
    } catch (e) {
      alert("Erro ao carregar admin: " + e.message);
    }
  }
  SF.openAdmin = openAdmin;

  function setActiveTab(tab) {
    ADM.tab = tab;
    document.querySelectorAll(".admin-tab").forEach((el) => {
      el.classList.toggle("active", el.dataset.tab === tab);
    });
    document.querySelectorAll(".admin-pane").forEach((el) => {
      el.classList.toggle("hidden", el.id !== `pane-${tab}`);
    });
  }

  function renderActiveTab() {
    if (ADM.tab === "apps") renderApps();
    else if (ADM.tab === "secoes") renderSecoes();
    else if (ADM.tab === "roles") renderRoles();
    else if (ADM.tab === "usuarios") renderUsuarios();
  }

  /* ---------- Render: APPS ---------- */
  function renderApps() {
    const t = document.getElementById("table-apps");
    if (ADM.apps.length === 0) {
      t.innerHTML = `<tbody><tr><td>Nenhum app cadastrado.</td></tr></tbody>`;
      return;
    }
    let html = `<thead><tr>
      <th style="width:42px"></th>
      <th>App</th>
      <th>Seção</th>
      <th>Tipo</th>
      <th>Badge</th>
      <th>Ordem</th>
      <th>Status</th>
      <th style="width:160px;text-align:right">Ações</th>
    </tr></thead><tbody>`;
    ADM.apps.forEach((a) => {
      html += `<tr>
        <td><span class="app-card-icon" style="width:30px;height:30px">${iconSvg(a.icone || "default")}</span></td>
        <td>
          <div class="col-nome">${escapeHtml(a.nome)}</div>
          <div class="col-slug">${escapeHtml(a.slug)}</div>
        </td>
        <td>${escapeHtml(a.secao_nome)}</td>
        <td><span class="pill ${a.tipo_acesso}">${escapeHtml(a.tipo_acesso)}</span></td>
        <td>${a.badge ? `<span class="pill ${a.badge.toLowerCase()}">${escapeHtml(a.badge)}</span>` : '<span class="col-meta">—</span>'}</td>
        <td>${a.ordem}</td>
        <td><span class="pill ${a.ativo ? "on" : "off"}">${a.ativo ? "ativo" : "inativo"}</span></td>
        <td class="actions">
          <button data-act="edit" data-id="${a.id}">Editar</button>
          <button class="danger" data-act="toggle" data-id="${a.id}">${a.ativo ? "Desativar" : "Reativar"}</button>
        </td>
      </tr>`;
    });
    html += `</tbody>`;
    t.innerHTML = html;
    bindRowActions(t, "apps");
  }

  /* ---------- Render: SEÇÕES ---------- */
  function renderSecoes() {
    const t = document.getElementById("table-secoes");
    if (ADM.secoes.length === 0) {
      t.innerHTML = `<tbody><tr><td>Nenhuma seção cadastrada.</td></tr></tbody>`;
      return;
    }
    let html = `<thead><tr>
      <th>Seção</th>
      <th>Ícone</th>
      <th>Apps</th>
      <th>Ordem</th>
      <th>Status</th>
      <th style="width:160px;text-align:right">Ações</th>
    </tr></thead><tbody>`;
    ADM.secoes.forEach((s) => {
      html += `<tr>
        <td>
          <div class="col-nome">${escapeHtml(s.nome)}</div>
          <div class="col-slug">${escapeHtml(s.slug)}</div>
        </td>
        <td><span class="col-meta">${escapeHtml(s.icone || "—")}</span></td>
        <td>${s.apps_count}</td>
        <td>${s.ordem}</td>
        <td><span class="pill ${s.ativo ? "on" : "off"}">${s.ativo ? "ativa" : "inativa"}</span></td>
        <td class="actions">
          <button data-act="edit" data-id="${s.id}">Editar</button>
          <button class="danger" data-act="toggle" data-id="${s.id}">${s.ativo ? "Desativar" : "Reativar"}</button>
        </td>
      </tr>`;
    });
    html += `</tbody>`;
    t.innerHTML = html;
    bindRowActions(t, "secoes");
  }

  /* ---------- Render: ROLES ---------- */
  function renderRoles() {
    const t = document.getElementById("table-roles");
    if (ADM.roles.length === 0) {
      t.innerHTML = `<tbody><tr><td>Nenhuma role cadastrada.</td></tr></tbody>`;
      return;
    }
    let html = `<thead><tr>
      <th>Role</th>
      <th>Apps liberados</th>
      <th>Usuários</th>
      <th>Status</th>
      <th style="width:160px;text-align:right">Ações</th>
    </tr></thead><tbody>`;
    ADM.roles.forEach((r) => {
      const pills = r.apps.map((a) => `<span class="pill url">${escapeHtml(a)}</span>`).join(" ");
      html += `<tr>
        <td>
          <div class="col-nome">${escapeHtml(r.nome)}</div>
          <div class="col-slug">${escapeHtml(r.slug)}</div>
        </td>
        <td><div class="pill-stack">${pills || '<span class="col-meta">— sem apps —</span>'}</div></td>
        <td>${r.usuarios_count}</td>
        <td><span class="pill ${r.ativo ? "on" : "off"}">${r.ativo ? "ativa" : "inativa"}</span></td>
        <td class="actions">
          <button data-act="edit" data-id="${r.id}">Editar</button>
          <button class="danger" data-act="toggle" data-id="${r.id}">${r.ativo ? "Desativar" : "Reativar"}</button>
        </td>
      </tr>`;
    });
    html += `</tbody>`;
    t.innerHTML = html;
    bindRowActions(t, "roles");
  }

  /* ---------- Render: USUÁRIOS ---------- */
  function renderUsuarios() {
    const t = document.getElementById("table-usuarios");
    if (ADM.usuarios.length === 0) {
      t.innerHTML = `<tbody><tr><td>Nenhum usuário cadastrado.</td></tr></tbody>`;
      return;
    }
    let html = `<thead><tr>
      <th>Usuário</th>
      <th>Email</th>
      <th>Roles</th>
      <th>Tipo</th>
      <th>Status</th>
      <th style="width:220px;text-align:right">Ações</th>
    </tr></thead><tbody>`;
    ADM.usuarios.forEach((u) => {
      const pills = u.roles.map((s) => `<span class="pill url">${escapeHtml(s)}</span>`).join(" ");
      const meEu = SF.state.user && SF.state.user.username === u.username;
      html += `<tr>
        <td>
          <div class="col-nome">${escapeHtml(u.nome || u.username)}</div>
          <div class="col-slug">${escapeHtml(u.username)}</div>
        </td>
        <td><span class="col-meta">${escapeHtml(u.email || "—")}</span></td>
        <td><div class="pill-stack">${pills || '<span class="col-meta">—</span>'}</div></td>
        <td>${u.is_admin ? '<span class="pill admin">admin</span>' : '<span class="col-meta">usuário</span>'}</td>
        <td><span class="pill ${u.ativo ? "on" : "off"}">${u.ativo ? "ativo" : "inativo"}</span></td>
        <td class="actions">
          <button data-act="edit" data-id="${u.id}">Editar</button>
          <button data-act="passwd" data-id="${u.id}">Senha</button>
          <button class="danger" data-act="toggle" data-id="${u.id}" ${meEu ? "disabled title='Não pode desativar a si mesmo'" : ""}>${u.ativo ? "Desativar" : "Reativar"}</button>
        </td>
      </tr>`;
    });
    html += `</tbody>`;
    t.innerHTML = html;
    bindRowActions(t, "usuarios");
  }

  /* ---------- Row actions ---------- */
  function bindRowActions(tableEl, entity) {
    tableEl.querySelectorAll("button[data-act]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const id = parseInt(btn.dataset.id, 10);
        const act = btn.dataset.act;
        if (act === "edit") {
          const rec = findRecord(entity, id);
          if (rec) openModal(entity, rec);
        } else if (act === "toggle") {
          try {
            await api("POST", `/api/admin/${entity}/${id}/toggle`);
            await loadAll();
            renderActiveTab();
          } catch (e) {
            alert("Erro: " + e.message);
          }
        } else if (act === "passwd") {
          openPasswordModal(id);
        }
      });
    });
  }

  function findRecord(entity, id) {
    const map = { apps: ADM.apps, secoes: ADM.secoes, roles: ADM.roles, usuarios: ADM.usuarios };
    return (map[entity] || []).find((r) => r.id === id);
  }

  /* ---------- Modal: formulários ---------- */
  function openModal(entity, record) {
    ADM.editing = { entity, record, mode: "form" };
    const isNew = !record;
    const titles = {
      apps: isNew ? "Novo app" : `Editar app — ${record.nome}`,
      secoes: isNew ? "Nova seção" : `Editar seção — ${record.nome}`,
      roles: isNew ? "Nova role" : `Editar role — ${record.nome}`,
      usuarios: isNew ? "Novo usuário" : `Editar usuário — ${record.username}`,
    };
    document.getElementById("modal-title").textContent = titles[entity];
    document.getElementById("modal-form").innerHTML = buildForm(entity, record);
    document.getElementById("modal-error").textContent = "";
    document.getElementById("modal-overlay").classList.add("visible");
    setTimeout(() => {
      const first = document.querySelector("#modal-form input,#modal-form select,#modal-form textarea");
      if (first) first.focus();
    }, 30);
  }

  function openPasswordModal(userId) {
    const u = findRecord("usuarios", userId);
    if (!u) return;
    ADM.editing = { entity: "usuarios", record: u, mode: "password" };
    document.getElementById("modal-title").textContent = `Resetar senha — ${u.username}`;
    document.getElementById("modal-form").innerHTML = `
      <div class="form-field">
        <label>Nova senha</label>
        <input name="senha" type="password" required minlength="8" autocomplete="new-password">
        <div class="field-hint">Mínimo 8 caracteres. O usuário precisa entrar de novo após o reset.</div>
      </div>
    `;
    document.getElementById("modal-error").textContent = "";
    document.getElementById("modal-overlay").classList.add("visible");
  }

  function closeModal() {
    document.getElementById("modal-overlay").classList.remove("visible");
    ADM.editing = null;
  }

  /* ---------- Form builders ---------- */
  function buildForm(entity, r) {
    if (entity === "secoes") return formSecao(r);
    if (entity === "apps") return formApp(r);
    if (entity === "roles") return formRole(r);
    if (entity === "usuarios") return formUsuario(r);
    return "";
  }

  function attr(v) {
    return escapeHtml(v == null ? "" : String(v));
  }

  function formSecao(r) {
    return `
      <div class="row-2">
        <div class="form-field">
          <label>Slug ${r ? "(não editável)" : ""}</label>
          <input name="slug" required value="${attr(r && r.slug)}" ${r ? "disabled" : ""} placeholder="ex: tecnologia">
        </div>
        <div class="form-field">
          <label>Ordem</label>
          <input name="ordem" type="number" value="${attr(r ? r.ordem : 0)}" step="1">
        </div>
      </div>
      <div class="form-field">
        <label>Nome</label>
        <input name="nome" required value="${attr(r && r.nome)}">
      </div>
      <div class="form-field">
        <label>Descrição</label>
        <textarea name="descricao">${attr(r && r.descricao)}</textarea>
      </div>
      <div class="form-field">
        <label>Ícone</label>
        <select name="icone">${iconOptions(r && r.icone)}</select>
        <div class="field-hint">Ícone exibido na sidebar (warehouse, briefcase, etc).</div>
      </div>
    `;
  }

  function formApp(r) {
    const secaoOpts = ADM.secoes
      .map((s) => `<option value="${s.id}" ${r && r.secao_id === s.id ? "selected" : ""}>${escapeHtml(s.nome)}</option>`)
      .join("");
    return `
      <div class="row-2">
        <div class="form-field">
          <label>Slug ${r ? "(não editável)" : ""}</label>
          <input name="slug" required value="${attr(r && r.slug)}" ${r ? "disabled" : ""} placeholder="ex: faq-blueyonder">
        </div>
        <div class="form-field">
          <label>Ordem</label>
          <input name="ordem" type="number" value="${attr(r ? r.ordem : 0)}" step="1">
        </div>
      </div>
      <div class="form-field">
        <label>Nome</label>
        <input name="nome" required value="${attr(r && r.nome)}">
      </div>
      <div class="form-field">
        <label>Descrição</label>
        <textarea name="descricao">${attr(r && r.descricao)}</textarea>
      </div>
      <div class="row-2">
        <div class="form-field">
          <label>Seção</label>
          <select name="secao_id" required>${secaoOpts}</select>
        </div>
        <div class="form-field">
          <label>Ícone</label>
          <select name="icone">${iconOptions(r && r.icone)}</select>
        </div>
      </div>
      <div class="form-field">
        <label>URL</label>
        <input name="url" required value="${attr(r && r.url)}" placeholder="https://...">
      </div>
      <div class="row-2">
        <div class="form-field">
          <label>Tipo de acesso</label>
          <select name="tipo_acesso">
            <option value="url" ${(!r || r.tipo_acesso === "url") ? "selected" : ""}>URL — abre em nova aba</option>
            <option value="iframe" ${r && r.tipo_acesso === "iframe" ? "selected" : ""}>Iframe — embute no portal</option>
          </select>
        </div>
        <div class="form-field">
          <label>Badge</label>
          <select name="badge">
            <option value="" ${!r || !r.badge ? "selected" : ""}>— sem badge —</option>
            <option value="NEW" ${r && r.badge === "NEW" ? "selected" : ""}>NEW</option>
            <option value="BETA" ${r && r.badge === "BETA" ? "selected" : ""}>BETA</option>
          </select>
        </div>
      </div>
    `;
  }

  function formRole(r) {
    const selected = new Set(r ? r.apps : []);
    const appChecks = ADM.apps
      .map(
        (a) => `
        <label class="check-row">
          <input type="checkbox" name="apps" value="${escapeHtml(a.slug)}" ${selected.has(a.slug) ? "checked" : ""}>
          <span>${escapeHtml(a.nome)}</span>
          <span class="meta">${escapeHtml(a.secao_nome)} · ${escapeHtml(a.slug)}</span>
        </label>`
      )
      .join("");
    return `
      <div class="form-field">
        <label>Slug ${r ? "(não editável)" : ""}</label>
        <input name="slug" required value="${attr(r && r.slug)}" ${r ? "disabled" : ""} placeholder="ex: armazem-full">
      </div>
      <div class="form-field">
        <label>Nome</label>
        <input name="nome" required value="${attr(r && r.nome)}">
      </div>
      <div class="form-field">
        <label>Descrição</label>
        <textarea name="descricao">${attr(r && r.descricao)}</textarea>
      </div>
      <fieldset>
        <legend>Apps liberados</legend>
        ${appChecks || '<div class="col-meta">Nenhum app cadastrado ainda.</div>'}
      </fieldset>
    `;
  }

  function formUsuario(r) {
    const selected = new Set(r ? r.roles : []);
    const roleChecks = ADM.roles
      .map(
        (rl) => `
        <label class="check-row">
          <input type="checkbox" name="roles" value="${escapeHtml(rl.slug)}" ${selected.has(rl.slug) ? "checked" : ""}>
          <span>${escapeHtml(rl.nome)}</span>
          <span class="meta">${escapeHtml(rl.slug)} · ${rl.apps.length} app(s)</span>
        </label>`
      )
      .join("");

    const meEu = r && SF.state.user && SF.state.user.username === r.username;
    return `
      <div class="row-2">
        <div class="form-field">
          <label>Username ${r ? "(não editável)" : ""}</label>
          <input name="username" required value="${attr(r && r.username)}" ${r ? "disabled" : ""} placeholder="ex: jose.silva">
        </div>
        <div class="form-field">
          <label>Email</label>
          <input name="email" type="email" value="${attr(r && r.email)}">
        </div>
      </div>
      <div class="form-field">
        <label>Nome completo</label>
        <input name="nome" value="${attr(r && r.nome)}">
      </div>
      ${r ? "" : `
      <div class="form-field">
        <label>Senha inicial</label>
        <input name="senha" type="password" required minlength="8">
        <div class="field-hint">Mínimo 8 caracteres. O usuário pode trocar depois.</div>
      </div>`}
      <div class="form-field">
        <label class="check-row" style="margin:0">
          <input type="checkbox" name="is_admin" ${r && r.is_admin ? "checked" : ""} ${meEu ? "disabled" : ""}>
          <span>É administrador (acessa governança)</span>
          ${meEu ? '<span class="meta">não pode editar o próprio bit</span>' : ""}
        </label>
      </div>
      <fieldset>
        <legend>Roles</legend>
        ${roleChecks || '<div class="col-meta">Nenhuma role cadastrada ainda.</div>'}
      </fieldset>
    `;
  }

  function iconOptions(current) {
    const opts = ["", "warehouse", "briefcase", "book", "scale", "chat", "cart", "document", "truck"];
    return opts
      .map((o) => `<option value="${o}" ${o === (current || "") ? "selected" : ""}>${o || "— nenhum —"}</option>`)
      .join("");
  }

  /* ---------- Submit ---------- */
  async function submitModal() {
    if (!ADM.editing) return;
    const { entity, record, mode } = ADM.editing;
    const form = document.getElementById("modal-form");
    const errEl = document.getElementById("modal-error");
    const saveBtn = document.getElementById("modal-save");
    errEl.textContent = "";
    saveBtn.disabled = true;
    saveBtn.textContent = "Salvando...";

    try {
      if (mode === "password") {
        const senha = form.querySelector("[name='senha']").value;
        if (!senha || senha.length < 8) throw new Error("Senha deve ter ao menos 8 caracteres");
        await api("POST", `/api/admin/usuarios/${record.id}/password`, { senha });
      } else {
        const body = collectForm(entity, form, record);
        if (record) {
          await api("PATCH", `/api/admin/${entity}/${record.id}`, body);
        } else {
          await api("POST", `/api/admin/${entity}`, body);
        }
      }
      closeModal();
      await loadAll();
      renderActiveTab();
    } catch (e) {
      errEl.textContent = e.message || "Falha ao salvar";
    } finally {
      saveBtn.disabled = false;
      saveBtn.textContent = "Salvar";
    }
  }

  function collectForm(entity, form, record) {
    const fd = new FormData(form);
    const isNew = !record;
    const out = {};

    if (entity === "secoes") {
      if (isNew) out.slug = (fd.get("slug") || "").trim();
      out.nome = (fd.get("nome") || "").trim();
      out.descricao = (fd.get("descricao") || "").trim() || null;
      out.icone = (fd.get("icone") || "").trim() || null;
      out.ordem = parseInt(fd.get("ordem") || "0", 10) || 0;
    } else if (entity === "apps") {
      if (isNew) out.slug = (fd.get("slug") || "").trim();
      out.nome = (fd.get("nome") || "").trim();
      out.descricao = (fd.get("descricao") || "").trim() || null;
      out.icone = (fd.get("icone") || "").trim() || null;
      out.secao_id = parseInt(fd.get("secao_id"), 10);
      out.url = (fd.get("url") || "").trim();
      out.tipo_acesso = fd.get("tipo_acesso") || "url";
      out.badge = (fd.get("badge") || "").trim() || null;
      out.ordem = parseInt(fd.get("ordem") || "0", 10) || 0;
    } else if (entity === "roles") {
      if (isNew) out.slug = (fd.get("slug") || "").trim();
      out.nome = (fd.get("nome") || "").trim();
      out.descricao = (fd.get("descricao") || "").trim() || null;
      out.apps = fd.getAll("apps");
    } else if (entity === "usuarios") {
      if (isNew) {
        out.username = (fd.get("username") || "").trim();
        out.senha = fd.get("senha") || "";
      }
      out.nome = (fd.get("nome") || "").trim() || null;
      out.email = (fd.get("email") || "").trim() || null;
      out.is_admin = !!fd.get("is_admin");
      out.roles = fd.getAll("roles");
    }
    return out;
  }

  /* ---------- Bindings ---------- */
  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll(".admin-tab").forEach((el) => {
      el.addEventListener("click", () => {
        setActiveTab(el.dataset.tab);
        renderActiveTab();
      });
    });

    document.getElementById("btn-new-app").addEventListener("click", () => openModal("apps", null));
    document.getElementById("btn-new-secao").addEventListener("click", () => openModal("secoes", null));
    document.getElementById("btn-new-role").addEventListener("click", () => openModal("roles", null));
    document.getElementById("btn-new-usuario").addEventListener("click", () => openModal("usuarios", null));

    document.getElementById("modal-close").addEventListener("click", closeModal);
    document.getElementById("modal-cancel").addEventListener("click", closeModal);
    document.getElementById("modal-overlay").addEventListener("click", (ev) => {
      if (ev.target.id === "modal-overlay") closeModal();
    });
    document.getElementById("modal-save").addEventListener("click", submitModal);
    document.getElementById("modal-form").addEventListener("submit", (ev) => {
      ev.preventDefault();
      submitModal();
    });
    document.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape" && document.getElementById("modal-overlay").classList.contains("visible")) {
        closeModal();
      }
    });
  });
})();
