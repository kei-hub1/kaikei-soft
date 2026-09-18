/* 仕訳入力フォーム

   「仕訳入力」画面と、帳票 (総勘定元帳・仕訳帳) から開く修正ダイアログで
   同じフォームを使う。createEntryForm() が中身を作り、routes.entry は
   それを画面に置いたもの、openEntryDialog() はダイアログに置いたもの。 */
'use strict';

function createEntryForm(root, opts = {}) {
  const inDialog = !!opts.inDialog;
  const onChanged = opts.onChanged || (async () => {});
  const hasDept = S.departments.some(d => d.active);
  const exempt = isExempt();
  let editingId = null;      // 修正中の伝票 id
  let editingVno = null;
  let lastSaved = null;
  // 読み込んだ時点からの変更を見張る。別の伝票へ移る前に保存するかどうかの判断に使う。
  //   typed    : 手で文字を打ったか (打ちかけで未確定の文字も拾うため)
  //   baseline : 読み込んだ (または保存した) 時点の内容。定型仕訳の適用・行の追加や削除は
  //              入力イベントを出さないので、内容そのものを比べて変化を見つける
  let typed = false;
  let baseline = '';

  root.innerHTML = `
  <div class="panel" id="entry-form">
    <div class="head">
      <div class="field"><span>日付 (月日 例: 0401)</span>
        <div class="row" style="gap:6px"><input id="e-date" class="mono" style="width:120px"><span id="e-date-disp" class="muted"></span></div></div>
      <div class="field"><span>伝票No</span><input id="e-vno" class="num" style="width:70px" readonly></div>
      <div class="field"><span>伝票メモ</span><input id="e-memo" class="memo" style="width:200px"></div>
      <button id="e-template" title="定型仕訳を呼び出す">定型仕訳 <kbd>F2</kbd></button>
      <button id="e-tosave" title="いま入力されている内容を、伝票まるごと定型仕訳に登録します">定型登録 <kbd>F3</kbd></button>
      ${inDialog ? '' : '<button id="e-copy" title="直前に登録した伝票を複写">前伝票複写 <kbd>F5</kbd></button>'}
      <div class="status" id="e-status"></div>
    </div>
    <table class="entry-grid">
      <colgroup>
        <col style="width:28px">
        <col><col style="width:11%">${hasDept ? '<col style="width:8%">' : ''}
        <col><col style="width:11%">${hasDept ? '<col style="width:8%">' : ''}
        <col style="width:11%">${exempt ? '' : '<col style="width:9%"><col style="width:8%">'}
        <col style="width:18%"><col style="width:34px">
      </colgroup>
      <thead><tr>
        <th>#</th>
        <th class="dr">借方科目</th><th class="dr">借方補助</th>${hasDept ? '<th class="dr">部門</th>' : ''}
        <th class="cr">貸方科目</th><th class="cr">貸方補助</th>${hasDept ? '<th class="cr">部門</th>' : ''}
        <th>金額</th>${exempt ? '' : '<th>税区分</th><th>内消費税</th>'}
        <th>摘要</th><th></th>
      </tr></thead>
      <tbody id="e-lines"></tbody>
    </table>
    <div class="entry-footer">
      <div class="totals">借方 <b id="t-dr">0</b>　貸方 <b id="t-cr">0</b>　差額 <b id="t-diff" class="diff">0</b>
        <span id="t-suspense" class="suspense" hidden>　|　資金諸口 借方 <b id="t-sdr">0</b> / 貸方 <b id="t-scr">0</b>
          / 差額 <b id="t-sdiff" class="diff">0</b></span></div>
      <div class="actions">
        <button id="e-addrow" title="同じ伝票に行を足します (複合仕訳)">行追加 <kbd>Shift</kbd></button>
        ${inDialog ? '' : '<button id="e-clear">クリア <kbd>Esc</kbd></button>'}
        <button id="e-delete" class="danger" style="display:none">この伝票を削除</button>
        <button id="e-save" class="primary">${inDialog ? '修正を保存' : '登録'} <kbd>Ctrl+Enter</kbd></button>
      </div>
    </div>
    <div class="help">
      <kbd>Enter</kbd> 次の項目 / <kbd>Shift+Enter</kbd> 前の項目 / 科目はコード・かな・名称で検索 <kbd>↑↓</kbd> で選択 /
      金額欄で空欄のまま <kbd>Enter</kbd> → 差額を入力 / 摘要欄で <kbd>Enter</kbd> → 貸借一致なら${inDialog ? '保存' : '登録'}、不一致なら行追加 /
      資金諸口を使うと借方・貸方の合計を表示。釣り合うまで${inDialog ? '保存' : '登録'}できません /
      補助科目がある科目は確定すると候補が開くので <kbd>↑↓</kbd> と <kbd>Enter</kbd> で選択 (不要ならそのまま <kbd>Enter</kbd>) /
      <kbd>Shift</kbd> 単独で押して離すと行追加 (同じ伝票にまとめる) /
      2 行目以降は科目欄で空のまま <kbd>Enter</kbd> → 前の行と同じ科目 (空のまま進むときは <kbd>Tab</kbd>) /
      <kbd>Ctrl+Del</kbd> 行削除 / 摘要は <kbd>F4</kbd> または入力で候補表示、コード入力 + <kbd>Enter</kbd> で展開
      ${inDialog ? '/ <kbd>Esc</kbd> 保存して閉じる' : ''}
    </div>
  </div>`;

  const q = (sel) => $(sel, root);
  root.addEventListener('input', () => { typed = true; });
  root.addEventListener('change', () => { typed = true; });
  const tbody = q('#e-lines');
  const dateInput = q('#e-date');
  const memoInput = q('#e-memo');
  let currentDate = sessionStorage.getItem('entryDate:' + S.fy.id) || (S.fy.start_date <= today() && today() <= S.fy.end_date ? today() : S.fy.start_date);

  // ---------------------------------------------------------------- 日付
  function setDate(iso) {
    currentDate = iso;
    dateInput.value = iso;
    q('#e-date-disp').textContent = fmtDate(iso).slice(0) + ' ' + ['日', '月', '火', '水', '木', '金', '土'][new Date(iso).getDay()];
    if (!inDialog) sessionStorage.setItem('entryDate:' + S.fy.id, iso);
    q('#e-date-disp').classList.toggle('neg', iso < S.fy.start_date || iso > S.fy.end_date);
  }
  function commitDate() {
    const iso = parseDateInput(dateInput.value, S.fy);
    if (!iso) { toast('日付が不正です', true); dateInput.value = currentDate; dateInput.select(); return false; }
    setDate(iso);
    return true;
  }
  dateInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); if (commitDate()) focusFirstLine(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setDate(addDays(currentDate, 1)); dateInput.select(); }
    else if (e.key === 'ArrowDown') { e.preventDefault(); setDate(addDays(currentDate, -1)); dateInput.select(); }
  });
  dateInput.addEventListener('blur', () => { if (dateInput.value !== currentDate) commitDate(); });
  dateInput.addEventListener('focus', () => selectAllOnFocus(dateInput));
  memoInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); focusFirstLine(); } });

  // ---------------------------------------------------------------- 行
  function accountItems() { return S.accounts.filter(a => a.active); }
  function subItems(accountId) { return accountId ? (S.subsByAccount[accountId] || []).filter(s => s.active) : []; }
  function deptItems() { return S.departments.filter(d => d.active); }

  function taxOptionsHtml() {
    return S.meta.tax_classes.map(t => `<option value="${t.code}">${t.code} ${esc(t.short)}</option>`).join('');
  }

  function defaultTax(drId, crId) {
    const dr = S.accountById[drId], cr = S.accountById[crId];
    const d = dr && dr.default_tax_class !== '00' ? dr.default_tax_class : null;
    const c = cr && cr.default_tax_class !== '00' ? cr.default_tax_class : null;
    if (d && c) {
      // 収益科目が貸方なら売上側、費用科目が借方なら仕入側を優先
      if (cr.category === 'revenue') return c;
      return d;
    }
    return d || c || '00';
  }

  function addLine(data = {}, focus = false) {
    const tr = el(`<tr>
      <td class="rowno"></td>
      <td><input data-f="dr" placeholder="借方科目"></td>
      <td><input data-f="drsub" placeholder="補助"></td>
      ${hasDept ? '<td><input data-f="drdept" placeholder="部門"></td>' : ''}
      <td><input data-f="cr" placeholder="貸方科目"></td>
      <td><input data-f="crsub" placeholder="補助"></td>
      ${hasDept ? '<td><input data-f="crdept" placeholder="部門"></td>' : ''}
      <td><input data-f="amount" class="num" inputmode="numeric"></td>
      ${exempt ? '' : `<td><select data-f="tax">${taxOptionsHtml()}</select></td><td><input data-f="taxamt" class="num" inputmode="numeric"></td>`}
      <td><input data-f="desc" placeholder="摘要"></td>
      <td class="act"><button class="small" tabindex="-1" data-f="del" title="行削除">×</button></td>
    </tr>`);
    tbody.appendChild(tr);
    const f = (name) => tr.querySelector(`[data-f=${name}]`);
    const st = { taxTouched: false, taxAmtTouched: false };
    tr._state = st;

    // 補助科目はカーソルが入った時点で候補を出す。科目コードを打って Enter を押すと
    // ここに移ってくるので、そのまま上下キーと Enter で補助科目を選べる。
    const drSub = makeCombo(f('drsub'), { items: () => subItems(dr.id), openOnFocus: true, onCommit: () => focusNext(f('drsub')) });
    const crSub = makeCombo(f('crsub'), { items: () => subItems(cr.id), openOnFocus: true, onCommit: () => focusNext(f('crsub')) });
    // 空欄のまま Enter を押したら、前の行と同じ科目を入れる。
    // 複合仕訳で片側が同じ科目 (資金諸口など) の行を続けて書くときに打ち直さずに済む。
    // 空のままにしたいときは Enter ではなく Tab で次の欄へ移る。
    const dr = makeCombo(f('dr'), {
      items: accountItems,
      emptyFallback: () => prevAccount(tr, 'dr'),
      onChange: (it) => { drSub.clear(); updateSubState(f('drsub'), it); applyDefaultTax(); },
      onCommit: () => focusNext(f('dr')),
    });
    const cr = makeCombo(f('cr'), {
      items: accountItems,
      emptyFallback: () => prevAccount(tr, 'cr'),
      onChange: (it) => { crSub.clear(); updateSubState(f('crsub'), it); applyDefaultTax(); },
      onCommit: () => focusNext(f('cr')),
    });
    let drDept = null, crDept = null;
    if (hasDept) {
      drDept = makeCombo(f('drdept'), { items: deptItems, onCommit: () => focusNext(f('drdept')) });
      crDept = makeCombo(f('crdept'), { items: deptItems, onCommit: () => focusNext(f('crdept')) });
    }
    tr._combos = { dr, drSub, cr, crSub, drDept, crDept };

    function updateSubState(input, acct) {
      const has = acct && subItems(acct.id).length > 0;
      input.disabled = !has;
      input.placeholder = has ? '補助' : '';
    }
    function applyDefaultTax() {
      if (exempt || st.taxTouched) return;
      f('tax').value = defaultTax(dr.id, cr.id);
      recalcTax();
    }
    function recalcTax() {
      if (exempt) return;
      const t = S.taxById[f('tax').value];
      const amt = parseAmount(f('amount').value);
      const rate = t ? t.rate : 0;
      if (!st.taxAmtTouched) {
        const tax = rate > 0 ? Math.floor(Math.abs(amt) * rate / (100 + rate)) * Math.sign(amt || 1) : 0;
        f('taxamt').value = rate > 0 && amt !== 0 ? fmt(tax) : '';
      }
      f('taxamt').disabled = rate === 0;
      updateTotals();
    }

    const amount = f('amount');
    amount.addEventListener('focus', () => selectAllOnFocus(amount));
    amount.addEventListener('input', () => { updateTotals(); });
    amount.addEventListener('blur', () => { amount.value = amount.value.trim() ? fmt(parseAmount(amount.value)) : ''; recalcTax(); });
    amount.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        if (!amount.value.trim()) {
          const diff = computeTotals().diff;
          if (diff !== 0) amount.value = fmt(Math.abs(diff));
        }
        amount.value = amount.value.trim() ? fmt(parseAmount(amount.value)) : '';
        recalcTax();
        focusNext(amount);
      }
    });
    if (!exempt) {
      const tax = f('tax'), taxamt = f('taxamt');
      tax.addEventListener('change', () => { st.taxTouched = true; st.taxAmtTouched = false; recalcTax(); });
      tax.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); st.taxTouched = true; recalcTax(); focusNext(tax); }
      });
      taxamt.addEventListener('focus', () => selectAllOnFocus(taxamt));
      taxamt.addEventListener('input', () => { st.taxAmtTouched = true; });
      taxamt.addEventListener('blur', () => { taxamt.value = taxamt.value.trim() ? fmt(parseAmount(taxamt.value)) : ''; });
      taxamt.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); taxamt.value = taxamt.value.trim() ? fmt(parseAmount(taxamt.value)) : ''; focusNext(taxamt); }
      });
    }
    const desc = f('desc');
    // 摘要はプリセットから選べるが、候補に無い文字列もそのまま入力できる
    const descSuggest = makeSuggest(desc, {
      items: () => S.descriptionItems,
      accountIds: () => [dr.id, cr.id],
    });
    tr._descSuggest = descSuggest;
    desc.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        descSuggest.resolve();       // 候補を選んでいれば本文に、コード入力なら展開
        const rows = $$('tr', tbody);
        if (tr !== rows[rows.length - 1]) { focusNext(desc); return; }
        const t = computeTotals();
        // 貸借が合っていても、資金諸口が釣り合っていなければ続きがあるとみて行を足す
        if (t.dr > 0 && t.diff === 0 && suspenseTotals().diff === 0) save();
        else { addLine({}, true); }
      } else if (e.key === 'F4') {
        e.preventDefault();
        descSuggest.open();
      }
    });
    f('del').addEventListener('click', () => removeLine(tr));

    // 初期値
    if (data.debit_account_id) { dr.set(data.debit_account_id); updateSubState(f('drsub'), S.accountById[data.debit_account_id]); }
    else updateSubState(f('drsub'), null);
    if (data.debit_sub_id) drSub.set(data.debit_sub_id);
    if (data.credit_account_id) { cr.set(data.credit_account_id); updateSubState(f('crsub'), S.accountById[data.credit_account_id]); }
    else updateSubState(f('crsub'), null);
    if (data.credit_sub_id) crSub.set(data.credit_sub_id);
    if (hasDept) {
      if (data.debit_dept_id) drDept.set(data.debit_dept_id);
      if (data.credit_dept_id) crDept.set(data.credit_dept_id);
    }
    if (data.amount) amount.value = fmt(data.amount);
    if (!exempt) {
      if (data.tax_class) { f('tax').value = data.tax_class; st.taxTouched = true; }
      else f('tax').value = defaultTax(dr.id, cr.id);
      if (data.tax_amount !== undefined && data.tax_amount !== null && data.tax_class) {
        const t = S.taxById[data.tax_class];
        const auto = t && t.rate > 0 ? Math.floor(Math.abs(data.amount || 0) * t.rate / (100 + t.rate)) : 0;
        st.taxAmtTouched = data.tax_amount !== auto;
        f('taxamt').value = t && t.rate > 0 ? fmt(data.tax_amount) : '';
        f('taxamt').disabled = !(t && t.rate > 0);
      } else recalcTax();
    }
    if (data.description) desc.value = data.description;
    renumber();
    updateTotals();
    if (focus) f('dr').focus();
    return tr;
  }

  /** この行より上で、同じ欄に最後に入っている科目を返す。無ければ null。 */
  function prevAccount(tr, field) {
    for (let p = tr.previousElementSibling; p; p = p.previousElementSibling) {
      const combo = p._combos && p._combos[field];
      const id = combo && combo.id;
      if (id && S.accountById[id]) return S.accountById[id];
    }
    return null;
  }

  function removeLine(tr) {
    const rows = $$('tr', tbody);
    if (rows.length <= 1) { clearLine(tr); return; }
    const idx = rows.indexOf(tr);
    tr.remove();
    renumber();
    updateTotals();
    const rest = $$('tr', tbody);
    const target = rest[Math.min(idx, rest.length - 1)];
    if (target) target.querySelector('[data-f=dr]').focus();
  }
  function clearLine(tr) {
    const c = tr._combos;
    c.dr.clear(); c.cr.clear(); c.drSub.clear(); c.crSub.clear();
    if (c.drDept) { c.drDept.clear(); c.crDept.clear(); }
    tr.querySelector('[data-f=drsub]').disabled = true;
    tr.querySelector('[data-f=crsub]').disabled = true;
    tr.querySelector('[data-f=amount]').value = '';
    if (!exempt) { tr.querySelector('[data-f=tax]').value = '00'; tr.querySelector('[data-f=taxamt]').value = ''; tr.querySelector('[data-f=taxamt]').disabled = true; }
    tr.querySelector('[data-f=desc]').value = '';
    tr._state.taxTouched = false; tr._state.taxAmtTouched = false;
    updateTotals();
  }
  function renumber() { $$('tr', tbody).forEach((tr, i) => { tr.querySelector('.rowno').textContent = i + 1; }); }

  function lineData(tr) {
    const c = tr._combos;
    const f = (n) => tr.querySelector(`[data-f=${n}]`);
    const amt = parseAmount(f('amount').value);
    const taxCls = exempt ? '00' : f('tax').value;
    const t = S.taxById[taxCls];
    const empty = !c.dr.id && !c.cr.id && amt === 0 && !f('desc').value.trim();
    return {
      empty,
      debit_account_id: c.dr.id, debit_sub_id: c.drSub.id, debit_dept_id: c.drDept ? c.drDept.id : null,
      credit_account_id: c.cr.id, credit_sub_id: c.crSub.id, credit_dept_id: c.crDept ? c.crDept.id : null,
      amount: amt, tax_class: taxCls,
      tax_amount: (!exempt && t && t.rate > 0) ? (tr._state.taxAmtTouched ? parseAmount(f('taxamt').value) : null) : 0,
      description: f('desc').value.trim(),
    };
  }
  /** いまの入力内容を、比較できる形にまとめる。
   *  空の行は数えない (行を足しただけで「変更あり」にしないため)。 */
  function snapshot() {
    const lines = [];
    for (const tr of $$('tr', tbody)) {
      const { empty, ...l } = lineData(tr);
      if (!empty) lines.push(l);
    }
    return JSON.stringify([currentDate, memoInput.value.trim(), lines]);
  }
  function markSaved() { typed = false; baseline = snapshot(); }

  /** 資金諸口の科目 (役割が「諸口」、または名称が資金諸口・諸口)。 */
  function suspenseIds() {
    return new Set(S.accounts
      .filter(a => a.role === 'suspense' || a.name === '資金諸口' || a.name === '諸口')
      .map(a => a.id));
  }

  /** この伝票の中で、資金諸口が借方・貸方で釣り合っているかを集計する。
   *  資金諸口は 1 つの取引の中で通過させる科目なので、伝票ごとに借方と貸方が
   *  同額になっていなければ、どこかの行が抜けているか金額が違う。 */
  function suspenseTotals() {
    const ids = suspenseIds();
    let debit = 0, credit = 0, used = false;
    if (ids.size) {
      for (const tr of $$('tr', tbody)) {
        const l = lineData(tr);
        if (l.empty) continue;
        if (ids.has(l.debit_account_id)) { debit += l.amount; used = true; }
        if (ids.has(l.credit_account_id)) { credit += l.amount; used = true; }
      }
    }
    return { debit, credit, diff: debit - credit, used };
  }

  function computeTotals() {
    let dr = 0, cr = 0;
    for (const tr of $$('tr', tbody)) {
      const l = lineData(tr);
      if (l.debit_account_id) dr += l.amount;
      if (l.credit_account_id) cr += l.amount;
    }
    return { dr, cr, diff: dr - cr };
  }
  function updateTotals() {
    const t = computeTotals();
    q('#t-dr').textContent = fmt(t.dr);
    q('#t-cr').textContent = fmt(t.cr);
    const d = q('#t-diff');
    d.textContent = fmt(t.diff);
    d.className = 'diff ' + (t.diff === 0 ? 'ok' : 'ng');
    // 資金諸口は使っている伝票でだけ出す
    const sp = suspenseTotals();
    q('#t-suspense').hidden = !sp.used;
    if (sp.used) {
      q('#t-sdr').textContent = fmt(sp.debit);
      q('#t-scr').textContent = fmt(sp.credit);
      const sd = q('#t-sdiff');
      sd.textContent = fmt(sp.diff);
      sd.className = 'diff ' + (sp.diff === 0 ? 'ok' : 'ng');
    }
  }

  // ---------------------------------------------------------------- フォーカス移動
  function fieldList() {
    return $$('input:not([disabled]), select:not([disabled])', tbody).filter(x => x.dataset.f && x.dataset.f !== 'del');
  }
  function focusNext(cur) {
    const list = fieldList();
    const i = list.indexOf(cur);
    let next = list[i + 1];
    // 税区分の税率 0 の場合は税額欄をスキップ (disabled なのでリストに含まれない)
    if (next) next.focus();
    else { const rows = $$('tr', tbody); if (rows.length) addLine({}, true); }
  }
  function focusPrev(cur) {
    const list = fieldList();
    const i = list.indexOf(cur);
    if (i > 0) list[i - 1].focus(); else dateInput.focus();
  }
  function focusFirstLine() {
    const first = tbody.querySelector('[data-f=dr]');
    if (first) first.focus();
  }
  tbody.addEventListener('keydown', (e) => {
    const t = e.target;
    if (!t.dataset || !t.dataset.f) return;
    if (e.key === 'Enter' && e.shiftKey) { e.preventDefault(); e.stopPropagation(); focusPrev(t); return; }
    if (e.key === 'Enter' && !e.ctrlKey && t.dataset.f === 'desc') return; // desc 側で処理
    if (e.key === 'Delete' && e.ctrlKey) { e.preventDefault(); removeLine(t.closest('tr')); }
  }, true);

  // ---------------------------------------------------------------- 保存 / クリア / 編集
  function resetForm(keepDate = true) {
    editingId = null; editingVno = null;
    tbody.innerHTML = '';
    memoInput.value = '';
    q('#e-vno').value = '';
    q('#e-status').innerHTML = '';
    q('#e-delete').style.display = 'none';
    addLine({});
    if (!keepDate) setDate(S.fy.start_date);
    updateTotals();
    markSaved();
  }
  /** 入力途中の文字を確定する。画面の表示と、保存される内容を一致させる。
   *
   *  科目などの欄は「選んだ項目の id」を文字とは別に持っている。Enter を押さずに
   *  保存や別の伝票への移動をすると、打った文字が確定されないまま前の科目で
   *  保存されてしまうため、保存の直前にここで確定させる。
   */
  function commitPendingInput() {
    const rows = $$('tr', tbody);
    for (let i = 0; i < rows.length; i++) {
      const tr = rows[i];
      const c = tr._combos;
      const targets = [['借方科目', c.dr], ['借方補助', c.drSub], ['貸方科目', c.cr], ['貸方補助', c.crSub]];
      if (c.drDept) targets.push(['借方部門', c.drDept], ['貸方部門', c.crDept]);
      for (const [label, combo] of targets) {
        if (!combo || combo.commitText()) continue;
        toast(`${i + 1} 行目: ${label}「${combo.input.value.trim()}」が見つかりません`, true);
        combo.input.focus();
        return false;
      }
      if (tr._descSuggest) tr._descSuggest.resolve();   // 摘要のコード入力を本文に展開する
      const amt = tr.querySelector('[data-f=amount]');
      if (amt) amt.value = amt.value.trim() ? fmt(parseAmount(amt.value)) : '';
    }
    updateTotals();
    return true;
  }

  /** 保存する。成功したら true、入力の不備などで保存できなければ false。 */
  async function save() {
    if (!commitDate()) return false;
    if (!commitPendingInput()) return false;
    const lines = $$('tr', tbody).map(lineData).filter(l => !l.empty);
    if (!lines.length) { toast('仕訳行を入力してください', true); focusFirstLine(); return false; }
    const sp = suspenseTotals();
    if (sp.diff !== 0) {
      toast(`資金諸口の貸借が一致しません (借方 ${fmt(sp.debit)} / 貸方 ${fmt(sp.credit)} / 差額 ${fmt(sp.diff)})`, true);
      return false;
    }
    const payload = { entry_date: currentDate, memo: memoInput.value.trim(), lines: lines.map(({ empty, ...l }) => l) };
    const saveBtn = q('#e-save');
    saveBtn.disabled = true;
    try {
      let res;
      if (editingId) {
        payload.voucher_no = editingVno;
        res = await PUT(`/api/entries/${editingId}`, payload);
        toast(`伝票 No.${res.voucher_no} を修正しました`);
      } else {
        res = await POST(`/api/clients/${S.client.id}/entries`, payload);
        toast(`伝票 No.${res.voucher_no} を登録しました`);
      }
      lastSaved = res;
      markSaved();
      if (!inDialog) {
        resetForm(true);
        dateInput.focus();
      }
      await onChanged(res);
      return true;
    } catch (e) { showError(e); return false; }
    finally { saveBtn.disabled = false; }
  }
  function loadEntry(entry) {
    tbody.innerHTML = '';
    editingId = entry.id; editingVno = entry.voucher_no;
    setDate(entry.entry_date);
    memoInput.value = entry.memo || '';
    q('#e-vno').value = entry.voucher_no;
    for (const l of entry.lines) addLine(l);
    q('#e-status').innerHTML = inDialog ? ''
      : `<span class="editing">修正中: 伝票 No.${entry.voucher_no}</span> <button class="small" id="e-cancel-edit">新規入力に戻る</button>`;
    if (q('#e-cancel-edit')) q('#e-cancel-edit').onclick = () => { resetForm(true); dateInput.focus(); };
    q('#e-delete').style.display = '';
    updateTotals();
    focusFirstLine();
    markSaved();
    if (!inDialog) window.scrollTo({ top: 0 });
  }
  function copyEntry(entry) {
    const wasEditing = editingId;
    tbody.innerHTML = '';
    editingId = null; editingVno = null;
    q('#e-vno').value = '';
    q('#e-status').innerHTML = wasEditing ? '' : '<span class="muted">前伝票を複写しました</span>';
    q('#e-delete').style.display = 'none';
    memoInput.value = entry.memo || '';
    for (const l of entry.lines) addLine(l);
    updateTotals();
    focusFirstLine();
  }
  async function deleteEntry(id, vno) {
    if (!(await confirmDialog(`伝票 No.${vno} を削除します。よろしいですか？`))) return;
    try {
      await DEL(`/api/entries/${id}`);
      toast(`伝票 No.${vno} を削除しました`);
      if (!inDialog && editingId === id) resetForm(true);
      await onChanged();
    } catch (e) { showError(e); }
  }

  q('#e-save').onclick = save;
  if (q('#e-clear')) q('#e-clear').onclick = () => { resetForm(true); dateInput.focus(); };
  q('#e-addrow').onclick = () => addLine({}, true);
  q('#e-delete').onclick = () => { if (editingId) deleteEntry(editingId, editingVno); };
  q('#e-template').onclick = openTemplatePicker;
  q('#e-tosave').onclick = saveAsTemplate;
  if (q('#e-copy')) q('#e-copy').onclick = copyLast;

  async function copyLast() {
    let src = lastSaved;
    if (!src) {
      const r = await GET(`/api/clients/${S.client.id}/entries?fiscal_year_id=${S.fy.id}&limit=5000`);
      src = r.entries[r.entries.length - 1];
    }
    if (!src) { toast('複写できる伝票がありません', true); return; }
    copyEntry(src);
  }

  // ---------------------------------------------------------------- 定型登録
  /** いま入力されている伝票を、そのまま定型仕訳として登録する。 */
  function saveAsTemplate() {
    const lines = $$('tr', tbody).map(lineData).filter(l => !l.empty);
    if (!lines.length) { toast('先に仕訳を入力してください', true); focusFirstLine(); return; }
    const used = new Set(S.templates.map(t => t.code));
    let n = 1;
    while (used.has(String(n))) n++;
    const suggested = lines.find(l => l.description) ? lines.find(l => l.description).description : '';
    formModal('定型仕訳に登録',
      field('コード', textInput('code', String(n), 'required maxlength="10"')) +
      field('名称', textInput('name', suggested, 'required')) +
      `<div class="field wide"><span>登録する内容</span><div class="muted">${lines.length} 行 / 借方合計 ${
        fmt(lines.filter(l => l.debit_account_id).reduce((a, l) => a + l.amount, 0))} 円${
        memoInput.value.trim() ? ` / 伝票メモ「${esc(memoInput.value.trim())}」` : ''}</div></div>`,
      async (d) => {
        await POST(`/api/clients/${S.client.id}/templates`, {
          code: d.code.trim(), name: d.name.trim(), memo: memoInput.value.trim(),
          lines: lines.map(({ empty, tax_amount, ...l }) => l),
        });
        await loadTemplates();
        toast(`定型仕訳「${d.name.trim()}」に登録しました`);
      }, { submitLabel: '登録' });
  }

  // ---------------------------------------------------------------- 定型仕訳
  function openTemplatePicker() {
    if (!S.templates.length) { toast('定型仕訳が登録されていません (定型仕訳メニューから登録できます)', true); return; }
    const active = document.activeElement;
    const curTr = active && active.closest ? active.closest('tr') : null;
    let items = S.templates;
    const { bg, close } = modal(`<h3>定型仕訳</h3>
      <input id="tp-q" placeholder="コード・名称で検索" style="width:100%">
      <div style="max-height:50vh;overflow:auto;margin-top:8px"><table class="grid compact"><thead><tr><th>コード</th><th>名称</th><th>借方</th><th>貸方</th><th>金額</th><th>摘要</th></tr></thead>
      <tbody id="tp-body"></tbody></table></div>
      <div class="actions"><span class="muted" style="margin-right:auto"><kbd>↑↓</kbd> 選択 <kbd>Enter</kbd> 適用</span><button data-close>閉じる</button></div>`, {
      onOpen(bg) {
        const qi = $('#tp-q', bg), body = $('#tp-body', bg);
        let hl = 0;
        const draw = () => {
          const sum = (t, k) => (t.lines || []).reduce((n, l) => n + (l[k] || 0), 0);
          const label = (t, side) => {
            const names = [...new Set((t.lines || []).map(l => acctLabel(l[side + '_account_id'])).filter(Boolean))];
            return names.length > 1 ? names[0] + ` 他${names.length - 1}` : (names[0] || '');
          };
          body.innerHTML = items.map((t, i) => `<tr data-i="${i}" class="clickable ${i === hl ? 'hl' : ''}">
            <td class="code">${esc(t.code)}</td><td>${esc(t.name)}${(t.lines || []).length > 1 ? ` <span class="badge">${t.lines.length} 行</span>` : ''}</td>
            <td>${esc(label(t, 'debit'))}</td><td>${esc(label(t, 'credit'))}</td>
            <td class="num">${sum(t, 'amount') ? fmt(sum(t, 'amount')) : ''}</td>
            <td>${esc(((t.lines || []).find(l => l.description) || {}).description || '')}</td></tr>`).join('');
        };
        const apply = (t) => {
          close();
          // 空の行があれば、そこから置き換える (呼び出し先の行を無駄に残さない)
          let tr = curTr && tbody.contains(curTr) && lineData(curTr).empty ? curTr : null;
          if (!tr) {
            const rows = $$('tr', tbody);
            const last = rows[rows.length - 1];
            tr = last && lineData(last).empty ? last : null;
          }
          if (tr) tr.remove();
          if (t.memo && !memoInput.value.trim()) memoInput.value = t.memo;
          let first = null;
          for (const l of (t.lines && t.lines.length ? t.lines : [{}])) {
            const ntr = addLine({
              debit_account_id: l.debit_account_id, debit_sub_id: l.debit_sub_id, debit_dept_id: l.debit_dept_id,
              credit_account_id: l.credit_account_id, credit_sub_id: l.credit_sub_id, credit_dept_id: l.credit_dept_id,
              amount: l.amount || 0, tax_class: l.tax_class || undefined, description: l.description,
            });
            if (!l.tax_class) ntr._state.taxTouched = false;
            if (!first) first = ntr;
          }
          renumber();
          updateTotals();
          if (first) first.querySelector('[data-f=amount]').focus();
        };
        qi.oninput = () => {
          const s = qi.value.trim().toLowerCase();
          items = S.templates.filter(t => !s || t.code.toLowerCase().includes(s) || t.name.toLowerCase().includes(s) || (t.description || '').toLowerCase().includes(s));
          hl = 0; draw();
        };
        qi.onkeydown = (e) => {
          if (e.key === 'ArrowDown') { hl = Math.min(hl + 1, items.length - 1); draw(); e.preventDefault(); }
          else if (e.key === 'ArrowUp') { hl = Math.max(hl - 1, 0); draw(); e.preventDefault(); }
          else if (e.key === 'Enter') { e.preventDefault(); if (items[hl]) apply(items[hl]); }
        };
        body.onclick = (e) => { const r = e.target.closest('tr'); if (r) apply(items[Number(r.dataset.i)]); };
        draw();
        qi.focus();
      },
    });
  }

  // ---------------------------------------------------------------- グローバルキー
  /** 手前に出ているダイアログだけがキー操作を受ける。
   *  画面に置いたフォームは、ダイアログが開いている間は受け取らない。 */
  function keysActive() {
    const modals = $$('.modal-bg');
    const top = modals.length ? modals[modals.length - 1] : null;
    return inDialog ? !!(top && top.contains(root)) : !top;
  }

  // Shift を単独で押して離したら行追加。他のキーと組み合わせた場合 (Shift+Enter など) は何もしない。
  // 入力欄が Enter の伝播を止めることがあるため、押されたキーの見張りは捕捉段階 (capture) で行う。
  let shiftTap = 0;               // Shift を押した時刻。0 なら単独押しではない
  const SHIFT_TAP_MS = 700;       // これより長く押していたら、押しっぱなしとみなして無視する

  const onAnyKeyDown = (e) => {
    if (e.key !== 'Shift') { shiftTap = 0; return; }   // 他のキーと一緒に押したので単独押しではない
    if (!e.repeat && !e.ctrlKey && !e.altKey && !e.metaKey && keysActive()) shiftTap = Date.now();
  };
  const onKeyUp = (e) => {
    if (e.key !== 'Shift') return;
    const started = shiftTap;
    shiftTap = 0;
    if (!started || Date.now() - started > SHIFT_TAP_MS) return;
    if (!keysActive() || e.ctrlKey || e.altKey || e.metaKey) return;
    // 候補一覧が開いていても行を足す。摘要を打った直後は候補が開いたままで、
    // そこが一番行を足したい場面のため。入力中の内容は欄から離れる時に確定される。
    e.preventDefault();
    addLine({}, true);
  };

  const onKey = (e) => {
    if (!keysActive()) return;
    if (e.key === 'Enter' && e.ctrlKey) { e.preventDefault(); save(); }
    else if (e.key === 'Escape') {
      if (inDialog) return;     // ダイアログはダイアログ側が閉じる
      if (!document.querySelector('.combo .dropdown.open')) { e.preventDefault(); resetForm(true); dateInput.focus(); }
    } else if (e.key === 'Insert' && e.ctrlKey) { e.preventDefault(); addLine({}, true); }
    else if (e.key === 'F2') { e.preventDefault(); openTemplatePicker(); }
    else if (e.key === 'F3') { e.preventDefault(); saveAsTemplate(); }
    else if (e.key === 'F5' && !inDialog) { e.preventDefault(); copyLast(); }
  };
  // Shift を押しながらのマウス操作も、単独押しではない
  const onDown = () => { shiftTap = 0; };
  document.addEventListener('keydown', onAnyKeyDown, true);
  document.addEventListener('keyup', onKeyUp, true);
  document.addEventListener('keydown', onKey);
  document.addEventListener('mousedown', onDown);

  setDate(currentDate);
  resetForm(true);

  return {
    loadEntry, copyEntry, resetForm, save, deleteEntry, setDate, focusDate: () => dateInput.focus(),
    get editingId() { return editingId; },
    get currentDate() { return currentDate; },
    // 手で打った文字があるか、読み込んだ時点から内容が変わっていれば「未保存」。
    // 定型仕訳の適用・行の追加や削除・候補からの選択も、内容の比較で拾える。
    get isDirty() { return typed || snapshot() !== baseline; },
    destroy() {
      document.removeEventListener('keydown', onAnyKeyDown, true);
      document.removeEventListener('keyup', onKeyUp, true);
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('mousedown', onDown);
    },
  };
}

/** 帳票の行から、その伝票を直接修正するダイアログを開く。 */
/** 帳票の行から、その伝票を直接修正するダイアログを開く。
 *
 *  siblings に帳票が今出している伝票 id を渡しておくと、ダイアログの中で
 *  前後の仕訳へ移れる。摘要で絞り込んでまとめて直すときに、いちいち
 *  閉じて次の行をクリックしなくて済む。
 */
async function openEntryDialog(entryId, { onChanged, siblings } = {}) {
  if (S.fy && S.fy.closed) { toast('この会計期間は締め切られています', true); return; }
  // 同じ伝票が複数行に出る帳票もあるので、重複は取り除いて順序だけ残す
  const list = [...new Set((siblings && siblings.length ? siblings : [entryId]).map(Number))];
  let idx = list.indexOf(Number(entryId));
  if (idx < 0) { list.unshift(Number(entryId)); idx = 0; }

  let form = null;
  let closeModal = null;
  let pendingTarget = null;     // 保存が終わったら移りたい行 (前後ボタンで使う)
  let closingNow = false;       // 閉じる途中 (保存しても次の仕訳へ進まない)
  let discard = false;          // 「破棄して閉じる」を押した
  const multi = list.length > 1;

  const { bg, close } = modal(`<div style="width:min(1180px, 90vw)">
    <div class="row between" style="align-items:baseline;margin-bottom:8px">
      <h3 style="margin:0">仕訳の修正　<span class="muted" style="font-weight:normal" id="ed-sub"></span></h3>
      ${multi ? `<div class="row" style="gap:6px">
        <span class="muted" id="ed-pos"></span>
        <button id="ed-prev">◀ 前の仕訳 <kbd>PageUp</kbd></button>
        <button id="ed-next">次の仕訳 ▶ <kbd>PageDown</kbd></button></div>` : ''}
    </div>
    <div id="ed-host"></div>
    <div class="actions">
      <span class="muted" style="margin-right:auto">直した内容は、閉じるときも${multi ? '前後へ移るときも' : ''}保存されます</span>
      <button id="ed-discard" class="danger">変更を破棄して閉じる</button>
      <button data-close>閉じる</button></div>
    <div class="entry-dialog-space"></div>
  </div>`, {
    onOpen(bg, doClose) {
      closeModal = doClose;
      form = createEntryForm($('#ed-host', bg), {
        inDialog: true,
        async onChanged() {
          if (onChanged) await onChanged();      // 呼び出した帳票を引き直す
          if (closingNow) return;                // 閉じるための保存なので、次へは進まない
          // 保存後に移る先。前後ボタンで保存した場合はその行、ふつうに保存したら次の行
          const target = pendingTarget !== null ? pendingTarget : idx + 1;
          pendingTarget = null;
          if (!(await load(target))) doClose();  // 行き先が無ければ閉じる
        },
      });
      if (multi) {
        $('#ed-prev', bg).onclick = () => go(-1);
        $('#ed-next', bg).onclick = () => go(1);
      }
      $('#ed-discard', bg).onclick = () => { discard = true; doClose(); };
    },
    // Esc や「閉じる」で直した内容が消えないよう、閉じる前に保存する。
    // 保存できない状態 (貸借不一致など) のときは閉じずに留まる。
    async beforeClose() {
      if (discard || !form || !form.isDirty) return true;
      closingNow = true;
      const ok = await form.save();
      closingNow = false;
      return ok;
    },
    onClose() {
      document.removeEventListener('keydown', onNavKey);
      if (form) form.destroy();
    },
  });

  /** i 番目の伝票を読み込む。もう無ければ false。 */
  async function load(i) {
    while (i >= 0 && i < list.length) {
      let entry;
      try {
        entry = await GET(`/api/entries/${list[i]}`);
      } catch (e) {
        list.splice(i, 1);        // 削除済みなどで読めない伝票は一覧から外して次へ
        continue;
      }
      idx = i;
      form.loadEntry(entry);
      $('#ed-sub', bg).textContent = `伝票 No.${entry.voucher_no}　${fmtDate(entry.entry_date)}`;
      if (multi) {
        $('#ed-pos', bg).textContent = `${idx + 1} / ${list.length} 件`;
        $('#ed-prev', bg).disabled = idx === 0;
        $('#ed-next', bg).disabled = idx >= list.length - 1;
      }
      return true;
    }
    return false;
  }

  async function go(delta) {
    const next = idx + delta;
    if (next < 0 || next >= list.length) return;
    if (form.isDirty) {
      // 直しかけのまま移ると修正が消えてしまうので、先に保存する。
      // 保存できなければ (貸借不一致など) その場に留まる。
      pendingTarget = next;
      if (!(await form.save())) pendingTarget = null;
      return;                       // 保存が通れば onChanged 側で移動する
    }
    await load(next);
  }

  const onNavKey = (e) => {
    if (e.key !== 'PageDown' && e.key !== 'PageUp') return;
    const modals = $$('.modal-bg');
    if (modals[modals.length - 1] !== bg) return;   // 手前に別のダイアログがある
    e.preventDefault();
    go(e.key === 'PageDown' ? 1 : -1);
  };
  if (multi) document.addEventListener('keydown', onNavKey);

  if (!(await load(idx))) { close(); toast('仕訳が見つかりません', true); }
  return { bg, close };
}

// ---------------------------------------------------------------- 仕訳入力画面
routes.entry = async function (main, params) {
  const exempt = isExempt();
  let listMode = localStorage.getItem('entryListMode') || 'date';

  main.innerHTML = `<div id="entry-host"></div>
  <div class="panel">
    <div class="row between">
      <h3 style="margin:0">登録済み仕訳</h3>
      <div class="row">
        <select id="list-mode">
          <option value="date">入力日付の仕訳</option>
          <option value="recent">直近 50 件</option>
          <option value="month">入力月の仕訳</option>
        </select>
        <span id="list-summary" class="muted"></span>
      </div>
    </div>
    <div class="scroll-x"><table class="grid compact" id="e-list"><thead><tr>
      <th>日付</th><th>No</th><th>借方科目</th><th>借方補助</th><th>貸方科目</th><th>貸方補助</th><th>金額</th>${exempt ? '' : '<th>税</th>'}<th>摘要</th><th></th>
    </tr></thead><tbody></tbody></table></div>
  </div>`;

  const form = createEntryForm($('#entry-host'), { onChanged: () => loadList() });

  // ---------------------------------------------------------------- 一覧
  async function loadList() {
    const qs = new URLSearchParams({ fiscal_year_id: S.fy.id });
    const currentDate = form.currentDate;
    if (listMode === 'date') { qs.set('date_from', currentDate); qs.set('date_to', currentDate); }
    else if (listMode === 'month') { qs.set('date_from', currentDate.slice(0, 7) + '-01'); qs.set('date_to', currentDate.slice(0, 7) + '-31'); }
    else { qs.set('limit', 5000); }
    const r = await GET(`/api/clients/${S.client.id}/entries?${qs}`);
    let entries = r.entries;
    if (listMode === 'recent') entries = entries.slice(-50);
    const body = $('#e-list tbody');
    const rows = [];
    let total = 0;
    for (const e of (listMode === 'recent' ? entries.slice().reverse() : entries)) {
      e.lines.forEach((l, i) => {
        if (l.debit_account_id) total += l.amount;
        rows.push(`<tr class="clickable" data-id="${e.id}">
          <td class="code">${i === 0 ? fmtDate(e.entry_date) : ''}</td><td class="num">${i === 0 ? e.voucher_no : ''}</td>
          <td>${l.debit_code ? esc(l.debit_code + ' ' + l.debit_name) : '<span class="muted">諸口</span>'}</td><td>${esc(l.debit_sub_name || '')}</td>
          <td>${l.credit_code ? esc(l.credit_code + ' ' + l.credit_name) : '<span class="muted">諸口</span>'}</td><td>${esc(l.credit_sub_name || '')}</td>
          <td class="num">${fmt(l.amount)}</td>${exempt ? '' : `<td class="code" title="${esc(taxName(l.tax_class))}">${l.tax_class !== '00' ? esc(taxShort(l.tax_class)) : ''}</td>`}
          <td>${esc(l.description)}${e.memo && i === 0 ? ` <span class="memo">[${esc(e.memo)}]</span>` : ''}</td>
          <td class="center" style="white-space:nowrap">${i === 0 ? `<button class="small" data-edit="${e.id}">修正</button> <button class="small danger" data-del="${e.id}" data-vno="${e.voucher_no}">削除</button>` : ''}</td>
        </tr>`);
      });
    }
    body.innerHTML = rows.join('') || `<tr><td colspan="10" class="empty">仕訳がありません</td></tr>`;
    $('#list-summary').textContent = `${entries.length} 伝票 / 合計 ${fmt(total)} 円`;
    body.onclick = async (e) => {
      const ed = e.target.closest('[data-edit]');
      const dl = e.target.closest('[data-del]');
      if (dl) { form.deleteEntry(Number(dl.dataset.del), dl.dataset.vno); return; }
      const tr = e.target.closest('tr[data-id]');
      if (!tr) return;
      const id = ed ? Number(ed.dataset.edit) : Number(tr.dataset.id);
      if (form.isDirty && id !== form.editingId) {
        if (form.editingId) {
          // 修正中の伝票を直しかけのまま置き去りにしない
          if (!(await form.save())) return;
        } else if (!(await confirmDialog('入力中の仕訳が消えます。よろしいですか？'))) {
          return;
        }
      }
      try { form.loadEntry(await GET(`/api/entries/${id}`)); } catch (err) { showError(err); }
    };
  }
  $('#list-mode').value = listMode;
  $('#list-mode').onchange = (e) => { listMode = e.target.value; localStorage.setItem('entryListMode', listMode); loadList(); };
  $('#e-date').addEventListener('change', () => { if (listMode !== 'recent') loadList(); });

  // ---------------------------------------------------------------- 初期化
  if (params.entry) {
    try { form.loadEntry(await GET(`/api/entries/${params.entry}`)); } catch (e) { showError(e); }
  } else {
    form.focusDate();
  }
  await loadList();
  $('#header-hint').textContent = S.fy.closed ? 'この会計期間は締め切られています (入力不可)' : '';

  return () => { form.destroy(); $('#header-hint').textContent = ''; };
};
