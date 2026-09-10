/* 仕訳入力画面 */
'use strict';

routes.entry = async function (main, params) {
  const hasDept = S.departments.some(d => d.active);
  const exempt = isExempt();
  let editingId = null;      // 修正中の伝票 id
  let editingVno = null;
  let listMode = localStorage.getItem('entryListMode') || 'date';
  let lastSaved = null;

  main.innerHTML = `
  <div class="panel" id="entry-form">
    <div class="head">
      <div class="field"><span>日付 (月日 例: 0401)</span>
        <div class="row" style="gap:6px"><input id="e-date" class="mono" style="width:120px"><span id="e-date-disp" class="muted"></span></div></div>
      <div class="field"><span>伝票No</span><input id="e-vno" class="num" style="width:70px" readonly></div>
      <div class="field"><span>伝票メモ</span><input id="e-memo" style="width:200px"></div>
      <button id="e-template" title="定型仕訳を呼び出す">定型仕訳 <kbd>F2</kbd></button>
      <button id="e-copy" title="直前に登録した伝票を複写">前伝票複写 <kbd>F5</kbd></button>
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
      <div class="totals">借方 <b id="t-dr">0</b>　貸方 <b id="t-cr">0</b>　差額 <b id="t-diff" class="diff">0</b></div>
      <div class="actions">
        <button id="e-addrow">行追加 <kbd>Ctrl+Ins</kbd></button>
        <button id="e-clear">クリア <kbd>Esc</kbd></button>
        <button id="e-delete" class="danger" style="display:none">この伝票を削除</button>
        <button id="e-save" class="primary">登録 <kbd>Ctrl+Enter</kbd></button>
      </div>
    </div>
    <div class="help">
      <kbd>Enter</kbd> 次の項目 / <kbd>Shift+Enter</kbd> 前の項目 / 科目はコード・かな・名称で検索 <kbd>↑↓</kbd> で選択 /
      金額欄で空欄のまま <kbd>Enter</kbd> → 差額を入力 / 摘要欄で <kbd>Enter</kbd> → 貸借一致なら登録、不一致なら行追加 / <kbd>Ctrl+Del</kbd> 行削除 / 摘要は <kbd>F4</kbd> または入力で候補表示、コード入力 + <kbd>Enter</kbd> で展開
    </div>
  </div>
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

  const tbody = $('#e-lines');
  const dateInput = $('#e-date');
  const memoInput = $('#e-memo');
  let currentDate = sessionStorage.getItem('entryDate:' + S.fy.id) || (S.fy.start_date <= today() && today() <= S.fy.end_date ? today() : S.fy.start_date);

  // ---------------------------------------------------------------- 日付
  function setDate(iso) {
    currentDate = iso;
    dateInput.value = iso;
    $('#e-date-disp').textContent = fmtDate(iso).slice(0) + ' ' + ['日', '月', '火', '水', '木', '金', '土'][new Date(iso).getDay()];
    sessionStorage.setItem('entryDate:' + S.fy.id, iso);
    $('#e-date-disp').classList.toggle('neg', iso < S.fy.start_date || iso > S.fy.end_date);
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

    const drSub = makeCombo(f('drsub'), { items: () => subItems(dr.id), onCommit: () => focusNext(f('drsub')) });
    const crSub = makeCombo(f('crsub'), { items: () => subItems(cr.id), onCommit: () => focusNext(f('crsub')) });
    const dr = makeCombo(f('dr'), {
      items: accountItems,
      onChange: (it) => { drSub.clear(); updateSubState(f('drsub'), it); applyDefaultTax(); },
      onCommit: () => focusNext(f('dr')),
    });
    const cr = makeCombo(f('cr'), {
      items: accountItems,
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
        if (t.dr > 0 && t.diff === 0) save();
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
    $('#t-dr').textContent = fmt(t.dr);
    $('#t-cr').textContent = fmt(t.cr);
    const d = $('#t-diff');
    d.textContent = fmt(t.diff);
    d.className = 'diff ' + (t.diff === 0 ? 'ok' : 'ng');
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
    $('#e-vno').value = '';
    $('#e-status').innerHTML = '';
    $('#e-delete').style.display = 'none';
    addLine({});
    if (!keepDate) setDate(S.fy.start_date);
    updateTotals();
  }
  async function save() {
    if (!commitDate()) return;
    const lines = $$('tr', tbody).map(lineData).filter(l => !l.empty);
    if (!lines.length) { toast('仕訳行を入力してください', true); focusFirstLine(); return; }
    const payload = { entry_date: currentDate, memo: memoInput.value.trim(), lines: lines.map(({ empty, ...l }) => l) };
    const saveBtn = $('#e-save');
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
      resetForm(true);
      dateInput.focus();
      await loadList();
    } catch (e) { showError(e); }
    finally { saveBtn.disabled = false; }
  }
  function loadEntry(entry) {
    tbody.innerHTML = '';
    editingId = entry.id; editingVno = entry.voucher_no;
    setDate(entry.entry_date);
    memoInput.value = entry.memo || '';
    $('#e-vno').value = entry.voucher_no;
    for (const l of entry.lines) addLine(l);
    $('#e-status').innerHTML = `<span class="editing">修正中: 伝票 No.${entry.voucher_no}</span> <button class="small" id="e-cancel-edit">新規入力に戻る</button>`;
    $('#e-cancel-edit').onclick = () => { resetForm(true); dateInput.focus(); };
    $('#e-delete').style.display = '';
    updateTotals();
    focusFirstLine();
    window.scrollTo({ top: 0 });
  }
  function copyEntry(entry) {
    const wasEditing = editingId;
    tbody.innerHTML = '';
    editingId = null; editingVno = null;
    $('#e-vno').value = '';
    $('#e-status').innerHTML = wasEditing ? '' : '<span class="muted">前伝票を複写しました</span>';
    $('#e-delete').style.display = 'none';
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
      if (editingId === id) resetForm(true);
      await loadList();
    } catch (e) { showError(e); }
  }

  $('#e-save').onclick = save;
  $('#e-clear').onclick = () => { resetForm(true); dateInput.focus(); };
  $('#e-addrow').onclick = () => addLine({}, true);
  $('#e-delete').onclick = () => { if (editingId) deleteEntry(editingId, editingVno); };
  $('#e-template').onclick = openTemplatePicker;
  $('#e-copy').onclick = copyLast;

  async function copyLast() {
    let src = lastSaved;
    if (!src) {
      const r = await GET(`/api/clients/${S.client.id}/entries?fiscal_year_id=${S.fy.id}&limit=5000`);
      src = r.entries[r.entries.length - 1];
    }
    if (!src) { toast('複写できる伝票がありません', true); return; }
    copyEntry(src);
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
        const q = $('#tp-q', bg), body = $('#tp-body', bg);
        let hl = 0;
        const draw = () => {
          body.innerHTML = items.map((t, i) => `<tr data-i="${i}" class="clickable ${i === hl ? 'hl' : ''}">
            <td class="code">${esc(t.code)}</td><td>${esc(t.name)}</td><td>${esc(acctLabel(t.debit_account_id))}${t.debit_sub_id ? ' / ' + esc(subLabel(t.debit_sub_id)) : ''}</td>
            <td>${esc(acctLabel(t.credit_account_id))}${t.credit_sub_id ? ' / ' + esc(subLabel(t.credit_sub_id)) : ''}</td>
            <td class="num">${t.amount ? fmt(t.amount) : ''}</td><td>${esc(t.description)}</td></tr>`).join('');
        };
        const apply = (t) => {
          close();
          let tr = curTr && tbody.contains(curTr) && lineData(curTr).empty ? curTr : null;
          if (!tr) {
            const rows = $$('tr', tbody);
            const last = rows[rows.length - 1];
            tr = last && lineData(last).empty ? last : null;
          }
          if (tr) tr.remove();
          const ntr = addLine({
            debit_account_id: t.debit_account_id, debit_sub_id: t.debit_sub_id,
            credit_account_id: t.credit_account_id, credit_sub_id: t.credit_sub_id,
            amount: t.amount || 0, tax_class: t.tax_class || undefined, description: t.description,
          });
          if (!t.tax_class) ntr._state.taxTouched = false;
          renumber();
          ntr.querySelector('[data-f=amount]').focus();
        };
        q.oninput = () => {
          const s = q.value.trim().toLowerCase();
          items = S.templates.filter(t => !s || t.code.toLowerCase().includes(s) || t.name.toLowerCase().includes(s) || (t.description || '').toLowerCase().includes(s));
          hl = 0; draw();
        };
        q.onkeydown = (e) => {
          if (e.key === 'ArrowDown') { hl = Math.min(hl + 1, items.length - 1); draw(); e.preventDefault(); }
          else if (e.key === 'ArrowUp') { hl = Math.max(hl - 1, 0); draw(); e.preventDefault(); }
          else if (e.key === 'Enter') { e.preventDefault(); if (items[hl]) apply(items[hl]); }
        };
        body.onclick = (e) => { const r = e.target.closest('tr'); if (r) apply(items[Number(r.dataset.i)]); };
        draw();
        q.focus();
      },
    });
  }

  // ---------------------------------------------------------------- 一覧
  async function loadList() {
    const qs = new URLSearchParams({ fiscal_year_id: S.fy.id });
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
          <td>${esc(l.description)}${e.memo && i === 0 ? ` <span class="muted">[${esc(e.memo)}]</span>` : ''}</td>
          <td class="center" style="white-space:nowrap">${i === 0 ? `<button class="small" data-edit="${e.id}">修正</button> <button class="small danger" data-del="${e.id}" data-vno="${e.voucher_no}">削除</button>` : ''}</td>
        </tr>`);
      });
    }
    body.innerHTML = rows.join('') || `<tr><td colspan="10" class="empty">仕訳がありません</td></tr>`;
    $('#list-summary').textContent = `${entries.length} 伝票 / 合計 ${fmt(total)} 円`;
    body.onclick = async (e) => {
      const ed = e.target.closest('[data-edit]');
      const dl = e.target.closest('[data-del]');
      if (dl) { deleteEntry(Number(dl.dataset.del), dl.dataset.vno); return; }
      const tr = e.target.closest('tr[data-id]');
      if (!tr) return;
      const id = ed ? Number(ed.dataset.edit) : Number(tr.dataset.id);
      try { loadEntry(await GET(`/api/entries/${id}`)); } catch (err) { showError(err); }
    };
  }
  $('#list-mode').value = listMode;
  $('#list-mode').onchange = (e) => { listMode = e.target.value; localStorage.setItem('entryListMode', listMode); loadList(); };
  dateInput.addEventListener('change', () => { if (listMode !== 'recent') loadList(); });

  // ---------------------------------------------------------------- グローバルキー
  const onKey = (e) => {
    if (document.querySelector('.modal-bg')) return;
    if (e.key === 'Enter' && e.ctrlKey) { e.preventDefault(); save(); }
    else if (e.key === 'Escape') { if (!document.querySelector('.combo .dropdown.open')) { e.preventDefault(); resetForm(true); dateInput.focus(); } }
    else if (e.key === 'Insert' && e.ctrlKey) { e.preventDefault(); addLine({}, true); }
    else if (e.key === 'F2') { e.preventDefault(); openTemplatePicker(); }
    else if (e.key === 'F5') { e.preventDefault(); copyLast(); }
  };
  document.addEventListener('keydown', onKey);

  // ---------------------------------------------------------------- 初期化
  setDate(currentDate);
  resetForm(true);
  if (params.entry) {
    try { loadEntry(await GET(`/api/entries/${params.entry}`)); } catch (e) { showError(e); }
  } else {
    dateInput.focus();
  }
  await loadList();
  $('#header-hint').textContent = S.fy.closed ? 'この会計期間は締め切られています (入力不可)' : '';

  return () => { document.removeEventListener('keydown', onKey); $('#header-hint').textContent = ''; };
};
