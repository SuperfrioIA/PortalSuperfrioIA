/* Hub SuperFrio & Icestar — tela administrativa (apps, seções, roles, usuários) */
(() => {
  const SF = window.SF;
  if (!SF) {
    console.error("admin.js carregado antes de app.js");
    return;
  }
  const escapeHtml = SF.escapeHtml;
  const iconSvg = SF.iconSvg;
  const t = (k) => SF.i18n.t(k);

  const PASSWORD_MIN_LEN = 8;

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
    if (res.status === 401) {
      // Sessão expirou enquanto a tela ficou ociosa: volta pro login em vez
      // de travar com um erro críptico de "credenciais inválidas".
      if (SF.logout) SF.logout(t("session.expired"));
      const e = new Error(t("session.expired"));
      e.sessionExpired = true;
      throw e;
    }
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
      if (e.sessionExpired) return;
      alert(t("admin.err.load") + e.message);
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

  /* ---------- Render genérico de tabela ----------
     Monta thead + tbody e religa as ações de linha. Cada aba só descreve
     suas colunas (headers) e como renderiza uma linha (rowHtml). */
  function renderTable(tbl, { entity, emptyMsg, headers, rows, rowHtml }) {
    if (rows.length === 0) {
      tbl.innerHTML = `<tbody><tr><td>${escapeHtml(emptyMsg)}</td></tr></tbody>`;
      return;
    }
    tbl.innerHTML =
      `<thead><tr>${headers.join("")}</tr></thead>` +
      `<tbody>${rows.map(rowHtml).join("")}</tbody>`;
    bindRowActions(tbl, entity);
  }

  const th = (key) => `<th>${escapeHtml(t(key))}</th>`;
  const thRight = (key) => `<th style="width:160px;text-align:right">${escapeHtml(t(key))}</th>`;

  /* ---------- Render: APPS ---------- */
  function renderApps() {
    renderTable(document.getElementById("table-apps"), {
      entity: "apps",
      emptyMsg: t("admin.empty.apps"),
      rows: ADM.apps,
      headers: [
        `<th style="width:42px"></th>`,
        th("admin.col.app"), th("admin.col.secao"), th("admin.col.tipo"),
        th("admin.col.badge"), th("admin.col.ordem"), th("admin.col.status"),
        thRight("admin.col.acoes"),
      ],
      rowHtml: (a) => `<tr>
        <td><span class="app-card-icon" style="width:30px;height:30px">${iconSvg(a.icone || "default")}</span></td>
        <td>
          <div class="col-nome">${escapeHtml(a.nome)}</div>
          <div class="col-slug">${escapeHtml(a.slug)}</div>
        </td>
        <td>${escapeHtml(a.secao_nome)}</td>
        <td><span class="pill ${a.tipo_acesso}">${escapeHtml(a.tipo_acesso)}</span></td>
        <td>${a.badge ? `<span class="pill ${a.badge.toLowerCase()}">${escapeHtml(a.badge)}</span>` : `<span class="col-meta">${escapeHtml(t("admin.dash"))}</span>`}</td>
        <td>${a.ordem}</td>
        <td><span class="pill ${a.ativo ? "on" : "off"}">${escapeHtml(a.ativo ? t("admin.status.active.m") : t("admin.status.inactive.m"))}</span></td>
        <td class="actions">
          <button data-act="edit" data-id="${a.id}">${escapeHtml(t("admin.act.edit"))}</button>
          <button class="danger" data-act="toggle" data-id="${a.id}">${escapeHtml(a.ativo ? t("admin.act.deactivate") : t("admin.act.reactivate"))}</button>
        </td>
      </tr>`,
    });
  }

  /* ---------- Render: SEÇÕES ---------- */
  function renderSecoes() {
    renderTable(document.getElementById("table-secoes"), {
      entity: "secoes",
      emptyMsg: t("admin.empty.secoes"),
      rows: ADM.secoes,
      headers: [
        th("admin.col.secao"), th("admin.col.icone"), th("admin.col.apps"),
        th("admin.col.ordem"), th("admin.col.status"), thRight("admin.col.acoes"),
      ],
      rowHtml: (s) => `<tr>
        <td>
          <div class="col-nome">${escapeHtml(s.nome)}</div>
          <div class="col-slug">${escapeHtml(s.slug)}</div>
        </td>
        <td><span class="col-meta">${escapeHtml(s.icone || t("admin.dash"))}</span></td>
        <td>${s.apps_count}</td>
        <td>${s.ordem}</td>
        <td><span class="pill ${s.ativo ? "on" : "off"}">${escapeHtml(s.ativo ? t("admin.status.active.f") : t("admin.status.inactive.f"))}</span></td>
        <td class="actions">
          <button data-act="edit" data-id="${s.id}">${escapeHtml(t("admin.act.edit"))}</button>
          <button class="danger" data-act="toggle" data-id="${s.id}">${escapeHtml(s.ativo ? t("admin.act.deactivate") : t("admin.act.reactivate"))}</button>
        </td>
      </tr>`,
    });
  }

  /* ---------- Render: ROLES ---------- */
  function renderRoles() {
    renderTable(document.getElementById("table-roles"), {
      entity: "roles",
      emptyMsg: t("admin.empty.roles"),
      rows: ADM.roles,
      headers: [
        th("admin.col.role"), th("admin.col.appsLiberados"), th("admin.col.usuarios"),
        th("admin.col.status"), thRight("admin.col.acoes"),
      ],
      rowHtml: (r) => {
        const pills = r.apps.map((a) => `<span class="pill url">${escapeHtml(a)}</span>`).join(" ");
        return `<tr>
        <td>
          <div class="col-nome">${escapeHtml(r.nome)}</div>
          <div class="col-slug">${escapeHtml(r.slug)}</div>
        </td>
        <td><div class="pill-stack">${pills || `<span class="col-meta">${escapeHtml(t("admin.noApps"))}</span>`}</div></td>
        <td>${r.usuarios_count}</td>
        <td><span class="pill ${r.ativo ? "on" : "off"}">${escapeHtml(r.ativo ? t("admin.status.active.f") : t("admin.status.inactive.f"))}</span></td>
        <td class="actions">
          <button data-act="edit" data-id="${r.id}">${escapeHtml(t("admin.act.edit"))}</button>
          <button class="danger" data-act="toggle" data-id="${r.id}">${escapeHtml(r.ativo ? t("admin.act.deactivate") : t("admin.act.reactivate"))}</button>
        </td>
      </tr>`;
      },
    });
  }

  /* ---------- Render: USUÁRIOS ---------- */
  function renderUsuarios() {
    renderTable(document.getElementById("table-usuarios"), {
      entity: "usuarios",
      emptyMsg: t("admin.empty.usuarios"),
      rows: ADM.usuarios,
      headers: [
        th("admin.col.usuario"), th("admin.col.email"), th("admin.col.roles"),
        th("admin.col.tipo"), th("admin.col.status"),
        `<th style="width:220px;text-align:right">${escapeHtml(t("admin.col.acoes"))}</th>`,
      ],
      rowHtml: (u) => {
        const pills = u.roles.map((s) => `<span class="pill url">${escapeHtml(s)}</span>`).join(" ");
        const meEu = SF.state.user && SF.state.user.username === u.username;
        return `<tr>
        <td>
          <div class="col-nome">${escapeHtml(u.nome || u.username)}</div>
          <div class="col-slug">${escapeHtml(u.username)}</div>
        </td>
        <td><span class="col-meta">${escapeHtml(u.email || t("admin.dash"))}</span></td>
        <td><div class="pill-stack">${pills || `<span class="col-meta">${escapeHtml(t("admin.dash"))}</span>`}</div></td>
        <td>${u.is_admin ? `<span class="pill admin">${escapeHtml(t("admin.type.admin"))}</span>` : `<span class="col-meta">${escapeHtml(t("admin.type.user"))}</span>`}</td>
        <td><span class="pill ${u.ativo ? "on" : "off"}">${escapeHtml(u.ativo ? t("admin.status.active.m") : t("admin.status.inactive.m"))}</span></td>
        <td class="actions">
          <button data-act="edit" data-id="${u.id}">${escapeHtml(t("admin.act.edit"))}</button>
          <button data-act="passwd" data-id="${u.id}">${escapeHtml(t("admin.act.password"))}</button>
          <button class="danger" data-act="toggle" data-id="${u.id}" ${meEu ? `disabled title="${escapeHtml(t("admin.cantDeactivateSelf"))}"` : ""}>${escapeHtml(u.ativo ? t("admin.act.deactivate") : t("admin.act.reactivate"))}</button>
        </td>
      </tr>`;
      },
    });
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
            if (e.sessionExpired) return;
            alert(t("admin.err.generic") + e.message);
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
      apps: isNew ? t("admin.new.app") : `${t("admin.edit.app")} — ${record.nome}`,
      secoes: isNew ? t("admin.new.secao") : `${t("admin.edit.secao")} — ${record.nome}`,
      roles: isNew ? t("admin.new.role") : `${t("admin.edit.role")} — ${record.nome}`,
      usuarios: isNew ? t("admin.new.usuario") : `${t("admin.edit.usuario")} — ${record.username}`,
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
    document.getElementById("modal-title").textContent = `${t("admin.pwd.title")} — ${u.username}`;
    document.getElementById("modal-form").innerHTML = `
      <div class="form-field">
        <label>${escapeHtml(t("admin.pwd.newPass"))}</label>
        <input name="senha" type="password" required minlength="${PASSWORD_MIN_LEN}" autocomplete="new-password">
        <div class="field-hint">${escapeHtml(t("admin.pwd.hint"))}</div>
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
          <label>${escapeHtml(t("admin.f.slug"))} ${r ? escapeHtml(t("admin.f.slugLocked")) : ""}</label>
          <input name="slug" required value="${attr(r && r.slug)}" ${r ? "disabled" : ""} placeholder="ex: tecnologia">
        </div>
        <div class="form-field">
          <label>${escapeHtml(t("admin.f.ordem"))}</label>
          <input name="ordem" type="number" value="${attr(r ? r.ordem : 0)}" step="1">
        </div>
      </div>
      <div class="row-2">
        <div class="form-field">
          <label>${escapeHtml(t("admin.f.nomePt"))}</label>
          <input name="nome" required value="${attr(r && r.nome)}">
        </div>
        <div class="form-field">
          <label>${escapeHtml(t("admin.f.nomeEs"))}</label>
          <input name="nome_es" value="${attr(r && r.nome_es)}">
        </div>
      </div>
      <div class="form-field">
        <label>${escapeHtml(t("admin.f.descricaoPt"))}</label>
        <textarea name="descricao">${attr(r && r.descricao)}</textarea>
      </div>
      <div class="form-field">
        <label>${escapeHtml(t("admin.f.descricaoEs"))}</label>
        <textarea name="descricao_es">${attr(r && r.descricao_es)}</textarea>
        <div class="field-hint">${escapeHtml(t("admin.f.nomeEsHint"))}</div>
      </div>
      <div class="form-field">
        <label>${escapeHtml(t("admin.f.icone"))}</label>
        <select name="icone">${iconOptions(r && r.icone)}</select>
        <div class="field-hint">${escapeHtml(t("admin.f.iconeHint"))}</div>
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
          <label>${escapeHtml(t("admin.f.slug"))} ${r ? escapeHtml(t("admin.f.slugLocked")) : ""}</label>
          <input name="slug" required value="${attr(r && r.slug)}" ${r ? "disabled" : ""} placeholder="ex: faq-blueyonder">
        </div>
        <div class="form-field">
          <label>${escapeHtml(t("admin.f.ordem"))}</label>
          <input name="ordem" type="number" value="${attr(r ? r.ordem : 0)}" step="1">
        </div>
      </div>
      <div class="row-2">
        <div class="form-field">
          <label>${escapeHtml(t("admin.f.nomePt"))}</label>
          <input name="nome" required value="${attr(r && r.nome)}">
        </div>
        <div class="form-field">
          <label>${escapeHtml(t("admin.f.nomeEs"))}</label>
          <input name="nome_es" value="${attr(r && r.nome_es)}">
        </div>
      </div>
      <div class="form-field">
        <label>${escapeHtml(t("admin.f.descricaoPt"))}</label>
        <textarea name="descricao">${attr(r && r.descricao)}</textarea>
      </div>
      <div class="form-field">
        <label>${escapeHtml(t("admin.f.descricaoEs"))}</label>
        <textarea name="descricao_es">${attr(r && r.descricao_es)}</textarea>
        <div class="field-hint">${escapeHtml(t("admin.f.nomeEsHint"))}</div>
      </div>
      <div class="row-2">
        <div class="form-field">
          <label>${escapeHtml(t("admin.f.secao"))}</label>
          <select name="secao_id" required>${secaoOpts}</select>
        </div>
        <div class="form-field">
          <label>${escapeHtml(t("admin.f.icone"))}</label>
          <select name="icone">${iconOptions(r && r.icone)}</select>
        </div>
      </div>
      <div class="form-field">
        <label>${escapeHtml(t("admin.f.url"))}</label>
        <input name="url" required value="${attr(r && r.url)}" placeholder="https://...">
      </div>
      <div class="row-2">
        <div class="form-field">
          <label>${escapeHtml(t("admin.f.tipoAcesso"))}</label>
          <select name="tipo_acesso">
            <option value="url" ${(!r || r.tipo_acesso === "url") ? "selected" : ""}>${escapeHtml(t("admin.f.tipoUrl"))}</option>
            <option value="iframe" ${r && r.tipo_acesso === "iframe" ? "selected" : ""}>${escapeHtml(t("admin.f.tipoIframe"))}</option>
          </select>
        </div>
        <div class="form-field">
          <label>${escapeHtml(t("admin.f.badge"))}</label>
          <select name="badge">
            <option value="" ${!r || !r.badge ? "selected" : ""}>${escapeHtml(t("admin.f.noBadge"))}</option>
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
        <label>${escapeHtml(t("admin.f.slug"))} ${r ? escapeHtml(t("admin.f.slugLocked")) : ""}</label>
        <input name="slug" required value="${attr(r && r.slug)}" ${r ? "disabled" : ""} placeholder="ex: armazem-full">
      </div>
      <div class="form-field">
        <label>${escapeHtml(t("admin.f.nome"))}</label>
        <input name="nome" required value="${attr(r && r.nome)}">
      </div>
      <div class="form-field">
        <label>${escapeHtml(t("admin.f.descricao"))}</label>
        <textarea name="descricao">${attr(r && r.descricao)}</textarea>
      </div>
      <fieldset>
        <legend>${escapeHtml(t("admin.f.appsLiberados"))}</legend>
        ${appChecks || `<div class="col-meta">${escapeHtml(t("admin.f.noAppsYet"))}</div>`}
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
          <label>${escapeHtml(t("admin.f.username"))} ${r ? escapeHtml(t("admin.f.slugLocked")) : ""}</label>
          <input name="username" required value="${attr(r && r.username)}" ${r ? "disabled" : ""} placeholder="ex: jose.silva">
        </div>
        <div class="form-field">
          <label>${escapeHtml(t("admin.f.email"))}</label>
          <input name="email" type="email" value="${attr(r && r.email)}">
        </div>
      </div>
      <div class="form-field">
        <label>${escapeHtml(t("admin.f.nomeCompleto"))}</label>
        <input name="nome" value="${attr(r && r.nome)}">
      </div>
      ${r ? "" : `
      <div class="form-field">
        <label>${escapeHtml(t("admin.f.senhaInicial"))}</label>
        <input name="senha" type="password" required minlength="${PASSWORD_MIN_LEN}">
        <div class="field-hint">${escapeHtml(t("admin.f.senhaHint"))}</div>
      </div>`}
      <div class="form-field">
        <label class="check-row" style="margin:0">
          <input type="checkbox" name="is_admin" ${r && r.is_admin ? "checked" : ""} ${meEu ? "disabled" : ""}>
          <span>${escapeHtml(t("admin.f.isAdmin"))}</span>
          ${meEu ? `<span class="meta">${escapeHtml(t("admin.f.cantEditOwnBit"))}</span>` : ""}
        </label>
      </div>
      <fieldset>
        <legend>${escapeHtml(t("admin.f.roles"))}</legend>
        ${roleChecks || `<div class="col-meta">${escapeHtml(t("admin.f.noRolesYet"))}</div>`}
      </fieldset>
    `;
  }

  function iconOptions(current) {
    const opts = ["", "warehouse", "briefcase", "book", "scale", "chat", "cart", "document", "truck"];
    return opts
      .map((o) => `<option value="${o}" ${o === (current || "") ? "selected" : ""}>${o || t("admin.f.none")}</option>`)
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
    saveBtn.textContent = t("admin.modal.saving");

    try {
      if (mode === "password") {
        const senha = form.querySelector("[name='senha']").value;
        if (!senha || senha.length < PASSWORD_MIN_LEN) throw new Error(t("admin.pwd.tooShort"));
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
      if (e.sessionExpired) return;
      errEl.textContent = e.message || t("admin.save.fail");
    } finally {
      saveBtn.disabled = false;
      saveBtn.textContent = t("admin.modal.save");
    }
  }

  function collectForm(entity, form, record) {
    const fd = new FormData(form);
    const isNew = !record;
    const out = {};

    if (entity === "secoes") {
      if (isNew) out.slug = (fd.get("slug") || "").trim();
      out.nome = (fd.get("nome") || "").trim();
      out.nome_es = (fd.get("nome_es") || "").trim() || null;
      out.descricao = (fd.get("descricao") || "").trim() || null;
      out.descricao_es = (fd.get("descricao_es") || "").trim() || null;
      out.icone = (fd.get("icone") || "").trim() || null;
      out.ordem = parseInt(fd.get("ordem") || "0", 10) || 0;
    } else if (entity === "apps") {
      if (isNew) out.slug = (fd.get("slug") || "").trim();
      out.nome = (fd.get("nome") || "").trim();
      out.nome_es = (fd.get("nome_es") || "").trim() || null;
      out.descricao = (fd.get("descricao") || "").trim() || null;
      out.descricao_es = (fd.get("descricao_es") || "").trim() || null;
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

    /* Troca de idioma: re-renderiza a tabela ativa se a tela admin estiver aberta */
    window.addEventListener("sf:langchange", () => {
      const adminVisible = !document.getElementById("screen-admin").classList.contains("hidden");
      if (adminVisible) renderActiveTab();
    });
  });
})();
