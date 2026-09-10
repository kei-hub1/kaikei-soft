/* キーボード操作向けコンボボックス (科目・補助科目・部門などの選択) */
'use strict';

/**
 * makeSuggest(input, options) — 自由入力を許す候補表示 (摘要欄用)。
 *
 * makeCombo と違い、候補に無い文字列もそのまま確定できる。
 *   options.items    : () => [{code, text, kana, account_id}]
 *   options.onCommit : () => void   Enter で確定した時
 *   options.accountIds : () => [id] 関連科目が一致する候補を上位に出す
 * 確定の規則:
 *   1. ↑↓ で候補を選んでいれば、その候補の本文
 *   2. 入力がプリセットのコードと完全一致すれば、その本文に展開
 *   3. それ以外は入力された文字列をそのまま使う
 */
function makeSuggest(input, options) {
  const wrap = document.createElement('div');
  wrap.className = 'combo';
  input.parentNode.insertBefore(wrap, input);
  wrap.appendChild(input);
  const dd = document.createElement('div');
  dd.className = 'dropdown';
  wrap.appendChild(dd);
  input.setAttribute('autocomplete', 'off');

  let filtered = [];
  let hl = -1;
  let navigated = false;

  const norm = (s) => (s || '').toString().toLowerCase()
    .replace(/[Ａ-Ｚａ-ｚ０-９]/g, ch => String.fromCharCode(ch.charCodeAt(0) - 0xFEE0))
    .replace(/[ァ-ヶ]/g, ch => String.fromCharCode(ch.charCodeAt(0) - 0x60));

  function filter(q) {
    const all = options.items() || [];
    const related = new Set((options.accountIds ? options.accountIds() : []).filter(Boolean));
    const score = (it) => (it.account_id && related.has(it.account_id) ? 0 : 1);
    q = norm(q);
    if (!q) return all.slice().sort((a, b) => score(a) - score(b)).slice(0, 60);
    const starts = [], contains = [];
    for (const it of all) {
      const code = norm(it.code), text = norm(it.text), kana = norm(it.kana);
      if (code && code === q) starts.unshift(it);
      else if (code.startsWith(q) || text.startsWith(q) || kana.startsWith(q)) starts.push(it);
      else if (text.includes(q) || kana.includes(q)) contains.push(it);
    }
    starts.sort((a, b) => score(a) - score(b));
    return starts.concat(contains).slice(0, 60);
  }
  function renderDD() {
    dd.innerHTML = filtered.map((it, i) =>
      `<div data-i="${i}" class="${i === hl ? 'hl' : ''}"><span class="c">${esc(it.code || '')}</span><span>${esc(it.text)}</span></div>`).join('');
    dd.classList.toggle('open', filtered.length > 0);
    const h = dd.querySelector('.hl');
    if (h) h.scrollIntoView({ block: 'nearest' });
  }
  function open(q) {
    filtered = filter(q);
    hl = -1;
    navigated = false;
    renderDD();
  }
  function close() { dd.classList.remove('open'); dd.innerHTML = ''; filtered = []; hl = -1; navigated = false; }

  /** 確定後の文字列を返す (副作用として入力欄を書き換える)。 */
  function resolve() {
    if (navigated && hl >= 0 && filtered[hl]) {
      input.value = filtered[hl].text;
    } else {
      const q = input.value.trim();
      const byCode = (options.items() || []).find(it => it.code && norm(it.code) === norm(q));
      if (byCode) input.value = byCode.text;
    }
    close();
    return input.value;
  }

  input.addEventListener('focus', () => selectAllOnFocus(input));
  input.addEventListener('input', () => open(input.value));
  input.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown') {
      if (!dd.classList.contains('open')) open(input.value);
      else if (hl < filtered.length - 1) { hl++; navigated = true; renderDD(); }
      else if (hl === -1 && filtered.length) { hl = 0; navigated = true; renderDD(); }
      e.preventDefault();
    } else if (e.key === 'ArrowUp') {
      if (hl > 0) { hl--; navigated = true; renderDD(); }
      else if (hl === 0) { hl = -1; navigated = false; renderDD(); }
      e.preventDefault();
    } else if (e.key === 'Escape') {
      if (dd.classList.contains('open')) { e.stopPropagation(); close(); }
    } else if (e.key === 'Tab') {
      resolve();
    }
  });
  // Enter は行の確定処理と競合するため、呼び出し側から resolve() を使う
  input.addEventListener('blur', () => {
    setTimeout(() => { if (document.activeElement !== input) { resolve(); if (options.onChange) options.onChange(); } }, 120);
  });
  dd.addEventListener('mousedown', (e) => {
    const row = e.target.closest('[data-i]');
    if (!row) return;
    e.preventDefault();
    input.value = filtered[Number(row.dataset.i)].text;
    close();
    input.focus();
    if (options.onChange) options.onChange();
  });

  const api = { input, resolve, close, open: () => open(''), get isOpen() { return dd.classList.contains('open'); } };
  input._suggest = api;
  return api;
}

/**
 * makeCombo(input, options)
 *   options.items    : () => [{id, code, name, kana}]
 *   options.onCommit : (item|null) => void   Enter で確定した時に呼ばれる (null = 空で確定)
 *   options.onChange : (item|null) => void   選択が変わった時
 *   options.allowEmpty : 空を許すか (既定 true)
 * input.dataset.id に選択 id を保持する。
 */
function makeCombo(input, options) {
  const wrap = document.createElement('div');
  wrap.className = 'combo';
  input.parentNode.insertBefore(wrap, input);
  wrap.appendChild(input);
  const dd = document.createElement('div');
  dd.className = 'dropdown';
  wrap.appendChild(dd);
  input.setAttribute('autocomplete', 'off');

  let filtered = [];
  let hl = -1;
  let lastLabel = '';

  const label = (it) => it ? (it.code ? `${it.code} ${it.name}` : it.name) : '';
  const norm = (s) => (s || '').toString().toLowerCase()
    .replace(/[Ａ-Ｚａ-ｚ０-９]/g, ch => String.fromCharCode(ch.charCodeAt(0) - 0xFEE0))
    .replace(/[ァ-ヶ]/g, ch => String.fromCharCode(ch.charCodeAt(0) - 0x60)); // カタカナ→ひらがな

  function items() { return (options.items() || []).filter(it => it.active === undefined || it.active); }

  function filter(q) {
    const all = items();
    q = norm(q);
    if (!q) return all;
    const starts = [], contains = [];
    for (const it of all) {
      const code = norm(it.code), name = norm(it.name), kana = norm(it.kana);
      if (code.startsWith(q) || name.startsWith(q) || kana.startsWith(q)) starts.push(it);
      else if (code.includes(q) || name.includes(q) || kana.includes(q)) contains.push(it);
    }
    return starts.concat(contains);
  }

  function renderDD() {
    dd.innerHTML = filtered.slice(0, 60).map((it, i) =>
      `<div data-i="${i}" class="${i === hl ? 'hl' : ''}"><span class="c">${esc(it.code || '')}</span><span>${esc(it.name)}</span></div>`).join('');
    dd.classList.toggle('open', filtered.length > 0);
    const h = dd.querySelector('.hl');
    if (h) h.scrollIntoView({ block: 'nearest' });
  }
  function open(q) {
    filtered = filter(q);
    hl = filtered.length ? 0 : -1;
    renderDD();
  }
  function close() { dd.classList.remove('open'); dd.innerHTML = ''; filtered = []; hl = -1; }

  function select(it, commit) {
    const prev = input.dataset.id || '';
    input.dataset.id = it ? String(it.id) : '';
    input.value = label(it);
    lastLabel = input.value;
    close();
    if (prev !== (input.dataset.id || '') && options.onChange) options.onChange(it);
    if (commit && options.onCommit) options.onCommit(it);
  }

  /** 入力テキストから確定候補を求める: 完全一致コード > 唯一の候補 > ハイライト */
  function resolve() {
    const q = input.value.trim();
    if (!q) return null;
    const all = items();
    const exact = all.find(it => norm(it.code) === norm(q));
    if (exact) return exact;
    const byLabel = all.find(it => label(it) === q);
    if (byLabel) return byLabel;
    if (dd.classList.contains('open') && hl >= 0) return filtered[hl];
    const f = filter(q);
    if (f.length >= 1) return f[0];
    return undefined; // 該当なし
  }

  input.addEventListener('focus', () => {
    lastLabel = input.value;
    selectAllOnFocus(input);
  });
  input.addEventListener('input', () => {
    input.dataset.id = '';
    open(input.value);
  });
  input.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown') {
      if (!dd.classList.contains('open')) { open(''); }
      else if (hl < filtered.length - 1) { hl++; renderDD(); }
      e.preventDefault();
    } else if (e.key === 'ArrowUp') {
      if (hl > 0) { hl--; renderDD(); }
      e.preventDefault();
    } else if (e.key === 'Enter') {
      e.preventDefault();
      e.stopPropagation();
      const q = input.value.trim();
      if (!q) {
        if (options.allowEmpty === false && input.dataset.id) { close(); return; }
        select(null, true);
        return;
      }
      if (input.dataset.id && q === lastLabel) { close(); if (options.onCommit) options.onCommit(items().find(it => String(it.id) === input.dataset.id) || null); return; }
      const it = resolve();
      if (it) select(it, true);
      else { toast('該当する項目がありません', true); open(input.value); }
    } else if (e.key === 'Escape') {
      if (dd.classList.contains('open')) { e.stopPropagation(); close(); input.value = lastLabel; }
    } else if (e.key === 'Tab') {
      if (input.value.trim() && !input.dataset.id) {
        const it = resolve();
        if (it) select(it, false); else { input.value = ''; }
      } else if (!input.value.trim()) {
        select(null, false);
      }
      close();
    }
  });
  input.addEventListener('blur', () => {
    setTimeout(() => {
      if (document.activeElement === input) return;
      if (input.value.trim() && !input.dataset.id) {
        const it = resolve();
        if (it) select(it, false); else { input.value = ''; if (options.onChange) options.onChange(null); }
      } else if (!input.value.trim() && input.dataset.id) {
        select(null, false);
      }
      close();
    }, 120);
  });
  dd.addEventListener('mousedown', (e) => {
    const row = e.target.closest('[data-i]');
    if (!row) return;
    e.preventDefault();
    select(filtered[Number(row.dataset.i)], true);
  });

  const combo = {
    input,
    set(id) {
      const it = id ? items().concat(options.items() || []).find(x => String(x.id) === String(id)) : null;
      input.dataset.id = it ? String(it.id) : '';
      input.value = label(it);
      lastLabel = input.value;
    },
    get id() { return input.dataset.id ? Number(input.dataset.id) : null; },
    get item() { return this.id ? (options.items() || []).find(x => x.id === this.id) || null : null; },
    clear() { this.set(null); },
    refresh() { if (this.id) this.set(this.id); },
  };
  input._combo = combo;
  return combo;
}
