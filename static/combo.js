/* キーボード操作向けコンボボックス (科目・補助科目・部門などの選択) */
'use strict';

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
