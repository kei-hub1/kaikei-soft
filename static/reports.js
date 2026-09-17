/* 帳票画面: 仕訳帳 / 総勘定元帳 / 残高試算表 / 月次推移表 / 消費税集計表 / 決算書 */
'use strict';

function periodToolbar(id, { from = S.fy.start_date, to = S.fy.end_date } = {}) {
  return `
    <div class="field"><span>期間 (自)</span><input type="date" id="${id}-from" value="${from}" min="${S.fy.start_date}" max="${S.fy.end_date}"></div>
    <div class="field"><span>期間 (至)</span><input type="date" id="${id}-to" value="${to}" min="${S.fy.start_date}" max="${S.fy.end_date}"></div>
    <div class="field"><span>月指定</span><select id="${id}-month"><option value="">(期間全体)</option>${monthOptions()}</select></div>`;
}
function monthOptions() {
  const out = [];
  let [y, m] = S.fy.start_date.split('-').map(Number);
  const end = S.fy.end_date.slice(0, 7);
  for (let i = 0; i < 24; i++) {
    const ym = `${y}-${String(m).padStart(2, '0')}`;
    out.push(`<option value="${ym}">${y}年${m}月</option>`);
    if (ym >= end) break;
    m++; if (m > 12) { m = 1; y++; }
  }
  return out.join('');
}
function bindMonthSelect(id, onChange) {
  const sel = $(`#${id}-month`), from = $(`#${id}-from`), to = $(`#${id}-to`);
  sel.onchange = () => {
    if (!sel.value) { from.value = S.fy.start_date; to.value = S.fy.end_date; }
    else {
      const [y, m] = sel.value.split('-').map(Number);
      const last = new Date(y, m, 0).getDate();
      from.value = `${sel.value}-01`; to.value = `${sel.value}-${last}`;
      if (from.value < S.fy.start_date) from.value = S.fy.start_date;
      if (to.value > S.fy.end_date) to.value = S.fy.end_date;
    }
    onChange();
  };
  from.onchange = to.onchange = () => { sel.value = ''; onChange(); };
}
function printButton() { return `<button onclick="window.print()">印刷</button>`; }
function csvButton(id) { return `<button id="${id}">CSV</button>`; }
function tableToCsv(table, filename) {
  const rows = $$('tr', table).map(tr => $$('th,td', tr).map(td => {
    let t = td.textContent.trim().replace(/△/g, '-').replace(/,/g, '');
    if (td.classList.contains('num') && t === '') t = '0';
    return `"${t.replace(/"/g, '""')}"`;
  }).join(','));
  const blob = new Blob(['﻿' + rows.join('\r\n')], { type: 'text/csv' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = filename; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
function accountSelectHtml(id, { all = false, includeBlank = true } = {}) {
  return `<select id="${id}">${includeBlank ? '<option value="">(すべて)</option>' : ''}${S.accounts.filter(a => all || a.active)
    .map(a => `<option value="${a.id}">${esc(a.code)} ${esc(a.name)}</option>`).join('')}</select>`;
}

// ---------------------------------------------------------------- 仕訳帳
routes.journal = async function (main, params) {
  const exempt = isExempt();
  main.innerHTML = `<h2>仕訳帳</h2>
  <div class="toolbar no-print">
    ${periodToolbar('j', { from: params.from, to: params.to })}
    <div class="field"><span>科目</span><input id="j-acct" style="width:200px" placeholder="コード・かな・名称 (空欄で全科目)"></div>
    <div class="field"><span>摘要検索</span><input id="j-q" style="width:160px"></div>
    <div class="field"><span>並び順</span><select id="j-sort">
      <option value="date">日付順</option><option value="description">摘要順</option></select></div>
    <button id="j-run" class="primary">表示</button>
    ${printButton()} ${csvButton('j-csv')} ${backButtonHtml()}
  </div>
  <div class="panel"><div id="j-title"></div>
  <div class="muted no-print" style="margin:2px 0 4px">行をクリックすると、その仕訳をこの画面のまま修正できます。修正画面から前後の仕訳へそのまま移れます。</div>
  <div class="scroll-x"><table class="grid compact sticky-head" id="j-table"><thead><tr>
    <th>日付</th><th>No</th><th>借方科目</th><th>借方補助</th><th>貸方科目</th><th>貸方補助</th><th>金額</th>${exempt ? '' : '<th>税区分</th><th>内消費税</th>'}<th>摘要</th>
  </tr></thead><tbody></tbody></table></div></div>`;
  // 開いた直後からコードを打てるよう、科目欄は入力欄 (コード・かな・名称で検索)
  // 科目を変えたら摘要の絞り込みは外す。前の科目に合わせて入れた摘要が
  // 残っていると、新しい科目では 1 件も出ない、ということが起きるため。
  const acctCombo = makeCombo($('#j-acct'), {
    items: () => S.accounts,
    onChange: () => { $('#j-q').value = ''; run(); },
    onCommit: () => { $('#j-acct').select(); },
  });
  if (params.account) acctCombo.set(Number(params.account));
  if (params.q) $('#j-q').value = params.q;
  if (params.sort) $('#j-sort').value = params.sort;

  let shown = [];                          // いま表示している伝票 id (表示順)
  async function run() {
    const sort = $('#j-sort').value;
    const qs = new URLSearchParams({ fiscal_year_id: S.fy.id, date_from: $('#j-from').value, date_to: $('#j-to').value, limit: 5000, sort });
    if (acctCombo.id) qs.set('account_id', acctCombo.id);
    if ($('#j-q').value.trim()) qs.set('q', $('#j-q').value.trim());
    const r = await GET(`/api/clients/${S.client.id}/entries?${qs}`);
    shown = r.entries.map(e => e.id);      // 修正ダイアログで前後に移れるようにする
    $('#j-title').innerHTML = reportHeader('仕訳帳', `${fmtDate($('#j-from').value)} 〜 ${fmtDate($('#j-to').value)}　${r.total} 伝票${sort === 'description' ? '　摘要順' : ''}`);
    let total = 0;
    const rows = [];
    // 摘要順のときは、摘要が変わる位置に小計を挟む
    let curDesc = null, grpDr = 0, grpCount = 0;
    const flush = () => {
      if (curDesc === null || !grpCount) return;
      rows.push(`<tr class="subtotal"><td colspan="6">${esc(curDesc || '(摘要なし)')} 小計 (${grpCount} 行)</td>
        <td class="num">${fmt(grpDr)}</td><td colspan="${exempt ? 1 : 3}"></td></tr>`);
      grpDr = 0; grpCount = 0;
    };
    for (const e of r.entries) {
      if (sort === 'description') {
        const d = (e.lines.find(l => l.description) || {}).description || '';
        if (d !== curDesc) { flush(); curDesc = d; }
      }
      e.lines.forEach((l, i) => {
        if (l.debit_account_id) { total += l.amount; grpDr += l.amount; }
        grpCount++;
        rows.push(`<tr class="clickable" data-id="${e.id}">
          <td class="code">${i === 0 ? fmtDate(e.entry_date) : ''}</td><td class="num">${i === 0 ? e.voucher_no : ''}</td>
          <td>${l.debit_code ? esc(l.debit_code + ' ' + l.debit_name) : '<span class="muted">諸口</span>'}</td><td>${esc(l.debit_sub_name || '')}</td>
          <td>${l.credit_code ? esc(l.credit_code + ' ' + l.credit_name) : '<span class="muted">諸口</span>'}</td><td>${esc(l.credit_sub_name || '')}</td>
          <td class="num">${fmt(l.amount)}</td>
          ${exempt ? '' : `<td class="code">${l.tax_class !== '00' ? esc(taxShort(l.tax_class)) : ''}</td><td class="num">${l.tax_amount ? fmt(l.tax_amount) : ''}</td>`}
          <td>${esc(l.description)}${e.memo && i === 0 ? ` <span class="muted">[${esc(e.memo)}]</span>` : ''}</td></tr>`);
      });
    }
    flush();
    rows.push(`<tr class="total"><td colspan="6">合計</td><td class="num">${fmt(total)}</td><td colspan="${exempt ? 1 : 3}"></td></tr>`);
    $('#j-table tbody').innerHTML = rows.join('');
  }
  $('#j-run').onclick = run;
  $('#j-sort').onchange = run;
  $('#j-q').onkeydown = (e) => { if (e.key === 'Enter') run(); };
  bindMonthSelect('j', run);
  $('#j-csv').onclick = () => tableToCsv($('#j-table'), `仕訳帳_${S.client.code}.csv`);
  // 行をクリックしたら、その場で修正できるダイアログを開く
  $('#j-table').addEventListener('click', (e) => {
    const tr = e.target.closest('tr[data-id]');
    if (tr) openEntryDialog(Number(tr.dataset.id), { onChanged: run, siblings: shown });
  });
  await run();
  $('#j-acct').focus({ preventScroll: true });
  return bindDrillBack();
};

// ---------------------------------------------------------------- 総勘定元帳
routes.ledger = async function (main, params) {
  main.innerHTML = `<h2>総勘定元帳 / 補助元帳</h2>
  <div class="toolbar no-print">
    <div class="field"><span>勘定科目</span><input id="l-acct" style="width:220px" placeholder="コード・かな・名称"></div>
    <div class="field"><span>補助科目</span><select id="l-sub"><option value="">(科目合計)</option></select></div>
    ${periodToolbar('l', { from: params.from, to: params.to })}
    <div class="field"><span>並び順</span><select id="l-sort">
      <option value="date">日付順</option><option value="description">摘要順</option></select></div>
    <button id="l-prev" title="前の科目">◀</button><button id="l-next" title="次の科目">▶</button>
    ${printButton()} ${csvButton('l-csv')} ${backButtonHtml()}
  </div>
  <div class="panel"><div id="l-title"></div>
  <div class="muted no-print" style="margin:2px 0 4px">行をクリックすると、その仕訳をこの画面のまま修正できます。</div>
  <div class="scroll-x"><table class="grid compact sticky-head" id="l-table"><thead><tr>
    <th>日付</th><th>No</th><th>相手科目</th><th>相手補助</th><th>摘要</th><th>借方</th><th>貸方</th><th>残高</th>
  </tr></thead><tbody></tbody></table></div></div>`;
  // 確定後は入力欄の文字を選択状態にしておく。続けて次のコードを打つだけで切り替わる。
  const acctCombo = makeCombo($('#l-acct'), {
    items: () => S.accounts,
    onChange: () => { fillSubs(); run(); },
    onCommit: () => { run(); $('#l-acct').select(); },
  });
  const subSel = $('#l-sub');
  function fillSubs() {
    const subs = acctCombo.id ? (S.subsByAccount[acctCombo.id] || []) : [];
    subSel.innerHTML = '<option value="">(科目合計)</option>' + subs.map(s => `<option value="${s.id}">${esc(s.code)} ${esc(s.name)}</option>`).join('');
  }
  let shown = [];                          // いま表示している伝票 id (表示順)
  async function run() {
    if (!acctCombo.id) { $('#l-table tbody').innerHTML = '<tr><td colspan="8" class="empty">科目を選択してください</td></tr>'; shown = []; return; }
    const sort = $('#l-sort').value;
    const qs = new URLSearchParams({ account_id: acctCombo.id, date_from: $('#l-from').value, date_to: $('#l-to').value, sort });
    if (subSel.value) qs.set('sub_id', subSel.value);
    const r = await GET(`/api/fiscal-years/${S.fy.id}/reports/ledger?${qs}`);
    shown = r.rows.map(x => x.entry_id);
    const a = r.account;
    $('#l-title').innerHTML = reportHeader(`${subSel.value ? '補助元帳' : '総勘定元帳'}　${a.code} ${a.name}${r.sub ? ' / ' + r.sub.name : ''}`,
      `${fmtDate($('#l-from').value)} 〜 ${fmtDate($('#l-to').value)}${sort === 'description' ? '　摘要順' : ''}`);
    const byDesc = sort === 'description';
    // 摘要順では残高欄が意味を持たないので出さず、代わりに摘要ごとの小計を挟む
    $('#l-table thead th:last-child').textContent = byDesc ? '' : '残高';
    const rows = byDesc ? []
      : [`<tr class="subtotal"><td colspan="5">前期繰越 / 期間前残高</td><td></td><td></td>${fmtCell0(r.opening)}</tr>`];
    let curDesc = null;
    const groupOf = (d) => (r.groups || []).find(g => g.description === d);
    for (const x of r.rows) {
      if (byDesc && x.description !== curDesc) {
        if (curDesc !== null) {
          const g = groupOf(curDesc);
          if (g) rows.push(`<tr class="subtotal"><td colspan="5">${esc(curDesc || '(摘要なし)')} 小計 (${g.count} 件)</td>${fmtCell0(g.debit)}${fmtCell0(g.credit)}<td></td></tr>`);
        }
        curDesc = x.description;
      }
      rows.push(`<tr class="clickable" data-id="${x.entry_id}">
        <td class="code">${fmtDate(x.date)}</td><td class="num">${x.voucher_no}</td>
        <td>${x.counter_code ? esc(x.counter_code + ' ' + x.counter_name) : '<span class="muted">諸口</span>'}</td><td>${esc(x.counter_sub)}</td>
        <td>${esc(x.description)}${x.is_tax_split ? ' <span class="badge">消費税</span>' : ''}${x.sub_name && !subSel.value ? ` <span class="muted">(${esc(x.sub_name)})</span>` : ''}</td>
        ${fmtCell(x.debit)}${fmtCell(x.credit)}${byDesc ? '<td></td>' : fmtCell0(x.balance)}</tr>`);
    }
    if (byDesc && curDesc !== null) {
      const g = groupOf(curDesc);
      if (g) rows.push(`<tr class="subtotal"><td colspan="5">${esc(curDesc || '(摘要なし)')} 小計 (${g.count} 件)</td>${fmtCell0(g.debit)}${fmtCell0(g.credit)}<td></td></tr>`);
    }
    rows.push(`<tr class="total"><td colspan="5">期間合計${byDesc ? '' : ' / 残高'}</td>${fmtCell0(r.total_debit)}${fmtCell0(r.total_credit)}${byDesc ? '<td></td>' : fmtCell0(r.closing)}</tr>`);
    $('#l-table tbody').innerHTML = rows.join('');
  }
  function step(dir) {
    const list = S.accounts;
    const i = list.findIndex(a => a.id === acctCombo.id);
    const n = list[i + dir];
    if (n) { acctCombo.set(n.id); fillSubs(); run(); }
  }
  $('#l-prev').onclick = () => step(-1);
  $('#l-next').onclick = () => step(1);
  subSel.onchange = run;
  $('#l-sort').onchange = run;
  bindMonthSelect('l', run);
  $('#l-csv').onclick = () => tableToCsv($('#l-table'), `元帳_${S.client.code}.csv`);
  // 行をクリックしたら、その場で修正できるダイアログを開く。
  // 修正・削除したら元帳を引き直して、残高も新しい内容で表示し直す。
  $('#l-table').addEventListener('click', (e) => {
    const tr = e.target.closest('tr[data-id]');
    if (tr) openEntryDialog(Number(tr.dataset.id), { onChanged: run, siblings: shown });
  });
  const init = params.account ? Number(params.account) : (S.accounts.find(a => a.code === '100') || S.accounts[0] || {}).id;
  if (init) { acctCombo.set(init); fillSubs(); }
  if (params.sub) subSel.value = params.sub;
  await run();
  $('#l-acct').focus({ preventScroll: true });
  return bindDrillBack();
};

// ---------------------------------------------------------------- 残高試算表
routes.tb = async function (main, params) {
  main.innerHTML = `<h2>残高試算表</h2>
  <div class="toolbar no-print">
    <div class="field"><span>科目を開く</span><input id="t-find" style="width:200px" placeholder="コード・かな・名称"></div>
    ${periodToolbar('t', { from: params.from, to: params.to })}
    <div class="field"><span>表示</span><select id="t-kind"><option value="bs">貸借対照表科目</option><option value="pl">損益計算書科目</option><option value="all">すべて</option></select></div>
    <label><input type="checkbox" id="t-sub"> 補助科目を表示</label>
    <label><input type="checkbox" id="t-zero"> 残高ゼロも表示</label>
    ${printButton()} ${csvButton('t-csv')}
  </div>
  <div class="panel"><div id="t-title"></div>
  <div class="scroll-x"><table class="grid compact sticky-head" id="t-table"><thead><tr>
    <th>コード</th><th>科目</th><th>繰越残高</th><th>借方</th><th>貸方</th><th>残高</th>
  </tr></thead><tbody></tbody></table></div></div>`;
  $('#t-kind').value = params.kind || localStorage.getItem('tbKind') || 'bs';
  // 元帳から戻ってきたときに、見ていた状態をそのまま復元する
  if (params.by_sub) $('#t-sub').checked = params.by_sub === '1';
  if (params.zero) $('#t-zero').checked = params.zero === '1';

  async function run() {
    const qs = new URLSearchParams({ date_from: $('#t-from').value, date_to: $('#t-to').value, by_sub: $('#t-sub').checked });
    const r = await GET(`/api/fiscal-years/${S.fy.id}/reports/trial-balance?${qs}`);
    const kind = $('#t-kind').value;
    localStorage.setItem('tbKind', kind);
    $('#t-title').innerHTML = reportHeader('残高試算表', `${fmtDate(r.date_from)} 〜 ${fmtDate(r.date_to)}`);
    const showZero = $('#t-zero').checked;
    const cats = kind === 'bs' ? ['asset', 'liability', 'equity'] : kind === 'pl' ? ['revenue', 'expense'] : null;
    const groups = S.meta.groups.filter(g => !cats || cats.includes(g.category)).map(g => g.grp);
    const rows = [];
    for (const grp of groups) {
      const grows = r.rows.filter(x => x.grp === grp && (showZero || x.closing !== 0 || x.debit !== 0 || x.credit !== 0 || x.opening !== 0));
      if (!grows.length) continue;
      rows.push(`<tr class="group"><td colspan="6">【${esc(grp)}】</td></tr>`);
      for (const x of grows) {
        rows.push(`<tr class="clickable" data-acct="${x.account_id}"><td class="code">${esc(x.code)}</td><td>${esc(x.name)}</td>
          ${fmtCell(x.opening_n)}${fmtCell(x.debit)}${fmtCell(x.credit)}${fmtCell0(x.closing_n)}</tr>`);
        for (const s of x.subs || []) {
          rows.push(`<tr class="sub clickable" data-acct="${x.account_id}" data-sub="${s.sub_id}"><td class="code"></td><td class="name">${esc(s.code)} ${esc(s.name)}</td>
            ${fmtCell(s.opening_n)}${fmtCell(s.debit)}${fmtCell(s.credit)}${fmtCell0(s.closing_n)}</tr>`);
        }
      }
      const t = r.totals['grp:' + grp];
      const ns = S.meta.groups.find(g => g.grp === grp).category;
      const sign = (ns === 'asset' || ns === 'expense') ? 1 : -1;
      rows.push(`<tr class="subtotal"><td></td><td>${esc(grp)} 合計</td>${fmtCell(sign * t.opening)}${fmtCell(t.debit)}${fmtCell(t.credit)}${fmtCell0(sign * t.closing)}</tr>`);
    }
    const ni = r.net_income;
    if (kind !== 'pl') {
      rows.push(`<tr class="subtotal"><td></td><td>当期純利益 (損益より)</td>${fmtCell(ni.opening)}<td></td><td></td>${fmtCell0(ni.closing)}</tr>`);
      const A = r.totals.asset || {}, L = r.totals.liability || {}, E = r.totals.equity || {};
      rows.push(`<tr class="total"><td></td><td>資産合計</td>${fmtCell(A.opening)}${fmtCell(A.debit)}${fmtCell(A.credit)}${fmtCell0(A.closing)}</tr>`);
      rows.push(`<tr class="total"><td></td><td>負債・純資産合計 (純利益含む)</td>${fmtCell(-((L.opening || 0) + (E.opening || 0)) + ni.opening)}${fmtCell((L.debit || 0) + (E.debit || 0))}${fmtCell((L.credit || 0) + (E.credit || 0))}${fmtCell0(-((L.closing || 0) + (E.closing || 0)) + ni.closing)}</tr>`);
    }
    if (kind !== 'bs') {
      rows.push(`<tr class="total"><td></td><td>当期純利益</td>${fmtCell(ni.opening)}<td></td>${fmtCell(ni.period)}${fmtCell0(ni.closing)}</tr>`);
    }
    $('#t-table tbody').innerHTML = rows.join('') || '<tr><td colspan="6" class="empty">データがありません</td></tr>';
  }
  bindMonthSelect('t', run);
  $('#t-kind').onchange = $('#t-sub').onchange = $('#t-zero').onchange = run;
  $('#t-csv').onclick = () => tableToCsv($('#t-table'), `試算表_${S.client.code}.csv`);
  $('#t-table').addEventListener('click', (e) => {
    const tr = e.target.closest('tr[data-acct]');
    if (!tr) return;
    const p = { account: tr.dataset.acct, from: $('#t-from').value, to: $('#t-to').value };
    if (tr.dataset.sub) p.sub = tr.dataset.sub;
    // 元帳から Esc で戻れるよう、いまの試算表の状態 (期間・表示・チェック) を戻り先にする
    drillDown('ledger', p, { label: '残高試算表', rowKey: tr.dataset.acct, from: stateHash() });
  });
  function stateHash() {
    const qs = new URLSearchParams({
      from: $('#t-from').value, to: $('#t-to').value, kind: $('#t-kind').value,
      by_sub: $('#t-sub').checked ? '1' : '0', zero: $('#t-zero').checked ? '1' : '0',
    });
    return `#/tb?${qs}`;
  }
  // コードを打って Enter を押すと、その科目の総勘定元帳を開く (行のクリックと同じ)
  makeCombo($('#t-find'), {
    items: () => S.accounts,
    onCommit: (it) => {
      if (!it) return;
      drillDown('ledger', { account: it.id, from: $('#t-from').value, to: $('#t-to').value },
        { label: '残高試算表', rowKey: it.id, from: stateHash() });
    },
  });
  await run();
  $('#t-find').focus({ preventScroll: true });
  restoreDrillPosition('#t-table', 'data-acct');
};

// ---------------------------------------------------------------- 月次推移表
routes.monthly = async function (main) {
  main.className = 'wide';
  main.innerHTML = `<h2>月次推移表</h2>
  <div class="toolbar no-print">
    <div class="field"><span>表示</span><select id="m-kind"><option value="pl">損益計算書科目</option><option value="bs">貸借対照表科目 (残高)</option></select></div>
    ${printButton()} ${csvButton('m-csv')}
  </div>
  <div class="panel"><div id="m-title"></div><div class="scroll-x"><table class="grid compact sticky-head" id="m-table"></table></div></div>`;
  const r = await GET(`/api/fiscal-years/${S.fy.id}/reports/monthly`);
  $('#m-title').innerHTML = reportHeader('月次推移表', `${fmtDate(S.fy.start_date)} 〜 ${fmtDate(S.fy.end_date)}`);
  function draw() {
    const kind = $('#m-kind').value;
    const cats = kind === 'pl' ? ['revenue', 'expense'] : ['asset', 'liability', 'equity'];
    const months = r.months;
    const head = `<thead><tr><th>コード</th><th style="min-width:140px">科目</th>${kind === 'bs' ? '<th>期首</th>' : ''}${months.map(m => `<th>${Number(m.slice(5))}月</th>`).join('')}<th>${kind === 'bs' ? '期末' : '合計'}</th></tr></thead>`;
    const rows = [];
    const groups = S.meta.groups.filter(g => cats.includes(g.category)).map(g => g.grp);
    for (const grp of groups) {
      const grows = r.rows.filter(x => x.grp === grp);
      if (!grows.length) continue;
      rows.push(`<tr class="group"><td colspan="${months.length + (kind === 'bs' ? 4 : 3)}">【${esc(grp)}】</td></tr>`);
      const sums = new Array(months.length).fill(0);
      let so = 0;
      for (const x of grows) {
        if (kind === 'bs') {
          let bal = x.opening;
          const cells = x.months.map(v => { bal += v; return bal; });
          rows.push(`<tr><td class="code">${esc(x.code)}</td><td>${esc(x.name)}</td>${fmtCell(x.opening)}${cells.map(fmtCell).join('')}${fmtCell0(x.closing)}</tr>`);
        } else {
          rows.push(`<tr><td class="code">${esc(x.code)}</td><td>${esc(x.name)}</td>${x.months.map(fmtCell).join('')}${fmtCell0(x.total)}</tr>`);
        }
        x.months.forEach((v, i) => { sums[i] += v; });
        so += x.opening;
      }
      if (kind === 'bs') {
        let bal = so;
        const cells = sums.map(v => { bal += v; return bal; });
        rows.push(`<tr class="subtotal"><td></td><td>${esc(grp)} 合計</td>${fmtCell(so)}${cells.map(fmtCell).join('')}${fmtCell0(bal)}</tr>`);
      } else {
        rows.push(`<tr class="subtotal"><td></td><td>${esc(grp)} 合計</td>${sums.map(fmtCell).join('')}${fmtCell0(sums.reduce((a, b) => a + b, 0))}</tr>`);
      }
    }
    if (kind === 'pl') {
      const rev = new Array(months.length).fill(0), exp = new Array(months.length).fill(0);
      for (const x of r.rows) {
        if (x.category === 'revenue') x.months.forEach((v, i) => { rev[i] += v; });
        if (x.category === 'expense') x.months.forEach((v, i) => { exp[i] += v; });
      }
      const ni = rev.map((v, i) => v - exp[i]);
      let cum = 0;
      const cumRow = ni.map(v => { cum += v; return cum; });
      rows.push(`<tr class="total"><td></td><td>当期純利益 (月次)</td>${ni.map(fmtCell).join('')}${fmtCell0(cum)}</tr>`);
      rows.push(`<tr class="total"><td></td><td>当期純利益 (累計)</td>${cumRow.map(fmtCell).join('')}${fmtCell0(cum)}</tr>`);
    }
    $('#m-table').innerHTML = head + `<tbody>${rows.join('') || '<tr><td class="empty">データがありません</td></tr>'}</tbody>`;
  }
  $('#m-kind').onchange = draw;
  $('#m-csv').onclick = () => tableToCsv($('#m-table'), `月次推移_${S.client.code}.csv`);
  draw();
};

// ---------------------------------------------------------------- 消費税集計表
routes.tax = async function (main, params) {
  main.innerHTML = `<h2>消費税集計表</h2>
  <div class="toolbar no-print">${periodToolbar('x', { from: params.from, to: params.to })}${printButton()} ${csvButton('x-csv')}</div>
  <div class="panel"><div id="x-title"></div>
  <table class="grid compact" id="x-table"><thead><tr><th>区分</th><th>名称</th><th>税率</th><th>件数</th><th>税込金額</th><th>本体金額</th><th>消費税額</th><th>控除対象税額</th></tr></thead><tbody></tbody></table>
  <div id="x-summary" style="margin-top:10px"></div>
  <p class="help">※ 内税方式で仕訳ごとに計算した消費税額の集計です (切捨て)。申告額は端数処理・積上げ計算等により異なる場合があります。</p></div>`;
  async function run() {
    const r = await GET(`/api/fiscal-years/${S.fy.id}/reports/tax-summary?date_from=${$('#x-from').value}&date_to=${$('#x-to').value}`);
    $('#x-title').innerHTML = reportHeader('消費税集計表', `${fmtDate(r.date_from)} 〜 ${fmtDate(r.date_to)}`);
    $('#x-table tbody').innerHTML = r.rows.map(x => `<tr><td class="code">${x.code}</td><td>${esc(x.name)}</td><td class="center">${x.rate ? x.rate + '%' : ''}</td>
      <td class="num">${x.count}</td>${fmtCell0(x.amount)}${fmtCell0(x.net)}${fmtCell(x.tax)}${x.kind === 'purchase' ? fmtCell(x.deductible) : '<td></td>'}</tr>`).join('')
      || '<tr><td colspan="8" class="empty">データがありません</td></tr>';
    $('#x-summary').innerHTML = `<table class="grid compact" style="width:auto"><tr><th>売上に係る消費税 (仮受)</th>${fmtCell0(r.sales_tax)}</tr>
      <tr><th>仕入に係る消費税 (仮払・控除対象)</th>${fmtCell0(r.purchase_tax)}</tr><tr class="total"><th>差引 納付(還付)税額の目安</th>${fmtCell0(r.net_tax)}</tr></table>`;
  }
  bindMonthSelect('x', run);
  $('#x-csv').onclick = () => tableToCsv($('#x-table'), `消費税集計_${S.client.code}.csv`);
  await run();
};

// ---------------------------------------------------------------- 決算書
routes.fs = async function (main, params) {
  main.innerHTML = `<h2>決算書 (貸借対照表 / 損益計算書)</h2>
  <div class="toolbar no-print">
    <div class="field"><span>基準日 (至)</span><input type="date" id="f-to" value="${params.to || S.fy.end_date}" min="${S.fy.start_date}" max="${S.fy.end_date}"></div>
    ${printButton()}
  </div>
  <div id="f-body"></div>`;
  async function run() {
    const r = await GET(`/api/fiscal-years/${S.fy.id}/reports/financial-statements?date_to=${$('#f-to').value}`);
    const bs = r.bs, pl = r.pl;
    const items = (list) => list.map(i => `<tr><td class="code">${esc(i.code)}</td><td>${esc(i.name)}</td>${fmtCell0(i.amount)}</tr>`).join('');
    const section = (s) => `<tr class="group"><td colspan="3">${esc(s.grp)}</td></tr>${items(s.items)}<tr class="subtotal"><td></td><td>${esc(s.grp)} 合計</td>${fmtCell0(s.total)}</tr>`;
    $('#f-body').innerHTML = `
    <div class="panel">${reportHeader('貸借対照表', `${fmtDate(r.date_to)} 現在`)}
      <div class="two-col">
        <table class="grid compact"><thead><tr><th colspan="3">資産の部</th></tr></thead><tbody>
          ${bs.assets.map(section).join('')}
          <tr class="total"><td></td><td>資産合計</td>${fmtCell0(bs.total_assets)}</tr></tbody></table>
        <table class="grid compact"><thead><tr><th colspan="3">負債・純資産の部</th></tr></thead><tbody>
          ${bs.liabilities.map(section).join('')}
          <tr class="subtotal"><td></td><td>負債合計</td>${fmtCell0(bs.total_liabilities)}</tr>
          ${bs.equity.map(section).join('')}
          <tr class="total"><td></td><td>負債・純資産合計</td>${fmtCell0(bs.total_liabilities_equity)}</tr></tbody></table>
      </div>
      ${bs.total_assets !== bs.total_liabilities_equity ? `<p class="neg">※ 貸借が一致していません (差額 ${fmt(bs.total_assets - bs.total_liabilities_equity)})。期首残高を確認してください。</p>` : ''}
    </div>
    <div class="panel">${reportHeader('損益計算書', `${fmtDate(S.fy.start_date)} 〜 ${fmtDate(r.date_to)}`)}
      <table class="grid compact" style="max-width:700px"><tbody>
        ${section(pl.sections[0])}${section(pl.sections[1])}
        <tr class="total"><td></td><td>売上総利益</td>${fmtCell0(pl.gross_profit)}</tr>
        ${section(pl.sections[2])}
        <tr class="total"><td></td><td>営業利益</td>${fmtCell0(pl.operating_income)}</tr>
        ${section(pl.sections[3])}${section(pl.sections[4])}
        <tr class="total"><td></td><td>経常利益</td>${fmtCell0(pl.ordinary_income)}</tr>
        ${section(pl.sections[5])}${section(pl.sections[6])}
        <tr class="total"><td></td><td>税引前当期純利益</td>${fmtCell0(pl.pretax_income)}</tr>
        ${section(pl.sections[7])}
        <tr class="total"><td></td><td>当期純利益</td>${fmtCell0(pl.net_income)}</tr>
      </tbody></table>
    </div>`;
  }
  $('#f-to').onchange = run;
  await run();
};

// ---------------------------------------------------------------- 摘要別集計
routes.descsum = async function (main, params) {
  main.innerHTML = `<h2>摘要別集計</h2>
  <div class="toolbar no-print">
    ${periodToolbar('s', { from: params.from, to: params.to })}
    <div class="field"><span>科目</span>${accountSelectHtml('s-acct')}</div>
    <div class="field"><span>検索</span><input id="s-q" style="width:160px" placeholder="摘要"></div>
    <div class="field"><span>並び順</span><select id="s-sort">
      <option value="description">摘要順</option><option value="count">件数の多い順</option>
      <option value="debit">借方の大きい順</option><option value="credit">貸方の大きい順</option></select></div>
    ${printButton()} ${csvButton('s-csv')}
  </div>
  <div class="panel"><div id="s-title"></div>
  <div class="scroll-x"><table class="grid compact sticky-head" id="s-table"><thead><tr>
    <th>摘要</th><th>件数</th><th>借方</th><th>貸方</th><th>差引</th><th>科目</th><th>期間</th>
  </tr></thead><tbody></tbody></table></div>
  <p class="help">摘要が同じ取引をまとめた集計です。売上先・仕入先を摘要に書いている場合の取引先別の確認に使えます。
  行をクリックすると、その摘要の仕訳だけを仕訳帳で表示します。</p></div>`;
  if (params.account) $('#s-acct').value = params.account;

  let data = null;
  async function load() {
    const qs = new URLSearchParams({ date_from: $('#s-from').value, date_to: $('#s-to').value });
    if ($('#s-acct').value) qs.set('account_id', $('#s-acct').value);
    data = await GET(`/api/fiscal-years/${S.fy.id}/reports/description-summary?${qs}`);
    draw();
  }
  function draw() {
    const q = $('#s-q').value.trim().toLowerCase();
    const sort = $('#s-sort').value;
    let rows = data.rows.filter(r => !q || (r.description || '').toLowerCase().includes(q));
    if (sort === 'count') rows = rows.slice().sort((a, b) => b.count - a.count);
    else if (sort === 'debit') rows = rows.slice().sort((a, b) => b.debit - a.debit);
    else if (sort === 'credit') rows = rows.slice().sort((a, b) => b.credit - a.credit);
    $('#s-title').innerHTML = reportHeader('摘要別集計',
      `${fmtDate(data.date_from)} 〜 ${fmtDate(data.date_to)}　${rows.length} 種類 / ${data.total_count} 行`
      + (data.account ? `　${data.account.code} ${data.account.name}` : ''));
    const out = rows.map(r => `<tr class="clickable" data-desc="${esc(r.description)}">
      <td>${r.description ? esc(r.description) : '<span class="muted">(摘要なし)</span>'}</td>
      <td class="num">${r.count}</td>${fmtCell(r.debit)}${fmtCell(r.credit)}${fmtCell0(r.net)}
      <td class="muted">${esc(r.accounts.join(', '))}${r.account_count > r.accounts.length ? ' ほか' : ''}</td>
      <td class="code muted">${fmtDate(r.first_date)}〜${fmtDate(r.last_date)}</td></tr>`);
    out.push(`<tr class="total"><td>合計</td><td class="num">${data.total_count}</td>
      ${fmtCell0(data.total_debit)}${fmtCell0(data.total_credit)}${fmtCell0(data.total_debit - data.total_credit)}<td></td><td></td></tr>`);
    $('#s-table tbody').innerHTML = out.join('') || '<tr><td colspan="7" class="empty">データがありません</td></tr>';
  }
  // 仕訳帳から戻ってきたときに、見ていた状態をそのまま復元する
  if (params.account) $('#s-acct').value = params.account;
  if (params.q) $('#s-q').value = params.q;
  if (params.sort) $('#s-sort').value = params.sort;
  bindMonthSelect('s', load);
  $('#s-acct').onchange = load;
  $('#s-q').oninput = () => draw();
  $('#s-sort').onchange = () => draw();
  $('#s-csv').onclick = () => tableToCsv($('#s-table'), `摘要別集計_${S.client.code}.csv`);
  $('#s-table').addEventListener('click', (e) => {
    const tr = e.target.closest('tr[data-desc]');
    if (!tr) return;
    drillDown('journal', { from: $('#s-from').value, to: $('#s-to').value, q: tr.dataset.desc, sort: 'description' },
      { label: '摘要別集計', rowKey: tr.dataset.desc, from: stateHash() });
  });
  function stateHash() {
    const qs = new URLSearchParams({
      from: $('#s-from').value, to: $('#s-to').value, account: $('#s-acct').value,
      q: $('#s-q').value, sort: $('#s-sort').value,
    });
    return `#/descsum?${qs}`;
  }
  await load();
  restoreDrillPosition('#s-table', 'data-desc');
};
