/* 共通: 状態 / API / ユーティリティ / ルーティング */
'use strict';

const S = {
  meta: null,
  clients: [],
  client: null,        // 選択中の顧問先
  fiscalYears: [],
  fy: null,            // 選択中の会計期間
  accounts: [],        // 選択中顧問先の科目 (有効/無効含む)
  accountById: {},
  subsByAccount: {},   // account_id -> [sub]
  subById: {},
  departments: [],
  templates: [],
  descriptions: [],       // 摘要プリセット
  descriptionItems: [],   // 入力候補 (プリセット + 過去に使った摘要)
  taxById: {},
};

const routes = {};   // name -> render(fn)

// ---------------------------------------------------------------- API
async function api(method, url, body, opts = {}) {
  const init = { method, headers: {} };
  if (body instanceof FormData) {
    init.body = body;
  } else if (body !== undefined) {
    init.headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(body);
  }
  const res = await fetch(url, init);
  if (res.status === 204) return null;
  const ct = res.headers.get('content-type') || '';
  const data = ct.includes('application/json') ? await res.json() : await res.text();
  if (!res.ok) {
    let msg = typeof data === 'string' ? data : (data.detail || JSON.stringify(data));
    if (Array.isArray(msg)) msg = msg.map(e => `${(e.loc || []).join('.')}: ${e.msg}`).join(' / ');
    const err = new Error(msg);
    err.status = res.status;
    throw err;
  }
  return data;
}
const GET = (u) => api('GET', u);
const POST = (u, b) => api('POST', u, b);
const PUT = (u, b) => api('PUT', u, b);
const DEL = (u) => api('DELETE', u);

// ---------------------------------------------------------------- utils
function fmt(n) {
  if (n === null || n === undefined || n === '') return '';
  const v = Number(n);
  if (Number.isNaN(v)) return '';
  const s = Math.abs(v).toLocaleString('ja-JP');
  return v < 0 ? '△' + s : s;
}
function fmtCell(n) {
  const v = Number(n) || 0;
  return `<td class="num${v < 0 ? ' neg' : ''}">${v === 0 ? '' : fmt(v)}</td>`;
}
function fmtCell0(n) {
  const v = Number(n) || 0;
  return `<td class="num${v < 0 ? ' neg' : ''}">${fmt(v)}</td>`;
}
function parseAmount(s) {
  if (s === null || s === undefined) return 0;
  s = String(s).replace(/[,，¥￥\s]/g, '').replace(/[０-９]/g, ch => String.fromCharCode(ch.charCodeAt(0) - 0xFEE0));
  if (s === '') return 0;
  const v = Number(s);
  return Number.isFinite(v) ? Math.round(v) : 0;
}
function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
function el(html) {
  const t = document.createElement('template');
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}
function $(sel, root = document) { return root.querySelector(sel); }
function $$(sel, root = document) { return Array.from(root.querySelectorAll(sel)); }
function today() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}
function fmtDate(iso) {
  if (!iso) return '';
  const [y, m, d] = iso.split('-');
  return `${y}/${m}/${d}`;
}
function fmtDateShort(iso) {
  if (!iso) return '';
  const [, m, d] = iso.split('-');
  return `${m}/${d}`;
}
/**
 * 日付の簡易入力を解釈する。
 *   "0401" / "401" → 会計期間内の 4/1、"20260401"、"2026-04-01"、"2026/4/1"、"4/1"
 */
function parseDateInput(s, fy) {
  s = (s || '').trim().replace(/[０-９]/g, ch => String.fromCharCode(ch.charCodeAt(0) - 0xFEE0));
  if (!s) return null;
  let y, m, d;
  let mt;
  if ((mt = s.match(/^(\d{4})[-\/.](\d{1,2})[-\/.](\d{1,2})$/))) {
    [y, m, d] = [+mt[1], +mt[2], +mt[3]];
  } else if ((mt = s.match(/^(\d{4})(\d{2})(\d{2})$/))) {
    [y, m, d] = [+mt[1], +mt[2], +mt[3]];
  } else if ((mt = s.match(/^(\d{1,2})[-\/.](\d{1,2})$/))) {
    [m, d] = [+mt[1], +mt[2]];
  } else if ((mt = s.match(/^(\d{3,4})$/))) {
    const t = mt[1].padStart(4, '0');
    m = +t.slice(0, 2); d = +t.slice(2);
  } else if ((mt = s.match(/^(\d{1,2})$/))) {
    d = +mt[1];
  } else {
    return null;
  }
  if (y === undefined) {
    // 会計期間内で年を推定 (期首年→期末年)
    const base = fy ? fy.start_date : today();
    const [by, bm] = base.split('-').map(Number);
    if (m === undefined) m = bm;
    if (fy) {
      const [ey] = fy.end_date.split('-').map(Number);
      y = by;
      const cand = `${y}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
      if (cand < fy.start_date && ey > by) y = ey;
    } else {
      y = by;
    }
  }
  const dt = new Date(y, m - 1, d);
  if (dt.getFullYear() !== y || dt.getMonth() !== m - 1 || dt.getDate() !== d) return null;
  return `${y}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
}
function addDays(iso, n) {
  const [y, m, d] = iso.split('-').map(Number);
  const dt = new Date(y, m - 1, d + n);
  return `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, '0')}-${String(dt.getDate()).padStart(2, '0')}`;
}

/**
 * フォーカス時に全選択する。setTimeout を使うと入力開始後に選択が走って先頭文字が消えるため同期で行い、
 * マウスクリックによる選択解除は mouseup を 1 回だけ抑止して防ぐ。
 */
function selectAllOnFocus(input) {
  input.select();
  input._keepSel = true;
  if (!input._selBound) {
    input._selBound = true;
    input.addEventListener('mouseup', (e) => { if (input._keepSel) { e.preventDefault(); input._keepSel = false; } });
    input.addEventListener('keydown', () => { input._keepSel = false; });
  }
}

let toastTimer = null;
function toast(msg, isError = false) {
  const t = $('#toast');
  t.textContent = msg;
  t.className = 'show' + (isError ? ' error' : '');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.className = ''; }, isError ? 5000 : 2500);
}
function showError(e) {
  console.error(e);
  toast(e && e.message ? e.message : String(e), true);
}

function modal(html, { onOpen, onClose } = {}) {
  const bg = el(`<div class="modal-bg"><div class="modal">${html}</div></div>`);
  document.body.appendChild(bg);
  let closed = false;
  const close = () => {
    if (closed) return;
    closed = true;
    bg.remove();
    document.removeEventListener('keydown', onKey);
    if (onClose) onClose();
  };
  const onKey = (e) => {
    if (e.key !== 'Escape') return;
    // ダイアログが重なっているときは、一番手前のものだけ閉じる
    const all = $$('.modal-bg');
    if (all[all.length - 1] !== bg) return;
    e.stopPropagation();
    close();
  };
  document.addEventListener('keydown', onKey);
  bg.addEventListener('mousedown', (e) => { if (e.target === bg) close(); });
  $$('[data-close]', bg).forEach(b => b.addEventListener('click', close));
  if (onOpen) onOpen(bg, close);
  return { bg, close };
}
function confirmDialog(msg) {
  return new Promise((resolve) => {
    const { close } = modal(`<h3>確認</h3><div>${esc(msg)}</div>
      <div class="actions"><button data-cancel>キャンセル</button><button class="primary" data-ok>OK</button></div>`, {
      onOpen(bg) {
        $('[data-ok]', bg).focus();
        $('[data-ok]', bg).onclick = () => { close(); resolve(true); };
        $('[data-cancel]', bg).onclick = () => { close(); resolve(false); };
      },
    });
  });
}

// ---------------------------------------------------------------- master loading
function taxName(code) { const t = S.taxById[code]; return t ? t.name : code; }
function taxShort(code) { const t = S.taxById[code]; return t ? t.short : code; }
function acctLabel(id) { const a = S.accountById[id]; return a ? `${a.code} ${a.name}` : ''; }
function subLabel(id) { const s = S.subById[id]; return s ? s.name : ''; }
function deptLabel(id) { const d = S.departments.find(x => x.id === id); return d ? d.name : ''; }
function isExempt() { return S.client && S.client.tax_method === 'exempt'; }

async function loadMeta() {
  S.meta = await GET('/api/meta');
  S.taxById = Object.fromEntries(S.meta.tax_classes.map(t => [t.code, t]));
}

async function loadClients() {
  S.clients = await GET('/api/clients');
  const sel = $('#sel-client');
  sel.innerHTML = '<option value="">(顧問先を選択)</option>' +
    S.clients.map(c => `<option value="${c.id}">${esc(c.code)} ${esc(c.name)}</option>`).join('');
  const saved = localStorage.getItem('clientId');
  const cid = S.client ? S.client.id : (saved && S.clients.some(c => String(c.id) === saved) ? Number(saved) : (S.clients[0] && S.clients[0].id));
  if (cid) await selectClient(cid); else await selectClient(null);
}

async function selectClient(id, keepFy = false) {
  S.client = S.clients.find(c => c.id === Number(id)) || null;
  $('#sel-client').value = S.client ? S.client.id : '';
  localStorage.setItem('clientId', S.client ? S.client.id : '');
  if (!S.client) {
    S.fiscalYears = []; S.fy = null; S.accounts = []; S.accountById = {}; S.subsByAccount = {}; S.subById = {};
    S.departments = []; S.templates = []; S.descriptions = []; S.descriptionItems = [];
    $('#sel-fy').innerHTML = '';
    $('#client-badges').innerHTML = '';
    return;
  }
  const c = S.client;
  const tm = S.meta.tax_methods.find(t => t.code === c.tax_method);
  $('#client-badges').innerHTML =
    `<span class="badge">${c.entity_type === 'sole' ? '個人' : '法人'}</span> <span class="badge">${esc(tm ? tm.name : c.tax_method)}</span>`;
  await Promise.all([loadFiscalYears(keepFy), loadAccounts(), loadDepartments(), loadTemplates(), loadDescriptions()]);
}

async function loadFiscalYears(keep = false) {
  S.fiscalYears = await GET(`/api/clients/${S.client.id}/fiscal-years`);
  const sel = $('#sel-fy');
  sel.innerHTML = S.fiscalYears.map(f =>
    `<option value="${f.id}">${esc(f.label)} (${fmtDate(f.start_date)}〜${fmtDate(f.end_date)})${f.closed ? ' [締]' : ''}</option>`).join('');
  const savedKey = 'fyId:' + S.client.id;
  const saved = Number(localStorage.getItem(savedKey));
  let fy = null;
  if (keep && S.fy) fy = S.fiscalYears.find(f => f.id === S.fy.id);
  if (!fy && saved) fy = S.fiscalYears.find(f => f.id === saved);
  if (!fy) {
    const t = today();
    fy = S.fiscalYears.find(f => f.start_date <= t && t <= f.end_date) || S.fiscalYears[S.fiscalYears.length - 1] || null;
  }
  S.fy = fy;
  sel.value = fy ? fy.id : '';
  if (fy) localStorage.setItem(savedKey, fy.id);
}

async function loadAccounts() {
  const [accounts, subs] = await Promise.all([
    GET(`/api/clients/${S.client.id}/accounts`),
    GET(`/api/clients/${S.client.id}/sub-accounts`),
  ]);
  S.accounts = accounts;
  S.accountById = Object.fromEntries(accounts.map(a => [a.id, a]));
  S.subsByAccount = {};
  S.subById = {};
  for (const s of subs) {
    (S.subsByAccount[s.account_id] = S.subsByAccount[s.account_id] || []).push(s);
    S.subById[s.id] = s;
  }
}
async function loadDepartments() { S.departments = await GET(`/api/clients/${S.client.id}/departments`); }
async function loadTemplates() { S.templates = await GET(`/api/clients/${S.client.id}/templates`); }

/** 摘要プリセットと、仕訳入力で出す候補 (プリセット + 過去に使った摘要) を読み込む。 */
async function loadDescriptions() {
  const [presets, sug] = await Promise.all([
    GET(`/api/clients/${S.client.id}/descriptions`),
    GET(`/api/clients/${S.client.id}/description-suggestions`),
  ]);
  S.descriptions = presets;
  S.descriptionItems = sug.presets.concat(
    sug.history.map(h => ({ id: null, code: '', text: h.text, kana: '', account_id: null, used: h.n })));
}

// ---------------------------------------------------------------- router
let currentRoute = null;
let currentCleanup = null;

function parseHash() {
  const h = location.hash.replace(/^#\/?/, '');
  const [name, qs] = h.split('?');
  const params = Object.fromEntries(new URLSearchParams(qs || ''));
  return { name: name || 'entry', params };
}

async function render() {
  const { name, params } = parseHash();
  const main = $('#main');
  if (currentCleanup) { try { currentCleanup(); } catch (e) { /* ignore */ } currentCleanup = null; }
  $$('#nav a').forEach(a => a.classList.toggle('active', a.dataset.route === name));
  currentRoute = name;
  const fn = routes[name];
  if (!fn) { main.innerHTML = '<div class="empty">ページが見つかりません</div>'; return; }
  const needsClient = !['clients', 'data'].includes(name);
  if (needsClient && !S.client) {
    main.innerHTML = `<div class="panel"><h2>顧問先が登録されていません</h2>
      <p>まず <a href="#/clients">顧問先・会計期間</a> から顧問先を登録してください。</p></div>`;
    return;
  }
  main.className = '';
  main.innerHTML = '';
  try {
    const cleanup = await fn(main, params);
    if (typeof cleanup === 'function') currentCleanup = cleanup;
  } catch (e) {
    showError(e);
    main.innerHTML += `<div class="panel neg">エラー: ${esc(e.message)}</div>`;
  }
}

function navigate(name, params) {
  const qs = params ? '?' + new URLSearchParams(params).toString() : '';
  const target = `#/${name}${qs}`;
  if (location.hash === target) render(); else location.hash = target;
}

// ------------------------------------------------- 帳票の掘り下げと、元の画面への復帰
// 残高試算表 → 総勘定元帳 のように帳票から帳票へ移ったとき、Esc で元の画面に戻れる
// ようにする。戻り先は「移る直前の画面の状態」をそのまま URL にしたもの。
let drill = null;              // { from, to, scroll, label, rowKey }
let pendingDrillRestore = null;

function drillDown(name, params, { label, rowKey, from } = {}) {
  const qs = params ? '?' + new URLSearchParams(params).toString() : '';
  drill = {
    from: from || location.hash, to: `#/${name}${qs}`,
    scroll: window.scrollY, label: label || '前の画面', rowKey: rowKey || null,
  };
  navigate(name, params);
}

/** いま開いている画面に戻り先があれば返す。別の画面へ移ったら無効になる。 */
function currentDrill() { return drill && drill.to === location.hash ? drill : null; }

function drillBack() {
  const d = currentDrill();
  if (!d) return false;
  drill = null;
  pendingDrillRestore = d;
  if (location.hash === d.from) render(); else location.hash = d.from;
  return true;
}

/** 戻ってきた画面を描き終えたら呼ぶ。元の位置までスクロールし、元の行を光らせる。 */
function restoreDrillPosition(tableSelector, rowAttr) {
  const d = pendingDrillRestore;
  pendingDrillRestore = null;
  if (!d) return;
  const tr = d.rowKey && tableSelector
    ? $(`${tableSelector} tr[${rowAttr}="${CSS.escape(String(d.rowKey))}"]`) : null;
  if (tr) {
    tr.scrollIntoView({ block: 'center' });
    tr.classList.add('flash');
    setTimeout(() => tr.classList.remove('flash'), 1600);
  } else {
    window.scrollTo({ top: d.scroll });
  }
}

/** 戻り先があるときだけ出す「戻る」ボタン。画面の toolbar に差し込む。 */
function backButtonHtml() {
  const d = currentDrill();
  return d ? `<button id="drill-back" class="no-print" title="${esc(d.label)}へ戻ります">◀ ${esc(d.label)}へ戻る <kbd>Esc</kbd></button>` : '';
}

/** 戻るボタンと Esc キーを有効にする。戻り値を画面の後片付けに使う。 */
function bindDrillBack() {
  const btn = $('#drill-back');
  if (btn) btn.onclick = () => drillBack();
  const onKey = (e) => {
    if (e.key !== 'Escape') return;
    // ダイアログや科目の候補一覧が開いているときは、そちらを閉じるのが先
    if (document.querySelector('.modal-bg')) return;
    if (document.querySelector('.combo .dropdown.open')) return;
    if (drillBack()) e.preventDefault();
  };
  document.addEventListener('keydown', onKey);
  return () => document.removeEventListener('keydown', onKey);
}

function reportHeader(title, period) {
  const c = S.client;
  return `<div class="report-title"><div><span class="client">${esc(c.code)} ${esc(c.name)}</span>　<b>${esc(title)}</b></div>
    <div class="period">${esc(period || '')}</div></div>`;
}
