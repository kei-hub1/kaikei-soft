/* マスタ画面: 勘定科目 / 部門 / 定型仕訳 / 期首残高 / 顧問先・会計期間 / データ管理 */
'use strict';

function formModal(title, fieldsHtml, onSubmit, { submitLabel = '保存', extraButtons = '' } = {}) {
  return modal(`<h3>${esc(title)}</h3><form id="fm"><div class="form">${fieldsHtml}</div>
    <div class="actions">${extraButtons}<button type="button" data-close>キャンセル</button><button type="submit" class="primary">${submitLabel}</button></div></form>`, {
    onOpen(bg, close) {
      const form = $('#fm', bg);
      const first = form.querySelector('input,select');
      if (first) first.focus();
      form.onsubmit = async (e) => {
        e.preventDefault();
        const data = Object.fromEntries(new FormData(form).entries());
        $$('input[type=checkbox]', form).forEach(c => { data[c.name] = c.checked; });
        try { await onSubmit(data, bg); close(); } catch (err) { showError(err); }
      };
    },
  });
}
const field = (label, inner, wide = false) => `<label class="field${wide ? ' wide' : ''}"><span>${esc(label)}</span>${inner}</label>`;
const textInput = (name, value = '', attrs = '') => `<input type="text" name="${name}" value="${esc(value)}" ${attrs}>`;
const selectInput = (name, options, value) => `<select name="${name}">${options.map(o => `<option value="${esc(o.value)}" ${String(o.value) === String(value) ? 'selected' : ''}>${esc(o.label)}</option>`).join('')}</select>`;
const checkInput = (name, checked) => `<input type="checkbox" name="${name}" ${checked ? 'checked' : ''}>`;

// ---------------------------------------------------------------- 勘定科目
routes.accounts = async function (main) {
  main.innerHTML = `<h2>勘定科目 / 補助科目</h2>
  <div class="toolbar no-print">
    <div class="field"><span>検索</span><input id="a-q" style="width:180px" placeholder="コード・名称"></div>
    <div class="field"><span>表示区分</span><select id="a-grp"><option value="">(すべて)</option>${S.meta.groups.map(g => `<option>${g.grp}</option>`).join('')}</select></div>
    <label><input type="checkbox" id="a-inactive"> 無効科目も表示</label>
    <button id="a-new" class="primary">科目を追加</button>
    <a class="btn" href="/api/clients/${S.client.id}/export/accounts.csv">科目一覧 CSV</a>
  </div>
  <div class="panel"><table class="grid compact" id="a-table"><thead><tr>
    <th>コード</th><th>科目名</th><th>かな</th><th>表示区分</th><th>既定の税区分</th><th>補助科目</th><th>状態</th><th></th>
  </tr></thead><tbody></tbody></table></div>`;

  function taxOpts(v) { return selectInput('default_tax_class', S.meta.tax_classes.map(t => ({ value: t.code, label: `${t.code} ${t.name}` })), v); }
  function grpOpts(v) { return selectInput('grp', S.meta.groups.map(g => ({ value: g.grp, label: g.grp })), v); }
  function roleOpts(v) {
    return selectInput('role', [
      { value: '', label: '(なし)' }, { value: 'tax_receivable', label: '仮払消費税' }, { value: 'tax_payable', label: '仮受消費税' },
      { value: 'retained', label: '繰越利益剰余金 (法人・繰越先)' }, { value: 'owner_capital', label: '元入金 (個人・繰越先)' },
      { value: 'owner_drawing', label: '事業主貸' }, { value: 'owner_contrib', label: '事業主借' }, { value: 'suspense', label: '諸口' },
    ], v);
  }
  function accountForm(a) {
    const isNew = !a;
    a = a || { code: '', name: '', kana: '', grp: '販売費及び一般管理費', default_tax_class: '00', role: '', active: 1 };
    formModal(isNew ? '科目の追加' : '科目の修正',
      field('コード', textInput('code', a.code, 'required maxlength="10"')) + field('科目名', textInput('name', a.name, 'required')) +
      field('かな (検索用)', textInput('kana', a.kana)) + field('表示区分', grpOpts(a.grp)) +
      field('既定の消費税区分', taxOpts(a.default_tax_class)) + field('特殊な役割', roleOpts(a.role)) +
      field('有効', checkInput('active', a.active)),
      async (d) => {
        const body = { code: d.code.trim(), name: d.name.trim(), kana: d.kana.trim(), grp: d.grp, default_tax_class: d.default_tax_class, role: d.role, active: !!d.active };
        if (isNew) await POST(`/api/clients/${S.client.id}/accounts`, body); else await PUT(`/api/accounts/${a.id}`, body);
        await loadAccounts(); draw(); toast('保存しました');
      });
  }
  function subForm(acct, s) {
    const isNew = !s;
    s = s || { code: '', name: '', kana: '', active: 1 };
    formModal(`${acct.code} ${acct.name} の補助科目${isNew ? '追加' : '修正'}`,
      field('コード', textInput('code', s.code, 'required maxlength="10"')) + field('名称', textInput('name', s.name, 'required')) +
      field('かな (検索用)', textInput('kana', s.kana)) + field('有効', checkInput('active', s.active)),
      async (d) => {
        const body = { code: d.code.trim(), name: d.name.trim(), kana: d.kana.trim(), active: !!d.active };
        if (isNew) await POST(`/api/accounts/${acct.id}/sub-accounts`, body); else await PUT(`/api/sub-accounts/${s.id}`, body);
        await loadAccounts(); draw(); toast('保存しました');
      });
  }
  const expanded = new Set();
  function draw() {
    const q = $('#a-q').value.trim().toLowerCase();
    const grp = $('#a-grp').value;
    const inactive = $('#a-inactive').checked;
    const rows = [];
    let lastGrp = null;
    for (const a of S.accounts) {
      if (!inactive && !a.active) continue;
      if (grp && a.grp !== grp) continue;
      if (q && !(a.code.toLowerCase().includes(q) || a.name.toLowerCase().includes(q) || (a.kana || '').includes(q))) continue;
      if (a.grp !== lastGrp) { rows.push(`<tr class="group"><td colspan="8">【${esc(a.grp)}】</td></tr>`); lastGrp = a.grp; }
      const subs = S.subsByAccount[a.id] || [];
      rows.push(`<tr data-id="${a.id}"><td class="code">${esc(a.code)}</td><td>${esc(a.name)}${a.role ? ` <span class="badge">${esc(a.role)}</span>` : ''}</td><td class="muted">${esc(a.kana)}</td>
        <td>${esc(a.grp)}</td><td>${esc(taxName(a.default_tax_class))}</td>
        <td><button class="small" data-toggle="${a.id}">${subs.length} 件 ${expanded.has(a.id) ? '▲' : '▼'}</button> <button class="small" data-addsub="${a.id}">＋追加</button></td>
        <td>${a.active ? '<span class="badge ok">有効</span>' : '<span class="badge">無効</span>'}</td>
        <td style="white-space:nowrap"><button class="small" data-edit="${a.id}">修正</button> <button class="small danger" data-del="${a.id}">削除</button></td></tr>`);
      if (expanded.has(a.id)) {
        for (const s of subs) {
          rows.push(`<tr class="sub"><td class="code"></td><td class="name">${esc(s.code)} ${esc(s.name)}</td><td class="muted">${esc(s.kana)}</td><td colspan="3" class="muted">補助科目</td>
            <td>${s.active ? '<span class="badge ok">有効</span>' : '<span class="badge">無効</span>'}</td>
            <td style="white-space:nowrap"><button class="small" data-editsub="${s.id}">修正</button> <button class="small danger" data-delsub="${s.id}">削除</button></td></tr>`);
        }
        if (!subs.length) rows.push(`<tr class="sub"><td></td><td colspan="7" class="muted">補助科目はありません</td></tr>`);
      }
    }
    $('#a-table tbody').innerHTML = rows.join('') || '<tr><td colspan="8" class="empty">科目がありません</td></tr>';
  }
  $('#a-table').onclick = async (e) => {
    const b = e.target.closest('button');
    if (!b) return;
    const ds = b.dataset;
    try {
      if (ds.toggle) { const id = Number(ds.toggle); expanded.has(id) ? expanded.delete(id) : expanded.add(id); draw(); }
      else if (ds.edit) accountForm(S.accountById[Number(ds.edit)]);
      else if (ds.del) {
        const a = S.accountById[Number(ds.del)];
        if (await confirmDialog(`科目 ${a.code} ${a.name} を削除します。よろしいですか？`)) { await DEL(`/api/accounts/${a.id}`); await loadAccounts(); draw(); toast('削除しました'); }
      }
      else if (ds.addsub) { expanded.add(Number(ds.addsub)); subForm(S.accountById[Number(ds.addsub)]); }
      else if (ds.editsub) { const s = S.subById[Number(ds.editsub)]; subForm(S.accountById[s.account_id], s); }
      else if (ds.delsub) {
        const s = S.subById[Number(ds.delsub)];
        if (await confirmDialog(`補助科目 ${s.name} を削除します。よろしいですか？`)) { await DEL(`/api/sub-accounts/${s.id}`); await loadAccounts(); draw(); toast('削除しました'); }
      }
    } catch (err) { showError(err); }
  };
  $('#a-new').onclick = () => accountForm(null);
  $('#a-q').oninput = $('#a-grp').onchange = $('#a-inactive').onchange = draw;
  draw();
};

// ---------------------------------------------------------------- 部門
routes.departments = async function (main) {
  main.innerHTML = `<h2>部門</h2>
  <div class="toolbar"><button id="d-new" class="primary">部門を追加</button><span class="muted">部門を登録すると仕訳入力画面に部門欄が表示されます。</span></div>
  <div class="panel"><table class="grid compact" id="d-table"><thead><tr><th>コード</th><th>部門名</th><th>状態</th><th></th></tr></thead><tbody></tbody></table></div>`;
  function form(d) {
    const isNew = !d;
    d = d || { code: '', name: '', active: 1 };
    formModal(isNew ? '部門の追加' : '部門の修正',
      field('コード', textInput('code', d.code, 'required maxlength="10"')) + field('部門名', textInput('name', d.name, 'required')) + field('有効', checkInput('active', d.active)),
      async (x) => {
        const body = { code: x.code.trim(), name: x.name.trim(), active: !!x.active };
        if (isNew) await POST(`/api/clients/${S.client.id}/departments`, body); else await PUT(`/api/departments/${d.id}`, body);
        await loadDepartments(); draw(); toast('保存しました');
      });
  }
  function draw() {
    $('#d-table tbody').innerHTML = S.departments.map(d => `<tr><td class="code">${esc(d.code)}</td><td>${esc(d.name)}</td>
      <td>${d.active ? '<span class="badge ok">有効</span>' : '<span class="badge">無効</span>'}</td>
      <td><button class="small" data-edit="${d.id}">修正</button> <button class="small danger" data-del="${d.id}">削除</button></td></tr>`).join('')
      || '<tr><td colspan="4" class="empty">部門はありません</td></tr>';
  }
  $('#d-table').onclick = async (e) => {
    const b = e.target.closest('button'); if (!b) return;
    try {
      if (b.dataset.edit) form(S.departments.find(d => d.id === Number(b.dataset.edit)));
      else if (b.dataset.del && await confirmDialog('この部門を削除します。よろしいですか？')) { await DEL(`/api/departments/${b.dataset.del}`); await loadDepartments(); draw(); }
    } catch (err) { showError(err); }
  };
  $('#d-new').onclick = () => form(null);
  draw();
};

// ---------------------------------------------------------------- 定型仕訳
routes.templates = async function (main) {
  main.innerHTML = `<h2>定型仕訳</h2>
  <div class="toolbar"><button id="p-new" class="primary">定型仕訳を追加</button><span class="muted">仕訳入力画面で <kbd>F2</kbd> を押すと呼び出せます。</span></div>
  <div class="panel"><table class="grid compact" id="p-table"><thead><tr><th>コード</th><th>名称</th><th>借方</th><th>貸方</th><th>金額</th><th>税区分</th><th>摘要</th><th></th></tr></thead><tbody></tbody></table></div>`;
  function form(t) {
    const isNew = !t;
    t = t || { code: String(S.templates.length + 1), name: '', amount: 0, tax_class: '', description: '' };
    const { bg } = formModal(isNew ? '定型仕訳の追加' : '定型仕訳の修正',
      field('コード', textInput('code', t.code, 'required maxlength="10"')) + field('名称', textInput('name', t.name, 'required')) +
      field('借方科目', '<input type="text" id="p-dr" placeholder="コード・かな・名称">') + field('借方補助', '<select id="p-drsub"><option value="">(なし)</option></select>') +
      field('貸方科目', '<input type="text" id="p-cr" placeholder="コード・かな・名称">') + field('貸方補助', '<select id="p-crsub"><option value="">(なし)</option></select>') +
      field('金額 (0 = 都度入力)', `<input type="text" name="amount" class="num" value="${t.amount || ''}">`) +
      field('消費税区分', selectInput('tax_class', [{ value: '', label: '(科目の既定に従う)' }].concat(S.meta.tax_classes.map(x => ({ value: x.code, label: `${x.code} ${x.name}` }))), t.tax_class)) +
      field('摘要', textInput('description', t.description), true),
      async (d) => {
        const body = {
          code: d.code.trim(), name: d.name.trim(), amount: parseAmount(d.amount), tax_class: d.tax_class, description: d.description.trim(),
          debit_account_id: dr.id, debit_sub_id: Number($('#p-drsub', bg).value) || null,
          credit_account_id: cr.id, credit_sub_id: Number($('#p-crsub', bg).value) || null,
        };
        if (isNew) await POST(`/api/clients/${S.client.id}/templates`, body); else await PUT(`/api/templates/${t.id}`, body);
        await loadTemplates(); draw(); toast('保存しました');
      });
    const fillSub = (sel, accountId, val) => {
      sel.innerHTML = '<option value="">(なし)</option>' + (S.subsByAccount[accountId] || []).map(s => `<option value="${s.id}" ${s.id === val ? 'selected' : ''}>${esc(s.code)} ${esc(s.name)}</option>`).join('');
    };
    const dr = makeCombo($('#p-dr', bg), { items: () => S.accounts.filter(a => a.active), onChange: (it) => fillSub($('#p-drsub', bg), it && it.id), onCommit: () => $('#p-drsub', bg).focus() });
    const cr = makeCombo($('#p-cr', bg), { items: () => S.accounts.filter(a => a.active), onChange: (it) => fillSub($('#p-crsub', bg), it && it.id), onCommit: () => $('#p-crsub', bg).focus() });
    if (t.debit_account_id) { dr.set(t.debit_account_id); fillSub($('#p-drsub', bg), t.debit_account_id, t.debit_sub_id); }
    if (t.credit_account_id) { cr.set(t.credit_account_id); fillSub($('#p-crsub', bg), t.credit_account_id, t.credit_sub_id); }
  }
  function draw() {
    $('#p-table tbody').innerHTML = S.templates.map(t => `<tr><td class="code">${esc(t.code)}</td><td>${esc(t.name)}</td>
      <td>${esc(acctLabel(t.debit_account_id))}${t.debit_sub_id ? ' / ' + esc(subLabel(t.debit_sub_id)) : ''}</td>
      <td>${esc(acctLabel(t.credit_account_id))}${t.credit_sub_id ? ' / ' + esc(subLabel(t.credit_sub_id)) : ''}</td>
      <td class="num">${t.amount ? fmt(t.amount) : ''}</td><td>${t.tax_class ? esc(taxName(t.tax_class)) : '<span class="muted">既定</span>'}</td><td>${esc(t.description)}</td>
      <td style="white-space:nowrap"><button class="small" data-edit="${t.id}">修正</button> <button class="small danger" data-del="${t.id}">削除</button></td></tr>`).join('')
      || '<tr><td colspan="8" class="empty">定型仕訳はありません</td></tr>';
  }
  $('#p-table').onclick = async (e) => {
    const b = e.target.closest('button'); if (!b) return;
    try {
      if (b.dataset.edit) form(S.templates.find(t => t.id === Number(b.dataset.edit)));
      else if (b.dataset.del && await confirmDialog('この定型仕訳を削除します。よろしいですか？')) { await DEL(`/api/templates/${b.dataset.del}`); await loadTemplates(); draw(); }
    } catch (err) { showError(err); }
  };
  $('#p-new').onclick = () => form(null);
  draw();
};

// ---------------------------------------------------------------- 期首残高
routes.opening = async function (main) {
  main.innerHTML = `<h2>期首残高 <span class="muted" style="font-size:12px">${esc(S.fy.label)}</span></h2>
  <div class="toolbar">
    <label><input type="checkbox" id="o-all"> 残高のない科目も表示</label>
    <button id="o-save" class="primary">保存</button>
    <span id="o-diff" class="mono"></span>
    <span class="muted">借方合計と貸方合計が一致するように入力してください。前期からの繰越は「データ管理」→「繰越処理」で自動設定できます。</span>
  </div>
  <div class="panel"><table class="grid compact sticky-head" id="o-table"><thead><tr><th>コード</th><th>科目 / 補助科目</th><th>借方残高</th><th>貸方残高</th></tr></thead><tbody></tbody></table></div>`;
  const existing = await GET(`/api/fiscal-years/${S.fy.id}/opening-balances`);
  const vals = {};  // key "aid:sid" -> signed amount
  for (const o of existing) vals[`${o.account_id}:${o.sub_account_id}`] = o.amount;

  function draw() {
    const showAll = $('#o-all').checked;
    const rows = [];
    let lastGrp = null;
    for (const a of S.accounts) {
      if (!['asset', 'liability', 'equity'].includes(a.category)) continue;
      const subs = (S.subsByAccount[a.id] || []).filter(s => s.active);
      const keys = [`${a.id}:0`].concat(subs.map(s => `${a.id}:${s.id}`));
      const has = keys.some(k => vals[k]);
      if (!showAll && !a.active && !has) continue;
      if (!showAll && !has && a.role === 'suspense') continue;
      if (a.grp !== lastGrp) { rows.push(`<tr class="group"><td colspan="4">【${esc(a.grp)}】</td></tr>`); lastGrp = a.grp; }
      const cell = (k) => {
        const v = vals[k] || 0;
        return `<td><input class="num" style="width:100%" data-k="${k}" data-side="D" value="${v > 0 ? fmt(v) : ''}"></td><td><input class="num" style="width:100%" data-k="${k}" data-side="C" value="${v < 0 ? fmt(-v) : ''}"></td>`;
      };
      rows.push(`<tr><td class="code">${esc(a.code)}</td><td>${esc(a.name)}${subs.length ? ' <span class="muted">(補助なし分)</span>' : ''}</td>${cell(`${a.id}:0`)}</tr>`);
      for (const s of subs) rows.push(`<tr class="sub"><td></td><td class="name">${esc(s.code)} ${esc(s.name)}</td>${cell(`${a.id}:${s.id}`)}</tr>`);
    }
    $('#o-table tbody').innerHTML = rows.join('');
    updateDiff();
  }
  function updateDiff() {
    let d = 0, c = 0;
    for (const v of Object.values(vals)) { if (v > 0) d += v; else c += -v; }
    $('#o-diff').innerHTML = `借方合計 ${fmt(d)}　貸方合計 ${fmt(c)}　差額 <b class="${d === c ? '' : 'neg'}">${fmt(d - c)}</b>`;
  }
  $('#o-table').addEventListener('change', (e) => {
    const inp = e.target;
    if (!inp.dataset.k) return;
    const v = parseAmount(inp.value);
    inp.value = v ? fmt(v) : '';
    const tr = inp.closest('tr');
    const other = tr.querySelector(`input[data-k="${inp.dataset.k}"][data-side="${inp.dataset.side === 'D' ? 'C' : 'D'}"]`);
    if (v) other.value = '';
    vals[inp.dataset.k] = inp.dataset.side === 'D' ? v : -v;
    updateDiff();
  });
  $('#o-table').addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && e.target.dataset.k) {
      e.preventDefault();
      const inputs = $$('input[data-k]', $('#o-table'));
      const i = inputs.indexOf(e.target);
      const next = inputs[i + 2] || inputs[i + 1];
      if (next) { next.focus(); next.select(); }
    }
  });
  $('#o-save').onclick = async () => {
    const items = Object.entries(vals).filter(([, v]) => v).map(([k, v]) => { const [a, s] = k.split(':').map(Number); return { account_id: a, sub_account_id: s, amount: v }; });
    try {
      const r = await PUT(`/api/fiscal-years/${S.fy.id}/opening-balances`, { items });
      toast(r.difference === 0 ? '保存しました' : `保存しました (貸借差額 ${fmt(r.difference)} があります)`, r.difference !== 0);
    } catch (err) { showError(err); }
  };
  $('#o-all').onchange = draw;
  draw();
};

// ---------------------------------------------------------------- 顧問先・会計期間
routes.clients = async function (main) {
  main.innerHTML = `<h2>顧問先・会計期間</h2>
  <div class="two-col">
    <div class="panel">
      <div class="row between"><h3 style="margin:0">顧問先</h3><button id="c-new" class="primary">顧問先を追加</button></div>
      <table class="grid compact" id="c-table" style="margin-top:8px"><thead><tr><th>コード</th><th>名称</th><th>形態</th><th>消費税</th><th>決算月</th><th></th></tr></thead><tbody></tbody></table>
    </div>
    <div class="panel" id="fy-panel"></div>
  </div>`;
  function clientForm(c) {
    const isNew = !c;
    c = c || { code: String(S.clients.length + 1).padStart(3, '0'), name: '', kana: '', entity_type: 'corp', tax_method: 'inclusive', fiscal_start_month: 4, note: '' };
    formModal(isNew ? '顧問先の追加' : '顧問先の修正',
      field('コード', textInput('code', c.code, 'required maxlength="20"')) + field('名称', textInput('name', c.name, 'required')) + field('かな', textInput('kana', c.kana)) +
      field('事業形態', selectInput('entity_type', S.meta.entity_types.map(x => ({ value: x.code, label: x.name })), c.entity_type)) +
      field('消費税の経理方式', selectInput('tax_method', S.meta.tax_methods.map(x => ({ value: x.code, label: x.name })), c.tax_method)) +
      field('期首月 (法人)', selectInput('fiscal_start_month', Array.from({ length: 12 }, (_, i) => ({ value: i + 1, label: `${i + 1}月` })), c.fiscal_start_month)) +
      field('備考', textInput('note', c.note), true) +
      (isNew ? '<div class="field wide muted">追加時に標準の勘定科目表と当期の会計期間が自動作成されます。</div>' : ''),
      async (d) => {
        const body = { code: d.code.trim(), name: d.name.trim(), kana: d.kana.trim(), entity_type: d.entity_type, tax_method: d.tax_method, fiscal_start_month: Number(d.fiscal_start_month), note: d.note };
        let saved;
        if (isNew) saved = await POST('/api/clients', body); else saved = await PUT(`/api/clients/${c.id}`, body);
        S.clients = await GET('/api/clients');
        await loadClients();
        await selectClient(saved.id, true);
        draw(); toast('保存しました');
      });
  }
  function draw() {
    $('#c-table tbody').innerHTML = S.clients.map(c => `<tr class="clickable ${S.client && c.id === S.client.id ? 'selected' : ''}" data-id="${c.id}">
      <td class="code">${esc(c.code)}</td><td>${esc(c.name)}</td><td>${c.entity_type === 'sole' ? '個人' : '法人'}</td>
      <td>${esc((S.meta.tax_methods.find(t => t.code === c.tax_method) || {}).name || '')}</td><td class="center">${c.entity_type === 'sole' ? '12月' : ((c.fiscal_start_month + 10) % 12 + 1) + '月'}</td>
      <td style="white-space:nowrap"><button class="small" data-edit="${c.id}">修正</button> <button class="small danger" data-del="${c.id}">削除</button></td></tr>`).join('')
      || '<tr><td colspan="6" class="empty">顧問先がありません。「顧問先を追加」から登録してください。</td></tr>';
    drawFy();
  }
  function drawFy() {
    const p = $('#fy-panel');
    if (!S.client) { p.innerHTML = '<div class="empty">顧問先を選択してください</div>'; return; }
    p.innerHTML = `<div class="row between"><h3 style="margin:0">会計期間: ${esc(S.client.name)}</h3>
      <div class="row"><button id="fy-next">翌期を作成</button><button id="fy-new">期間を追加</button></div></div>
      <table class="grid compact" style="margin-top:8px"><thead><tr><th>期間</th><th>自</th><th>至</th><th>仕訳</th><th>状態</th><th></th></tr></thead><tbody>
      ${S.fiscalYears.map(f => `<tr class="${S.fy && f.id === S.fy.id ? 'selected' : ''}"><td>${esc(f.label)}</td><td class="code">${fmtDate(f.start_date)}</td><td class="code">${fmtDate(f.end_date)}</td>
        <td class="num">${f.entry_count}</td><td>${f.closed ? '<span class="badge warn">締切</span>' : '<span class="badge ok">入力可</span>'}</td>
        <td style="white-space:nowrap"><button class="small" data-select="${f.id}">選択</button> <button class="small" data-edit="${f.id}">修正</button>
        <button class="small" data-close="${f.id}" data-closed="${f.closed}">${f.closed ? '締切解除' : '締切'}</button> <button class="small danger" data-del="${f.id}">削除</button></td></tr>`).join('')}
      </tbody></table>
      <p class="help">「締切」にすると、その期間の仕訳を追加・修正・削除できなくなります。</p>`;
    $('#fy-next').onclick = async () => {
      try { await POST(`/api/clients/${S.client.id}/fiscal-years/next`); await loadFiscalYears(true); drawFy(); toast('翌期を作成しました'); } catch (e) { showError(e); }
    };
    $('#fy-new').onclick = () => fyForm(null);
    p.querySelector('tbody').onclick = async (e) => {
      const b = e.target.closest('button'); if (!b) return;
      const ds = b.dataset;
      try {
        if (ds.select) { S.fy = S.fiscalYears.find(f => f.id === Number(ds.select)); $('#sel-fy').value = S.fy.id; localStorage.setItem('fyId:' + S.client.id, S.fy.id); drawFy(); }
        else if (ds.edit) fyForm(S.fiscalYears.find(f => f.id === Number(ds.edit)));
        else if (ds.close) { await POST(`/api/fiscal-years/${ds.close}/close?closed=${ds.closed === '1' ? 'false' : 'true'}`); await loadFiscalYears(true); drawFy(); }
        else if (ds.del && await confirmDialog('この会計期間を削除します。よろしいですか？')) { await DEL(`/api/fiscal-years/${ds.del}`); await loadFiscalYears(false); drawFy(); }
      } catch (err) { showError(err); }
    };
  }
  function fyForm(f) {
    const isNew = !f;
    f = f || { start_date: '', end_date: '', label: '' };
    formModal(isNew ? '会計期間の追加' : '会計期間の修正',
      field('期首日', `<input type="date" name="start_date" value="${f.start_date}" required>`) + field('期末日', `<input type="date" name="end_date" value="${f.end_date}" required>`) +
      field('表示名 (空欄で自動)', textInput('label', f.label), true),
      async (d) => {
        if (isNew) await POST(`/api/clients/${S.client.id}/fiscal-years`, d); else await PUT(`/api/fiscal-years/${f.id}`, d);
        await loadFiscalYears(true); drawFy(); toast('保存しました');
      });
  }
  $('#c-new').onclick = () => clientForm(null);
  $('#c-table').onclick = async (e) => {
    const b = e.target.closest('button');
    const tr = e.target.closest('tr[data-id]');
    try {
      if (b && b.dataset.edit) clientForm(S.clients.find(c => c.id === Number(b.dataset.edit)));
      else if (b && b.dataset.del) {
        const c = S.clients.find(x => x.id === Number(b.dataset.del));
        if (await confirmDialog(`顧問先「${c.name}」とその仕訳・科目をすべて削除します。この操作は取り消せません。よろしいですか？`)) {
          await DEL(`/api/clients/${c.id}`);
          if (S.client && S.client.id === c.id) S.client = null;
          await loadClients(); draw(); toast('削除しました');
        }
      } else if (tr) { await selectClient(Number(tr.dataset.id)); draw(); }
    } catch (err) { showError(err); }
  };
  draw();
};

// ---------------------------------------------------------------- データ管理
routes.data = async function (main) {
  const hasClient = !!S.client;
  main.innerHTML = `<h2>データ管理</h2>
  <div class="two-col">
    <div class="panel"><h3 style="margin-top:0">仕訳 CSV 出力</h3>
      ${hasClient ? `<p>選択中の顧問先・会計期間 (${esc(S.fy ? S.fy.label : '')}) の仕訳を CSV (UTF-8 BOM 付き, Excel で開けます) に出力します。</p>
      <a class="btn" href="/api/fiscal-years/${S.fy ? S.fy.id : 0}/export/journal.csv">仕訳 CSV をダウンロード</a>` : '<p class="muted">顧問先を選択してください</p>'}
    </div>
    <div class="panel"><h3 style="margin-top:0">仕訳 CSV 取込</h3>
      ${hasClient ? `<p>本ソフトで出力した形式の CSV を取り込みます (UTF-8 / Shift_JIS)。科目はコードまたは科目名で照合します。同じ「日付+伝票番号」の行は 1 伝票にまとめます。</p>
      <div class="row"><input type="file" id="i-file" accept=".csv,text/csv"><button id="i-check">検証</button><button id="i-run" class="primary">取込</button></div>
      <div id="i-result" style="margin-top:8px"></div>
      <details style="margin-top:8px"><summary class="muted">CSV の列</summary><code style="font-size:11px">日付, 伝票番号, 借方科目コード, 借方科目名, 借方補助コード, 借方補助名, 借方部門コード, 貸方科目コード, 貸方科目名, 貸方補助コード, 貸方補助名, 貸方部門コード, 金額, 消費税区分, 消費税額, 摘要, 伝票メモ</code></details>` : '<p class="muted">顧問先を選択してください</p>'}
    </div>
    <div class="panel"><h3 style="margin-top:0">繰越処理</h3>
      ${hasClient && S.fy ? `<p>「${esc(S.fy.label)}」の期末残高を翌期の期首残高へ転記します。翌期が無い場合は自動作成します。当期純利益は ${S.client.entity_type === 'sole' ? '元入金' : '繰越利益剰余金'} へ加算されます。<br>翌期の期首残高は上書きされます。決算確定後に実行してください (何度でも再実行できます)。</p>
      <button id="cf-run" class="primary">繰越処理を実行</button>` : '<p class="muted">顧問先を選択してください</p>'}
    </div>
    <div class="panel"><h3 style="margin-top:0">バックアップ</h3>
      <p>全データ (SQLite ファイル) をダウンロードします。復元するときは、サーバー停止後に <code>data/kaikei.db</code> をこのファイルで置き換えてください。</p>
      <a class="btn" href="/api/backup">バックアップをダウンロード</a>
    </div>
  </div>`;
  if (!hasClient) return;
  async function upload(dry) {
    const f = $('#i-file').files[0];
    if (!f) { toast('CSV ファイルを選択してください', true); return; }
    const fd = new FormData(); fd.append('file', f);
    const res = $('#i-result');
    res.innerHTML = '処理中...';
    try {
      const r = await api('POST', `/api/clients/${S.client.id}/import/journal?dry_run=${dry}`, fd);
      res.innerHTML = `<span class="badge ok">${dry ? '検証OK' : '取込完了'}</span> ${r.count} 伝票 / ${r.lines} 行`;
      if (!dry) { toast(`${r.count} 伝票を取り込みました`); await loadFiscalYears(true); }
    } catch (e) { res.innerHTML = `<span class="badge danger">エラー</span> ${esc(e.message)}`; }
  }
  $('#i-check').onclick = () => upload(true);
  $('#i-run').onclick = async () => { if (await confirmDialog('CSV を取り込みます。よろしいですか？')) upload(false); };
  if ($('#cf-run')) $('#cf-run').onclick = async () => {
    if (!(await confirmDialog(`${S.fy.label} の繰越処理を実行します。翌期の期首残高は上書きされます。よろしいですか？`))) return;
    try {
      const r = await POST(`/api/fiscal-years/${S.fy.id}/carry-forward`);
      await loadFiscalYears(true);
      toast(`繰越処理が完了しました: ${r.next_fiscal_year.label} へ ${r.count} 件の期首残高を設定 (当期純利益 ${fmt(r.net_income)})`);
    } catch (e) { showError(e); }
  };
};
