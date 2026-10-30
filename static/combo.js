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
 *
 * 予測変換: 打った文字だけでなく、漢字に変換する前の読み (かな) でも候補を探す。
 *   「でんき」と打った時点 (変換前) で「電気代」や通帳の「ﾃﾞﾝｷ ﾀﾞｲ」が候補に出る。
 *   漢字の摘要は読みを知らないと探せないので、仕訳を登録したときに打った読みを
 *   サーバーへ送って覚えさせる (reading())。次からはその読みで候補に出る。
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

  // 半角カナ・全角英数をそろえ、カタカナはひらがなにする。空白は無視する。
  const norm = (s) => (s || '').toString().normalize('NFKC').toLowerCase()
    .replace(/[ァ-ヶ]/g, ch => String.fromCharCode(ch.charCodeAt(0) - 0x60))
    .replace(/\s+/g, '');
  const isKana = (s) => /^[ぁ-ゖァ-ヺーｦ-ﾟ]+$/.test(s || '');

  // ---- 読みの記録 ----
  //   reading      : 確定済みの部分の読み (かな)。分からなくなったら null
  //   readingValue : reading がどの入力内容に対応しているか。入力欄の値と食い違えば読みは不明
  //   composing    : 変換中 (未確定) の読み
  let reading = '';
  let readingValue = '';
  let composing = '';
  let lastKana = '';
  let compStartOk = false;
  const readingOk = () => reading !== null && readingValue === input.value;
  function setReading(r) { reading = r; readingValue = input.value; }
  /** いま入力欄にある文字の読み (確定分 + 変換中)。分からなければ ''。 */
  function currentReading() {
    if (composing) return (compStartOk ? reading : '') + composing;
    return readingOk() ? reading : '';
  }

  function filter(q) {
    const all = options.items() || [];
    const related = new Set((options.accountIds ? options.accountIds() : []).filter(Boolean));
    const score = (it) => (it.account_id && related.has(it.account_id) ? 0 : 1);
    q = norm(q);
    const r = norm(currentReading());
    if (!q && !r) return all.slice().sort((a, b) => score(a) - score(b)).slice(0, 60);
    const keys = [q, r].filter(Boolean);
    const starts = [], contains = [];
    for (const it of all) {
      const code = norm(it.code), text = norm(it.text), kana = norm(it.kana);
      if (code && code === q) { starts.unshift(it); continue; }
      if (keys.some(k => (code && code.startsWith(k)) || text.startsWith(k) || (kana && kana.startsWith(k)))) starts.push(it);
      else if (keys.some(k => text.includes(k) || (kana && kana.includes(k)))) contains.push(it);
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

  /** 候補を選んだとき: 本文を入れ、読みは候補の読みに置き換える。 */
  function choose(it) {
    input.value = it.text;
    setReading(it.kana ? norm(it.kana) : null);
  }

  /** 確定後の文字列を返す (副作用として入力欄を書き換える)。 */
  function resolve() {
    if (navigated && hl >= 0 && filtered[hl]) {
      choose(filtered[hl]);
    } else {
      const q = input.value.trim();
      const byCode = (options.items() || []).find(it => it.code && norm(it.code) === norm(q));
      if (byCode) choose(byCode);
    }
    close();
    return input.value;
  }

  input.addEventListener('focus', () => {
    selectAllOnFocus(input);
    if (!input.value) setReading('');
  });
  input.addEventListener('compositionstart', () => {
    // 全体が選択された状態 (欄に入った直後) で打ち始めたら、前の内容は置き換わる
    if (input.selectionStart === 0 && input.selectionEnd === input.value.length) { reading = ''; compStartOk = true; }
    else compStartOk = readingOk();
    composing = ''; lastKana = '';
  });
  input.addEventListener('compositionupdate', (e) => {
    // 変換キーを押す前の、かなだけの状態を読みとして控える
    if (isKana(e.data)) lastKana = e.data;
    composing = lastKana;
  });
  input.addEventListener('compositionend', (e) => {
    const got = lastKana || (isKana(e.data) ? e.data : '');
    if (compStartOk && got) setReading(reading + got);
    else setReading(null);
    composing = ''; lastKana = '';
    open(input.value);
  });
  input.addEventListener('input', (e) => {
    if (!input.value) setReading('');
    else if (e.isComposing || e.inputType === 'insertCompositionText') { /* 変換中は composition 側で扱う */ }
    else if (e.inputType === 'insertText' && e.data) {           // 直接入力 (英数など)
      if (input.value === e.data) setReading(e.data);
      else if (reading !== null && readingValue + e.data === input.value) setReading(reading + e.data);
      else setReading(null);
    } else setReading(null);                     // 削除・貼り付けなど。読みは分からなくなる
    open(input.value);
  });
  input.addEventListener('keydown', (e) => {
    if (e.isComposing || e.keyCode === 229) return;     // 変換中のキーは IME に任せる
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
    choose(filtered[Number(row.dataset.i)]);
    close();
    input.focus();
    if (options.onChange) options.onChange();
  });

  const api = {
    input, resolve, close, open: () => open(''), get isOpen() { return dd.classList.contains('open'); },
    /** 入力欄の摘要の読み (かな)。打った読みが分からないときは ''。 */
    reading() { return readingOk() && reading && isKana(reading) ? reading : ''; },
  };
  input._suggest = api;
  return api;
}

/**
 * makeCombo(input, options)
 *   options.items    : () => [{id, code, name, kana}]
 *   options.onCommit : (item|null) => void   Enter で確定した時に呼ばれる (null = 空で確定)
 *   options.onChange : (item|null) => void   選択が変わった時
 *   options.allowEmpty : 空を許すか (既定 true)
 *   options.openOnFocus : カーソルが入ったら候補一覧を開くか (既定 false)
 *                         補助科目のように「何が選べるか」をその場で示したい欄で使う
 *   options.emptyFallback : () => item|null
 *                         空欄のまま Enter を押した時に、代わりに入れる項目を返す。
 *                         仕訳入力で「前の行と同じ科目」を補うために使う。
 *                         null を返せば従来どおり空のまま次へ進む。
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
  // 上下キーで候補を選んだかどうか。候補が開いているだけの状態と区別する。
  let navigated = false;

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
    navigated = false;
    renderDD();
  }
  function close() { dd.classList.remove('open'); dd.innerHTML = ''; filtered = []; hl = -1; navigated = false; }

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
    // 補助科目などは、カーソルが入った時点で候補を出す。
    // 既に選んである場合は絞り込まずに全件出し、その場で選び直せるようにする。
    if (options.openOnFocus && !input.disabled) open(input.dataset.id ? '' : input.value);
  });
  input.addEventListener('input', () => {
    input.dataset.id = '';
    open(input.value);
  });
  input.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown') {
      if (!dd.classList.contains('open')) { open(''); }
      else if (hl < filtered.length - 1) { hl++; renderDD(); }
      navigated = filtered.length > 0;
      e.preventDefault();
    } else if (e.key === 'ArrowUp') {
      if (hl > 0) { hl--; renderDD(); }
      navigated = filtered.length > 0;
      e.preventDefault();
    } else if (e.key === 'Enter') {
      e.preventDefault();
      e.stopPropagation();
      // 上下キーで候補を選んでいれば、入力欄の文字や選択済みの内容に関わらずそれを確定する。
      // 補助科目のようにカーソルが入ると候補が開く欄で、打たずに選べるようにするため。
      if (navigated && hl >= 0 && filtered[hl]) { select(filtered[hl], true); return; }
      const q = input.value.trim();
      if (!q) {
        if (options.emptyFallback) {
          const fb = options.emptyFallback();
          if (fb) { select(fb, true); return; }
        }
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
    /** 入力途中の文字を確定する。確定できなければ false を返す。
     *  保存の直前に呼ぶ。画面に見えている文字と、実際に保存される内容を一致させるため。 */
    commitText() {
      const q = input.value.trim();
      if (!q) {                                   // 空欄にした = 選択を外す
        if (input.dataset.id) select(null, false);
        close();
        return true;
      }
      if (input.dataset.id && q === lastLabel) { close(); return true; }   // 確定済みで変化なし
      const it = resolve();
      close();
      if (!it) return false;                      // 該当する項目が無い
      select(it, false);
      return true;
    },
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
