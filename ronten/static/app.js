/* 論点ノート フロントエンド（依存ライブラリなし） */
(function () {
  "use strict";

  const app = document.getElementById("app");
  let META = null;
  let CLIENTS = null;

  // ------------------------------------------------------------ utilities
  function esc(s) {
    if (s === null || s === undefined) return "";
    return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }
  function fmtDate(iso) {
    if (!iso) return "";
    return iso.replace("T", " ").slice(0, 16).replace(/-/g, "/");
  }
  function fmtDay(iso) {
    if (!iso) return "";
    return iso.slice(0, 10).replace(/-/g, "/");
  }
  function snippetHtml(s) {
    return esc(s).replace(/\[\[/g, "<mark>").replace(/\]\]/g, "</mark>");
  }
  function trunc(s, n) {
    s = (s || "").replace(/\s+/g, " ").trim();
    return s.length > n ? s.slice(0, n) + "…" : s;
  }
  function badgeStatus(st) { return `<span class="badge st-${esc(st)}">${esc(st)}</span>`; }
  function badgeTax(t) { return t ? `<span class="badge tax">${esc(t)}</span>` : ""; }
  function tagsHtml(tags) {
    return (tags || []).map((t) => `<a class="tag" href="#/?tag=${encodeURIComponent(t)}">${esc(t)}</a>`).join("");
  }
  function qs(obj) {
    const parts = [];
    for (const k of Object.keys(obj)) {
      const v = obj[k];
      if (v === undefined || v === null || v === "" || v === false) continue;
      parts.push(encodeURIComponent(k) + "=" + encodeURIComponent(v));
    }
    return parts.length ? "?" + parts.join("&") : "";
  }
  function toast(msg, isError) {
    const el = document.getElementById("toast");
    el.textContent = msg;
    el.className = "toast" + (isError ? " error" : "");
    el.hidden = false;
    clearTimeout(toast._t);
    toast._t = setTimeout(() => { el.hidden = true; }, isError ? 5000 : 2500);
  }
  async function api(method, path, body) {
    const opt = { method, headers: {} };
    if (body !== undefined) {
      opt.headers["Content-Type"] = "application/json";
      opt.body = JSON.stringify(body);
    }
    const res = await fetch(path, opt);
    let data = null;
    try { data = await res.json(); } catch (e) { data = null; }
    if (!res.ok) throw new Error((data && data.error) || `HTTP ${res.status}`);
    return data;
  }
  async function loadMeta(force) {
    if (!META || force) META = await api("GET", "/api/meta");
    return META;
  }
  async function loadClients(force) {
    if (!CLIENTS || force) CLIENTS = (await api("GET", "/api/clients")).items;
    return CLIENTS;
  }
  function invalidate() { META = null; CLIENTS = null; }
  function options(list, selected, placeholder) {
    let h = placeholder !== undefined ? `<option value="">${esc(placeholder)}</option>` : "";
    for (const v of list) {
      const val = typeof v === "object" ? v.value : v;
      const label = typeof v === "object" ? v.label : v;
      h += `<option value="${esc(val)}"${String(val) === String(selected) ? " selected" : ""}>${esc(label)}</option>`;
    }
    return h;
  }
  function datalist(id, list) {
    return `<datalist id="${id}">${list.map((v) => `<option value="${esc(v)}"></option>`).join("")}</datalist>`;
  }
  function formData(form) {
    const out = {};
    for (const el of form.elements) {
      if (!el.name) continue;
      if (el.type === "checkbox") out[el.name] = el.checked;
      else out[el.name] = el.value;
    }
    return out;
  }
  function setNav(name) {
    document.querySelectorAll("[data-nav]").forEach((a) => a.classList.toggle("active", a.dataset.nav === name));
  }

  // ------------------------------------------------------------ router
  function parseHash() {
    const h = location.hash.replace(/^#/, "") || "/";
    const [path, query] = h.split("?");
    const params = {};
    if (query) {
      for (const kv of query.split("&")) {
        const [k, v] = kv.split("=");
        params[decodeURIComponent(k)] = decodeURIComponent((v || "").replace(/\+/g, " "));
      }
    }
    return { path, params };
  }
  const routes = [
    [/^\/$/, viewHome],
    [/^\/clients$/, viewClients],
    [/^\/clients\/new$/, viewClientForm],
    [/^\/clients\/(\d+)$/, viewClient],
    [/^\/clients\/(\d+)\/edit$/, viewClientForm],
    [/^\/issues\/new$/, viewIssueForm],
    [/^\/issues\/(\d+)$/, viewIssue],
    [/^\/issues\/(\d+)\/edit$/, viewIssueForm],
    [/^\/issues\/(\d+)\/copy$/, viewIssueForm],
    [/^\/settings$/, viewSettings],
  ];
  async function render() {
    const { path, params } = parseHash();
    for (const [rx, fn] of routes) {
      const m = path.match(rx);
      if (m) {
        try {
          await fn(params, ...m.slice(1));
        } catch (e) {
          app.innerHTML = `<div class="panel"><p class="muted">エラー: ${esc(e.message)}</p><p><a href="#/">検索へ戻る</a></p></div>`;
        }
        window.scrollTo(0, 0);
        return;
      }
    }
    app.innerHTML = `<div class="empty">ページが見つかりません。<a href="#/">検索へ戻る</a></div>`;
  }
  window.addEventListener("hashchange", render);

  // ------------------------------------------------------------ issue list rendering
  function issueItem(it, opts) {
    opts = opts || {};
    let body = "";
    if (it.snippet) body = `<div class="snippet">${snippetHtml(it.snippet)}</div>`;
    else if (it.conclusion) body = `<div class="snippet conclusion">${esc(trunc(it.conclusion, 140))}</div>`;
    else if (it.question) body = `<div class="snippet">${esc(trunc(it.question, 140))}</div>`;
    const follow = it.followup ? `<div class="snippet small" style="color:#8a5a00">留意: ${esc(trunc(it.followup, 100))}</div>` : "";
    return `<li class="issue-item">
      <div class="row between">
        <a class="title" href="#/issues/${it.id}">${esc(it.title)}</a>
        <span class="nowrap">${badgeTax(it.tax_type)} ${badgeStatus(it.status)}</span>
      </div>
      <div class="meta">
        ${opts.hideClient ? "" : `<a href="#/clients/${it.client_id}">${esc(it.client_name)}</a>`}
        ${it.fiscal_year ? `<span>${esc(it.fiscal_year)}</span>` : ""}
        ${it.staff ? `<span>担当: ${esc(it.staff)}</span>` : ""}
        <span>更新 ${fmtDate(it.updated_at)}</span>
        <span>${tagsHtml(it.tags)}</span>
      </div>
      ${body}${follow}
    </li>`;
  }
  function issueList(items, opts) {
    if (!items.length) return `<div class="empty">該当する論点はありません。</div>`;
    return `<ul class="issue-list">${items.map((it) => issueItem(it, opts)).join("")}</ul>`;
  }

  // ------------------------------------------------------------ views: home / search
  async function viewHome(params) {
    setNav("home");
    const [meta, clients] = await Promise.all([loadMeta(true), loadClients(true)]);
    const f = {
      q: params.q || "", client_id: params.client_id || "", tax_type: params.tax_type || "", status: params.status || "",
      fiscal_year: params.fiscal_year || "", tag: params.tag || "", staff: params.staff || "", open: params.open || "",
    };
    app.innerHTML = `
      <div class="stats no-print">
        <div class="stat"><div class="num">${meta.counts.clients}</div><div class="lbl">顧問先</div></div>
        <div class="stat"><div class="num">${meta.counts.issues}</div><div class="lbl">論点</div></div>
        <a class="stat" href="#/?open=1"><div class="num">${meta.counts.open}</div><div class="lbl">検討中・要再検討</div></a>
      </div>
      <form id="searchForm" class="panel" style="margin-top:16px">
        <div class="searchbar">
          <input type="search" name="q" placeholder="キーワードで検索（例: インボイス 経過措置、役員退職金、100%グループ）" value="${esc(f.q)}" autofocus>
          <button class="btn primary" type="submit">検索</button>
        </div>
        <div class="filters">
          <select name="client_id">${options(clients.map((c) => ({ value: c.id, label: c.name })), f.client_id, "顧問先: すべて")}</select>
          <select name="tax_type">${options(meta.tax_types, f.tax_type, "税目: すべて")}</select>
          <select name="status">${options(meta.statuses, f.status, "ステータス: すべて")}</select>
          <select name="fiscal_year">${options(meta.fiscal_years, f.fiscal_year, "事業年度: すべて")}</select>
          <select name="tag">${options(meta.tags.map((t) => ({ value: t.name, label: `${t.name} (${t.count})` })), f.tag, "タグ: すべて")}</select>
          <select name="staff">${options(meta.staff, f.staff, "担当者: すべて")}</select>
          <label class="row small" style="font-weight:normal;color:var(--text)"><input type="checkbox" name="open" ${f.open ? "checked" : ""} style="width:auto"> 要フォローのみ</label>
          <button class="btn small" type="button" id="clearBtn">条件クリア</button>
        </div>
        ${meta.fts ? "" : `<p class="small muted">※ この環境では全文検索(FTS5)が使えないため、簡易検索(部分一致)で動作しています。</p>`}
      </form>
      <div id="results"><div class="empty">検索中…</div></div>`;

    const form = document.getElementById("searchForm");
    const results = document.getElementById("results");
    let timer = null;
    function currentFilters() {
      const d = formData(form);
      d.open = d.open ? "1" : "";
      return d;
    }
    async function run(pushHash) {
      const d = currentFilters();
      if (pushHash) {
        const newHash = "#/" + qs(d);
        if (location.hash !== newHash) history.replaceState(null, "", newHash);
      }
      const data = await api("GET", "/api/issues" + qs(Object.assign({ limit: 200 }, d)));
      const any = Object.values(d).some((v) => v);
      const head = any
        ? `<p class="muted small">${data.total} 件${data.total > data.items.length ? `（先頭 ${data.items.length} 件を表示）` : ""}${data.fts ? "・関連度順" : "・更新日順"}</p>`
        : `<p class="muted small">最近更新した論点（${data.items.length} 件）</p>`;
      results.innerHTML = head + issueList(data.items);
    }
    form.addEventListener("submit", (e) => { e.preventDefault(); run(true); });
    form.addEventListener("input", (e) => {
      clearTimeout(timer);
      timer = setTimeout(() => run(true), e.target.name === "q" ? 300 : 0);
    });
    document.getElementById("clearBtn").addEventListener("click", () => { location.hash = "#/"; });
    run(false);
  }

  // ------------------------------------------------------------ views: clients
  async function viewClients(params) {
    setNav("clients");
    const clients = await loadClients(true);
    const q = params.q || "";
    app.innerHTML = `
      <div class="row between">
        <h1>顧問先</h1>
        <a class="btn primary" href="#/clients/new">＋ 顧問先を登録</a>
      </div>
      <div class="panel"><input type="search" id="clientQ" placeholder="名称・かな・コード・担当者で絞り込み" value="${esc(q)}"></div>
      <div id="clientTable"></div>`;
    function draw() {
      const kw = document.getElementById("clientQ").value.trim().toLowerCase();
      const items = clients.filter((c) => !kw || [c.name, c.kana, c.code, c.industry, c.staff].some((v) => (v || "").toLowerCase().includes(kw)));
      const el = document.getElementById("clientTable");
      if (!items.length) { el.innerHTML = `<div class="empty">顧問先が登録されていません。<a href="#/clients/new">最初の顧問先を登録する</a></div>`; return; }
      el.innerHTML = `<table><thead><tr><th>コード</th><th>顧問先</th><th>区分</th><th>決算月</th><th>担当</th><th class="right">論点数</th><th class="right">要フォロー</th><th>最終更新</th></tr></thead><tbody>${items.map((c) => `
        <tr class="clickable" data-href="#/clients/${c.id}">
          <td class="muted">${esc(c.code)}</td>
          <td><a href="#/clients/${c.id}">${esc(c.name)}</a><div class="small muted">${esc(c.kana)}</div></td>
          <td>${esc(c.entity_type)}</td><td>${c.fiscal_month ? c.fiscal_month + "月" : ""}</td><td>${esc(c.staff)}</td>
          <td class="right">${c.issue_count}</td>
          <td class="right">${c.open_count ? `<span class="badge st-検討中">${c.open_count}</span>` : ""}</td>
          <td class="small muted">${fmtDate(c.last_issue_at)}</td>
        </tr>`).join("")}</tbody></table>`;
      el.querySelectorAll("tr.clickable").forEach((tr) => tr.addEventListener("click", (e) => { if (e.target.tagName !== "A") location.hash = tr.dataset.href; }));
    }
    document.getElementById("clientQ").addEventListener("input", draw);
    draw();
  }

  async function viewClientForm(params, id) {
    setNav("clients");
    const meta = await loadMeta();
    const c = id ? await api("GET", `/api/clients/${id}`) : { entity_type: "法人" };
    app.innerHTML = `
      <h1>${id ? "顧問先を編集" : "顧問先を登録"}</h1>
      <form id="f" class="panel">
        <div class="grid2">
          <div class="field"><label class="required">名称</label><input type="text" name="name" value="${esc(c.name)}" required autofocus></div>
          <div class="field"><label>かな（並び順用）</label><input type="text" name="kana" value="${esc(c.kana)}"></div>
          <div class="field"><label>顧問先コード</label><input type="text" name="code" value="${esc(c.code)}"></div>
          <div class="field"><label>区分</label><select name="entity_type">${options(meta.entity_types, c.entity_type)}</select></div>
          <div class="field"><label>決算月</label><select name="fiscal_month">${options([1,2,3,4,5,6,7,8,9,10,11,12].map((m) => ({ value: m, label: m + "月" })), c.fiscal_month, "未設定")}</select></div>
          <div class="field"><label>業種</label><input type="text" name="industry" value="${esc(c.industry)}"></div>
          <div class="field"><label>担当者</label><input type="text" name="staff" value="${esc(c.staff)}" list="staffList">${datalist("staffList", meta.staff)}</div>
        </div>
        <div class="field"><label>メモ（会社概要・関係会社・留意事項など）</label><textarea name="note">${esc(c.note)}</textarea></div>
        <div class="form-actions">
          <button class="btn primary" type="submit">保存</button>
          <a class="btn" href="${id ? `#/clients/${id}` : "#/clients"}">キャンセル</a>
        </div>
      </form>`;
    document.getElementById("f").addEventListener("submit", async (e) => {
      e.preventDefault();
      try {
        const d = formData(e.target);
        const saved = id ? await api("PUT", `/api/clients/${id}`, d) : await api("POST", "/api/clients", d);
        invalidate();
        toast("保存しました");
        location.hash = `#/clients/${saved.id}`;
      } catch (err) { toast(err.message, true); }
    });
  }

  async function viewClient(params, id) {
    setNav("clients");
    const [c, data] = await Promise.all([api("GET", `/api/clients/${id}`), api("GET", `/api/clients/${id}/issues`)]);
    const items = data.items;
    const open = items.filter((it) => it.status === "検討中" || it.status === "要再検討" || it.followup);
    const groups = {};
    for (const it of items) (groups[it.fiscal_year || ""] = groups[it.fiscal_year || ""] || []).push(it);
    const years = Object.keys(groups).sort((a, b) => (a === "" ? 1 : b === "" ? -1 : b.localeCompare(a, "ja")));
    app.innerHTML = `
      <p class="small no-print"><a href="#/clients">顧問先</a> › ${esc(c.name)}</p>
      <div class="row between">
        <h1>${esc(c.name)} <span class="muted small" style="font-weight:normal">${esc(c.code)}</span></h1>
        <span class="no-print">
          <a class="btn primary" href="#/issues/new?client=${c.id}">＋ この顧問先の論点を記録</a>
          <a class="btn" href="#/clients/${c.id}/edit">編集</a>
          <button class="btn danger" id="delClient">削除</button>
        </span>
      </div>
      <div class="panel">
        <dl class="kv">
          <dt>区分</dt><dd>${esc(c.entity_type)}${c.fiscal_month ? ` ／ ${c.fiscal_month}月決算` : ""}</dd>
          <dt>業種</dt><dd>${esc(c.industry) || "<span class='muted'>—</span>"}</dd>
          <dt>担当者</dt><dd>${esc(c.staff) || "<span class='muted'>—</span>"}</dd>
          <dt>メモ</dt><dd class="pre">${esc(c.note) || "<span class='muted'>—</span>"}</dd>
        </dl>
      </div>
      ${open.length ? `<div class="section"><div class="section-title"><h2>要フォロー（検討中・要再検討・翌年以降の留意点あり）</h2><span class="muted small">${open.length} 件</span></div>${issueList(open, { hideClient: true })}</div>` : ""}
      <div class="section">
        <div class="section-title"><h2>全論点</h2><span class="muted small">${items.length} 件</span></div>
        <div class="panel no-print"><input type="search" id="issueQ" placeholder="この顧問先の論点内を検索"></div>
        <div id="clientIssues">${years.map((y) => `<div class="year-group"><h3>${esc(y) || "事業年度未設定"}</h3>${issueList(groups[y], { hideClient: true })}</div>`).join("") || `<div class="empty">まだ論点がありません。</div>`}</div>
      </div>`;
    let timer = null;
    document.getElementById("issueQ").addEventListener("input", (e) => {
      clearTimeout(timer);
      timer = setTimeout(async () => {
        const q = e.target.value.trim();
        const el = document.getElementById("clientIssues");
        if (!q) { render(); return; }
        const r = await api("GET", `/api/clients/${id}/issues${qs({ q })}`);
        el.innerHTML = `<p class="muted small">${r.total} 件</p>` + issueList(r.items, { hideClient: true });
      }, 300);
    });
    document.getElementById("delClient").addEventListener("click", async () => {
      if (!confirm(`顧問先「${c.name}」と、その論点 ${items.length} 件をすべて削除します。元に戻せません。よろしいですか？`)) return;
      try { await api("DELETE", `/api/clients/${id}`); invalidate(); toast("削除しました"); location.hash = "#/clients"; }
      catch (err) { toast(err.message, true); }
    });
  }

  // ------------------------------------------------------------ views: issue
  function docBlock(label, text, cls) {
    return `<div class="doc-block ${cls || ""}"><h3>${esc(label)}</h3><div class="body pre${text ? "" : " none"}">${esc(text) || "（未記入）"}</div></div>`;
  }
  const FIELD_LABELS = {
    title: "論点名", tax_type: "税目", fiscal_year: "事業年度", status: "ステータス", staff: "担当者", reviewer: "確認者",
    decided_on: "結論日", facts: "事実関係・前提", question: "論点", analysis: "検討内容", conclusion: "結論", basis: "根拠",
    followup: "翌年以降の留意点", tags: "タグ", client_name: "顧問先",
  };

  async function viewIssue(params, id) {
    setNav(null);
    const it = await api("GET", `/api/issues/${id}`);
    app.innerHTML = `
      <p class="small no-print"><a href="#/clients">顧問先</a> › <a href="#/clients/${it.client_id}">${esc(it.client_name)}</a> › 論点</p>
      <div class="row between">
        <h1>${esc(it.title)}</h1>
        <span class="no-print nowrap">
          <a class="btn primary" href="#/issues/${it.id}/edit">編集</a>
          <a class="btn" href="#/issues/${it.id}/copy" title="事実関係・結論を引き継いで、別の事業年度の論点として記録します">翌年分として複製</a>
          <button class="btn" onclick="window.print()">印刷</button>
          <button class="btn danger" id="delIssue">削除</button>
        </span>
      </div>
      <div class="panel">
        <div class="row" style="margin-bottom:8px">
          <a href="#/clients/${it.client_id}"><strong>${esc(it.client_name)}</strong></a>
          ${badgeTax(it.tax_type)} ${badgeStatus(it.status)}
          ${it.fiscal_year ? `<span class="badge">${esc(it.fiscal_year)}</span>` : ""}
          <span>${tagsHtml(it.tags)}</span>
        </div>
        <dl class="kv small">
          <dt>担当者</dt><dd>${esc(it.staff) || "—"}</dd>
          <dt>確認者</dt><dd>${esc(it.reviewer) || "—"}</dd>
          <dt>結論日</dt><dd>${fmtDay(it.decided_on) || "—"}</dd>
          <dt>作成／更新</dt><dd>${fmtDate(it.created_at)} ／ ${fmtDate(it.updated_at)}</dd>
        </dl>
      </div>
      <div class="panel">
        ${docBlock("事実関係・前提", it.facts)}
        ${docBlock("論点（何が問題か）", it.question)}
        ${docBlock("検討内容", it.analysis)}
        ${docBlock("結論", it.conclusion, "conclusion")}
        ${docBlock("根拠（条文・通達・判例・質疑応答事例など）", it.basis)}
        ${docBlock("翌年以降の留意点", it.followup, "followup")}
      </div>
      <div class="section no-print">
        <div class="section-title"><h2>類似論点（他の顧問先を含む）</h2></div>
        <div id="similar"><p class="muted small">読み込み中…</p></div>
      </div>
      <div class="section no-print">
        <div class="section-title"><h2>更新履歴</h2></div>
        <div id="revisions"><p class="muted small">読み込み中…</p></div>
      </div>`;

    document.getElementById("delIssue").addEventListener("click", async () => {
      if (!confirm(`論点「${it.title}」を削除します。元に戻せません。よろしいですか？`)) return;
      try { await api("DELETE", `/api/issues/${id}`); invalidate(); toast("削除しました"); location.hash = `#/clients/${it.client_id}`; }
      catch (err) { toast(err.message, true); }
    });

    api("GET", `/api/issues/${id}/similar`).then((r) => {
      const el = document.getElementById("similar");
      if (!el) return;
      el.innerHTML = r.items.length ? issueList(r.items) : `<p class="muted small">類似する論点はまだありません。</p>`;
    });
    api("GET", `/api/issues/${id}/revisions`).then((r) => {
      const el = document.getElementById("revisions");
      if (!el) return;
      if (!r.items.length) { el.innerHTML = `<p class="muted small">更新履歴はありません。</p>`; return; }
      // 各履歴は「その保存時点の直前の状態」。次の状態(より新しい履歴 or 現在)との差分を表示する。
      const states = [it].concat(r.items.map((rv) => rv.data)); // 新→旧
      el.innerHTML = r.items.map((rv, i) => {
        const before = rv.data, after = states[i];
        const changed = Object.keys(FIELD_LABELS).filter((k) => JSON.stringify(before[k] ?? "") !== JSON.stringify(after[k] ?? ""));
        const diff = changed.map((k) => {
          const b = Array.isArray(before[k]) ? before[k].join(", ") : before[k];
          const a = Array.isArray(after[k]) ? after[k].join(", ") : after[k];
          return `<dt>${esc(FIELD_LABELS[k])}</dt><dd><span class="muted">変更前:</span> ${esc(b) || "（空）"}\n<span class="muted">変更後:</span> ${esc(a) || "（空）"}</dd>`;
        }).join("");
        return `<details><summary>${fmtDate(rv.saved_at)} に更新 — ${changed.length ? changed.map((k) => FIELD_LABELS[k]).join("・") : "変更なし"}</summary><dl class="rev-diff">${diff}</dl></details>`;
      }).join("");
    });
  }

  async function viewIssueForm(params, id) {
    setNav(id ? null : "new");
    const { path } = parseHash();
    const isCopy = /\/copy$/.test(path);
    const isEdit = !!id && !isCopy;
    const [meta, clients] = await Promise.all([loadMeta(true), loadClients(true)]);
    if (!clients.length) {
      app.innerHTML = `<div class="panel"><p>論点を記録するには、先に顧問先を登録してください。</p><a class="btn primary" href="#/clients/new">顧問先を登録</a></div>`;
      return;
    }
    let it = { client_id: params.client || "", status: "検討中", tax_type: "", tags: [] };
    if (id) {
      it = await api("GET", `/api/issues/${id}`);
      if (isCopy) {
        it = Object.assign({}, it, { fiscal_year: "", status: "検討中", decided_on: "", reviewer: "" });
        // 前年の「翌年以降の留意点」を、今回の検討の出発点として論点欄に引き継ぐ
        if (it.followup) it.question = `【前年からの引継ぎ】${it.followup}\n\n${it.question || ""}`.trim();
        it.analysis = "";
        it.followup = "";
      }
    }
    app.innerHTML = `
      <h1>${isEdit ? "論点を編集" : isCopy ? "論点を複製して記録" : "論点を記録"}</h1>
      ${isCopy ? `<div class="panel warn small">「${esc(it.title)}」（${esc(it.client_name)}）を元に、新しい事業年度の論点として記録します。事実関係・結論・根拠は前回の内容を引き継いでいますので、今回の状況に合わせて修正してください。</div>` : ""}
      <form id="f" class="panel">
        <div class="grid3">
          <div class="field"><label class="required">顧問先</label>
            <select name="client_id" ${isEdit ? "" : ""}>${options(clients.map((c) => ({ value: c.id, label: c.name + (c.code ? ` (${c.code})` : "") })), it.client_id, "選択してください")}</select></div>
          <div class="field"><label>税目</label><select name="tax_type">${options(meta.tax_types, it.tax_type || "法人税")}</select></div>
          <div class="field"><label>ステータス</label><select name="status">${options(meta.statuses, it.status)}</select></div>
        </div>
        <div class="field"><label class="required">論点名</label><input type="text" name="title" value="${esc(it.title)}" placeholder="例: 役員退職金の損金算入額（功績倍率法の妥当性）" required ${isEdit ? "" : "autofocus"}>
          <div class="hint">後から検索しやすいよう、取引・制度名と争点がわかる名称にします。</div></div>
        <div class="grid3">
          <div class="field"><label>事業年度・年分</label><input type="text" name="fiscal_year" value="${esc(it.fiscal_year)}" list="fyList" placeholder="例: 2026年3月期 / 令和7年分">${datalist("fyList", meta.fiscal_years)}</div>
          <div class="field"><label>担当者</label><input type="text" name="staff" value="${esc(it.staff)}" list="staffList">${datalist("staffList", meta.staff)}</div>
          <div class="field"><label>確認者（所長・レビュー担当）</label><input type="text" name="reviewer" value="${esc(it.reviewer)}" list="staffList"></div>
        </div>
        <div class="grid2">
          <div class="field"><label>結論日</label><input type="date" name="decided_on" value="${esc(it.decided_on)}"></div>
          <div class="field"><label>タグ（カンマ・スペース区切り）</label><input type="text" name="tags" value="${esc((it.tags || []).join(", "))}" list="tagList" placeholder="例: インボイス, 経過措置, 免税事業者">${datalist("tagList", meta.tags.map((t) => t.name))}</div>
        </div>
        <div class="field"><label>事実関係・前提</label><textarea name="facts" placeholder="取引の内容、金額、時期、契約関係、関係者、当時の状況など">${esc(it.facts)}</textarea></div>
        <div class="field"><label>論点（何が問題か）</label><textarea name="question" placeholder="どの規定の適用が問題になるか、どの点で判断が分かれるか">${esc(it.question)}</textarea></div>
        <div class="field"><label>検討内容</label><textarea name="analysis" class="tall" placeholder="考えられる取扱いと、それぞれの根拠・リスク。相談先・照会結果があればそれも。">${esc(it.analysis)}</textarea></div>
        <div class="field"><label>結論</label><textarea name="conclusion" placeholder="採用した取扱いと、その理由。顧客への説明内容。">${esc(it.conclusion)}</textarea></div>
        <div class="field"><label>根拠（条文・通達・判例・質疑応答事例・書籍など）</label><textarea name="basis" placeholder="例: 法法34①、法基通9-2-27、国税庁質疑応答事例「…」、○○地裁令和x年x月x日判決">${esc(it.basis)}</textarea></div>
        <div class="field"><label>翌年以降の留意点</label><textarea name="followup" placeholder="翌期以降の申告で確認すべきこと、期限、届出の要否、条件が変わった場合の再検討ポイントなど">${esc(it.followup)}</textarea>
          <div class="hint">記入すると顧問先ページの「要フォロー」に表示され、翌年の申告時に引き当てられます。</div></div>
        <div class="form-actions">
          <button class="btn primary" type="submit">${isEdit ? "更新" : "記録する"}</button>
          <a class="btn" href="${isEdit || isCopy ? `#/issues/${id}` : it.client_id ? `#/clients/${it.client_id}` : "#/"}">キャンセル</a>
          <span class="muted small">Ctrl+Enter で保存</span>
        </div>
      </form>`;
    const form = document.getElementById("f");
    async function submit() {
      try {
        const d = formData(form);
        const saved = isEdit ? await api("PUT", `/api/issues/${id}`, d) : await api("POST", "/api/issues", d);
        invalidate();
        toast(isEdit ? "更新しました" : "記録しました");
        location.hash = `#/issues/${saved.id}`;
      } catch (err) { toast(err.message, true); }
    }
    form.addEventListener("submit", (e) => { e.preventDefault(); submit(); });
    form.addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); submit(); } });
  }

  // ------------------------------------------------------------ views: settings
  async function viewSettings() {
    setNav("settings");
    const meta = await loadMeta(true);
    app.innerHTML = `
      <h1>設定・バックアップ</h1>
      <div class="panel">
        <dl class="kv">
          <dt>データファイル</dt><dd><code>${esc(meta.db_path)}</code></dd>
          <dt>全文検索</dt><dd>${meta.fts ? "有効（SQLite FTS5 / trigram）" : "無効（部分一致検索で動作中）"}</dd>
          <dt>登録件数</dt><dd>顧問先 ${meta.counts.clients} 件 ／ 論点 ${meta.counts.issues} 件</dd>
        </dl>
      </div>
      <h2>バックアップ</h2>
      <div class="panel">
        <p>データはすべて上記の SQLite ファイル 1 つに保存されています。<strong>このファイルをコピーするだけでバックアップになります</strong>（アプリを終了してからコピーしてください）。</p>
        <p>別形式でも書き出せます：</p>
        <p><a class="btn" href="/api/export.json" download>JSON 形式で書き出し（復元・移行用）</a> <a class="btn" href="/api/export.csv" download>CSV 形式で書き出し（Excel 用）</a></p>
      </div>
      <h2>JSON からの取り込み</h2>
      <div class="panel">
        <p class="small muted">上の「JSON 形式で書き出し」で作成したファイルを追加取り込みします。顧問先はコードまたは名称が一致すれば既存に紐付け、論点はすべて新規として追加されます（重複チェックはしません）。</p>
        <div class="row"><input type="file" id="importFile" accept="application/json,.json" style="width:auto"><button class="btn" id="importBtn">取り込む</button></div>
      </div>`;
    document.getElementById("importBtn").addEventListener("click", async () => {
      const f = document.getElementById("importFile").files[0];
      if (!f) { toast("ファイルを選択してください", true); return; }
      try {
        const data = JSON.parse(await f.text());
        const n = (data.issues || []).length;
        if (!confirm(`論点 ${n} 件、顧問先 ${(data.clients || []).length} 件を取り込みます。よろしいですか？`)) return;
        const r = await api("POST", "/api/import", data);
        invalidate();
        toast(`取り込みました（顧問先 ${r.clients_created} 件を新規作成、論点 ${r.issues_created} 件を追加）`);
        location.hash = "#/";
      } catch (err) { toast(err.message, true); }
    });
  }

  // ------------------------------------------------------------ boot
  document.addEventListener("keydown", (e) => {
    if (e.key === "/" && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) {
      const q = document.querySelector('input[name="q"]');
      if (q) { e.preventDefault(); q.focus(); q.select(); }
    }
  });
  render();
})();
