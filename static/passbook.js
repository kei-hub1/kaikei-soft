/* 通帳マスタと、通帳の写真・テキストから仕訳を起こす画面 */
'use strict';

// ---------------------------------------------------------------- 通帳マスタ
routes.passbooks = async function (main) {
  let list = [];
  let defaults = { account_id: null, counter_account_id: null };

  main.innerHTML = `<h2>通帳</h2>
  <div class="toolbar no-print">
    <button id="pb-add" class="primary">通帳を追加</button>
    <span class="muted">通帳ごとに預金科目と相手科目を決めておくと、「通帳取込」で写真から仕訳を起こせます。
      口座番号を入れておくと、写真から自動でどの通帳かを判別します。</span>
  </div>
  <div class="panel"><div class="scroll-x"><table class="grid compact" id="pb-table"><thead><tr>
    <th>名称</th><th>銀行 / 支店</th><th>種別</th><th>口座番号</th><th>預金科目</th><th>相手科目</th>
    <th>前回残高</th><th>状態</th><th></th>
  </tr></thead><tbody></tbody></table></div></div>`;

  function accountOptions(sel, filter) {
    return '<option value="">(未設定)</option>' + S.accounts.filter(a => a.active && (!filter || filter(a)))
      .map(a => `<option value="${a.id}" ${a.id === sel ? 'selected' : ''}>${esc(a.code)} ${esc(a.name)}</option>`).join('');
  }

  function form(pb) {
    const isNew = !pb;
    pb = pb || {
      code: '', name: '', bank_name: '', branch_name: '', account_type: '普通', account_number: '',
      account_id: defaults.account_id, sub_account_id: null,
      counter_account_id: defaults.counter_account_id, last_balance: null, active: 1,
    };
    const { bg } = formModal(isNew ? '通帳の追加' : '通帳の修正',
      field('名称 (画面での呼び名)', textInput('name', pb.name, 'required'), true) +
      field('コード', textInput('code', pb.code, 'maxlength="10"')) +
      field('銀行名', textInput('bank_name', pb.bank_name)) +
      field('支店名', textInput('branch_name', pb.branch_name)) +
      field('種別', selectInput('account_type', ['普通', '当座', '貯蓄', '総合'].map(v => ({ value: v, label: v })), pb.account_type)) +
      field('口座番号', textInput('account_number', pb.account_number, 'maxlength="20"')) +
      field('預金科目', `<select name="account_id" id="pb-acct">${accountOptions(pb.account_id, a => a.category === 'asset')}</select>`) +
      field('補助科目', `<select name="sub_account_id" id="pb-sub"><option value="">(なし)</option></select>`) +
      field('相手科目 (事業主借など)', `<select name="counter_account_id">${accountOptions(pb.counter_account_id)}</select>`) +
      field('前回の最終残高', `<input type="text" name="last_balance" class="num" value="${pb.last_balance != null ? fmt(pb.last_balance) : ''}">`) +
      field('有効', checkInput('active', pb.active)) +
      '<div class="field wide muted">前回の最終残高を入れておくと、次に取り込むときに 1 行目から入金・出金を判定できます。取込のたびに自動で更新されます。</div>',
      async (d) => {
        const body = {
          code: d.code.trim(), name: d.name.trim(), bank_name: d.bank_name.trim(),
          branch_name: d.branch_name.trim(), account_type: d.account_type,
          account_number: d.account_number.trim(),
          account_id: Number(d.account_id) || null,
          sub_account_id: Number($('#pb-sub', bg).value) || null,
          counter_account_id: Number(d.counter_account_id) || null,
          last_balance: String(d.last_balance).trim() ? parseAmount(d.last_balance) : null,
          active: !!d.active,
        };
        if (isNew) await POST(`/api/clients/${S.client.id}/passbooks`, body);
        else await PUT(`/api/passbooks/${pb.id}`, body);
        await load();
        toast('保存しました');
      });
    const fillSubs = (accountId, sel) => {
      const subs = (S.subsByAccount[accountId] || []).filter(s => s.active);
      $('#pb-sub', bg).innerHTML = '<option value="">(なし)</option>' +
        subs.map(s => `<option value="${s.id}" ${s.id === sel ? 'selected' : ''}>${esc(s.code)} ${esc(s.name)}</option>`).join('');
    };
    fillSubs(pb.account_id, pb.sub_account_id);
    $('#pb-acct', bg).onchange = (e) => fillSubs(Number(e.target.value) || null, null);
  }

  function draw() {
    $('#pb-table tbody').innerHTML = list.map(p => `<tr>
      <td>${esc(p.name)}${p.code ? ` <span class="muted mono">${esc(p.code)}</span>` : ''}</td>
      <td>${esc(p.bank_name)}${p.branch_name ? ' / ' + esc(p.branch_name) : ''}</td>
      <td class="center">${esc(p.account_type)}</td>
      <td class="code">${esc(p.account_number)}</td>
      <td>${p.account_code ? esc(p.account_code + ' ' + p.account_name) : '<span class="badge danger">未設定</span>'}${p.sub_account_name ? ' / ' + esc(p.sub_account_name) : ''}</td>
      <td>${p.counter_code ? esc(p.counter_code + ' ' + p.counter_name) : '<span class="badge danger">未設定</span>'}</td>
      <td class="num">${p.last_balance != null ? fmt(p.last_balance) : ''}${p.last_date ? `<br><span class="muted">${fmtDate(p.last_date)}</span>` : ''}</td>
      <td>${p.active ? '<span class="badge ok">有効</span>' : '<span class="badge">無効</span>'}</td>
      <td style="white-space:nowrap"><button class="small" data-edit="${p.id}">修正</button>
        <button class="small danger" data-del="${p.id}">削除</button></td></tr>`).join('')
      || '<tr><td colspan="9" class="empty">通帳が登録されていません。「通帳を追加」から登録してください。</td></tr>';
  }

  async function load() {
    [list, defaults] = await Promise.all([
      GET(`/api/clients/${S.client.id}/passbooks`),
      GET(`/api/clients/${S.client.id}/passbooks/defaults`),
    ]);
    draw();
  }

  $('#pb-table').onclick = async (e) => {
    const b = e.target.closest('button');
    if (!b) return;
    try {
      if (b.dataset.edit) form(list.find(p => p.id === Number(b.dataset.edit)));
      else if (b.dataset.del && await confirmDialog('この通帳を削除します。取り込んだ仕訳は残ります。よろしいですか？')) {
        await DEL(`/api/passbooks/${b.dataset.del}`);
        await load();
        toast('削除しました');
      }
    } catch (err) { showError(err); }
  };
  $('#pb-add').onclick = () => form(null);
  await load();
};

// ---------------------------------------------------------------- 通帳取込
routes.passbook = async function (main) {
  let passbooks = [];
  let engines = { engines: [], default: null };
  let formats = { accept: ['.jpg', '.png'], pdf: false, ocr: [], docuworks_installed: false, xdw_command: '' };
  let parsed = null;      // 解析結果
  let rows = [];          // 確認・修正中の行

  main.className = 'wide';
  main.innerHTML = `<h2>通帳取込</h2>
  <div class="panel">
    <div class="toolbar" style="margin-bottom:2px">
      <div class="field"><span>通帳</span><select id="pk-book" style="min-width:220px"></select></div>
      <div class="field"><span>前回の最終残高 (1 行目の判定に使う)</span><input id="pk-open" class="num" style="width:130px"></div>
      <div class="field"><span>読み取り方法</span><select id="pk-engine"></select></div>
      <div class="field"><span>ファイル (写真 / PDF / DocuWorks)</span><input type="file" id="pk-file" multiple></div>
      <button id="pk-run" class="primary">ファイルから読み取る</button>
      <button id="pk-paste">文字を貼り付けて取込</button>
    </div>
    <div id="pk-note" class="help"></div>
  </div>
  <div id="pk-result"></div>`;

  // ---- 起動時の読み込み
  try {
    [passbooks, engines, formats] = await Promise.all([
      GET(`/api/clients/${S.client.id}/passbooks`),
      GET('/api/ocr/engines'),
      GET('/api/passbook/formats'),
    ]);
    $('#pk-file').accept = formats.accept.join(',');
  } catch (e) { showError(e); }

  const bookSel = $('#pk-book');
  bookSel.innerHTML = '<option value="">(写真から自動で判別)</option>' +
    passbooks.filter(p => p.active).map(p => `<option value="${p.id}">${esc(p.name)}${p.account_number ? ` (${esc(p.account_number)})` : ''}</option>`).join('');
  bookSel.onchange = () => {
    const p = passbooks.find(x => String(x.id) === bookSel.value);
    $('#pk-open').value = p && p.last_balance != null ? fmt(p.last_balance) : '';
  };

  const engSel = $('#pk-engine');
  engSel.innerHTML = engines.engines.map(e => `<option value="${e.code}">${esc(e.name)}</option>`).join('')
    || '<option value="">(使える読み取り機能がありません)</option>';
  // 文字情報つき PDF は OCR 無しでも読めるので、常に使えるようにしておく

  const notes = [];
  if (!passbooks.length) {
    notes.push('<span class="badge danger">通帳が未登録です</span> 先に「通帳」画面で通帳を登録してください。');
  }
  notes.push(`取り込めるファイル: 写真 (${formats.accept.filter(x => x !== '.pdf' && x !== '.xdw' && x !== '.xbd').join(' ')})`
    + (formats.pdf ? '、PDF' : '') + '、DocuWorks (.xdw)');
  if (formats.pdf) {
    notes.push('<b>文字情報つきの PDF (検索可能 PDF) が最も正確です。</b> 複合機のスキャンで「検索可能PDF」を選べる場合は、それで取り込んでください。OCR を通さずそのまま読み取ります。');
  } else {
    notes.push('<span class="badge warn">PDF が読み込めません</span> start.bat を実行し直すと必要な部品が入ります。');
  }
  notes.push('<b>DocuWorks (.xdw)</b> は公開仕様が無いため、埋め込まれた画像の取り出しを試みます。'
    + '読み取れない場合は、DocuWorks で <b>PDF に書き出してから</b>取り込んでください'
    + (formats.xdw_command ? '（変換コマンドが設定されています）' : '（「データ管理」画面で変換コマンドを設定することもできます）') + '。');
  if (!engines.engines.length) {
    notes.push('<span class="badge warn">写真の読み取りが使えません</span> この環境には OCR がありません。'
      + '文字情報つき PDF か「文字を貼り付けて取込」なら使えます。Windows の場合は「設定 → 時刻と言語 → 言語と地域」で日本語の言語機能を追加すると写真からも読めるようになります。');
  } else {
    notes.push((engines.engines.find(e => e.code === engSel.value) || engines.engines[0]).note || '');
  }
  notes.push('読み取りは間違いが混じることがあります。<b>登録する前に必ず内容を確認してください。</b> 入金・出金は残高の増減から判定し、金額と合わない行には印を付けます。');
  $('#pk-note').innerHTML = notes.filter(Boolean).map(n => `<div>${n}</div>`).join('');

  // ---- 解析
  async function analyzeFiles() {
    const files = Array.from($('#pk-file').files || []);
    if (!files.length) { toast('通帳のファイルを選んでください', true); return; }
    const all = [];
    let first = null;
    $('#pk-result').innerHTML = '<div class="panel">読み取っています... しばらくお待ちください</div>';
    for (const f of files) {
      const fd = new FormData();
      fd.append('file', f);
      const qs = new URLSearchParams({ fiscal_year_id: S.fy.id });
      if (engSel.value) qs.set('engine', engSel.value);
      if (bookSel.value) qs.set('passbook_id', bookSel.value);
      const open = $('#pk-open').value.trim();
      // 2 枚目以降は前の写真の最終残高を引き継ぐ
      const carry = all.length ? lastBalanceOf(all) : (open ? parseAmount(open) : null);
      if (carry != null) qs.set('opening_balance', carry);
      try {
        const r = await api('POST', `/api/clients/${S.client.id}/passbook/analyze-file?${qs}`, fd);
        if (!first) first = r;
        all.push(r);
      } catch (e) {
        $('#pk-result').innerHTML = `<div class="panel"><span class="badge danger">エラー</span> ${esc(e.message)}</div>`;
        return;
      }
    }
    parsed = mergeParsed(all);
    showResult();
  }

  function lastBalanceOf(list) {
    for (let i = list.length - 1; i >= 0; i--) {
      const rs = list[i].rows;
      for (let j = rs.length - 1; j >= 0; j--) if (rs[j].balance != null) return rs[j].balance;
    }
    return null;
  }
  function mergeParsed(list) {
    const head = list[0];
    return {
      ...head,
      rows: list.flatMap(x => x.rows),
      skipped: list.flatMap(x => x.skipped),
      raw_text: list.map(x => x.raw_text).join('\n'),
      image_path: list.map(x => x.image_path).filter(Boolean).join(','),
      images: list.length,
    };
  }

  function openPasteDialog() {
    modal(`<h3>通帳の内容を貼り付ける</h3>
      <p class="muted" style="margin-top:0">通帳の明細を 1 行 1 取引で貼り付けてください。
      スマートフォンの文字認識やネットバンキングの明細をそのまま貼っても構いません。<br>
      例: <code>6-04-01 カ)ヤマダショウテン 330,000 1,530,000</code> (日付 摘要 取引金額 残高)</p>
      <textarea id="pk-text" style="width:100%;height:220px;font-family:var(--mono)"></textarea>
      <div class="actions"><button data-close>キャンセル</button><button class="primary" id="pk-text-run">解析する</button></div>`, {
      onOpen(bg, close) {
        $('#pk-text', bg).focus();
        $('#pk-text-run', bg).onclick = async () => {
          const text = $('#pk-text', bg).value;
          if (!text.trim()) { toast('内容を貼り付けてください', true); return; }
          const open = $('#pk-open').value.trim();
          try {
            parsed = await POST(`/api/clients/${S.client.id}/passbook/analyze-text`, {
              text, fiscal_year_id: S.fy.id,
              passbook_id: Number(bookSel.value) || null,
              opening_balance: open ? parseAmount(open) : null,
            });
            parsed.source = 'text';
            close();
            showResult();
          } catch (e) { showError(e); }
        };
      },
    });
  }

  // ---- 確認画面
  function showResult() {
    rows = parsed.rows.map((r, i) => ({ ...r, no: i + 1, use: !!(r.date && r.amount && r.direction) }));
    const pb = parsed.passbook;
    // 判別できた通帳と、実際に使った前回残高を画面に反映しておく
    if (pb && !bookSel.value) bookSel.value = pb.id;
    if (parsed.opening_balance != null) $('#pk-open').value = fmt(parsed.opening_balance);
    const matched = pb
      ? `<span class="badge ok">${esc(pb.name)}</span> ${parsed.matched_by ? `(${esc(parsed.matched_by)}で判別)` : ''}`
      : '<span class="badge danger">通帳を判別できませんでした</span> 上の「通帳」欄で選んでください。';
    const info = parsed.account || {};
    const infoText = [info.bank_name, info.branch_name, info.account_type, info.account_number]
      .filter(Boolean).join(' ');

    $('#pk-result').innerHTML = `
    <div class="panel">
      <div class="row between" style="margin-bottom:6px">
        <div>読み取った通帳: ${matched}${infoText ? `　<span class="muted">記載: ${esc(infoText)}</span>` : ''}
          ${parsed.method ? `　<span class="badge">${esc(parsed.method)}</span>` : ''}</div>
        <div id="pk-summary" class="muted"></div>
      </div>
      <div class="toolbar" style="margin-bottom:4px">
        <button id="pk-all">すべて選ぶ</button>
        <button id="pk-none">すべて外す</button>
        <button id="pk-ok-only">問題のない行だけ選ぶ</button>
        <span style="flex:1"></span>
        <label><input type="checkbox" id="pk-dup" checked> 登録済みと同じ行は飛ばす</label>
        <button id="pk-register" class="primary">選んだ行を仕訳にする</button>
      </div>
      <div class="scroll-x"><table class="grid compact sticky-head" id="pk-table"><thead><tr>
        <th style="width:40px">取込</th><th style="width:36px">#</th><th style="width:120px">日付</th>
        <th style="width:90px">入出金</th><th style="width:110px">金額</th><th style="width:110px">残高</th>
        <th>摘要</th><th style="width:260px">確認事項</th>
      </tr></thead><tbody></tbody></table></div>
      ${parsed.method_note ? `<div class="help">${esc(parsed.method_note)}</div>` : ''}
      ${parsed.skipped && parsed.skipped.length ? `<details style="margin-top:8px"><summary class="muted">読み飛ばした行 (${parsed.skipped.length})</summary>
        <div class="mono" style="font-size:11px;white-space:pre-wrap">${esc(parsed.skipped.join('\n'))}</div></details>` : ''}
    </div>`;

    drawRows();
    $('#pk-table').addEventListener('input', onEdit);
    $('#pk-table').addEventListener('change', onEdit);
    $('#pk-all').onclick = () => { rows.forEach(r => { r.use = true; }); drawRows(); };
    $('#pk-none').onclick = () => { rows.forEach(r => { r.use = false; }); drawRows(); };
    $('#pk-ok-only').onclick = () => { rows.forEach(r => { r.use = !r.issues.length && !!r.date && !!r.amount && !!r.direction; }); drawRows(); };
    $('#pk-register').onclick = register;
  }

  function drawRows() {
    $('#pk-table tbody').innerHTML = rows.map(r => `<tr data-i="${r.no - 1}" class="${r.issues.length ? 'warnrow' : ''}">
      <td class="center"><input type="checkbox" data-f="use" ${r.use ? 'checked' : ''}></td>
      <td class="rowno center muted">${r.no}</td>
      <td><input type="date" data-f="date" value="${r.date || ''}" min="${S.fy.start_date}" max="${S.fy.end_date}"></td>
      <td><select data-f="direction">
        <option value="">(未定)</option>
        <option value="in">入金</option><option value="out">出金</option></select></td>
      <td><input class="num" data-f="amount" value="${r.amount != null ? fmt(r.amount) : ''}"></td>
      <td class="num muted">${r.balance != null ? fmt(r.balance) : ''}</td>
      <td><input data-f="description" value="${esc(r.description || '')}"></td>
      <td class="muted" style="font-size:11.5px">${r.issues.map(i => `<div class="neg">${esc(i)}</div>`).join('')}
        ${r.source ? `<div title="${esc(r.source)}" class="mono" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:250px">${esc(r.source)}</div>` : ''}</td>
    </tr>`).join('') || '<tr><td colspan="8" class="empty">読み取れた明細がありません</td></tr>';
    for (const tr of $$('#pk-table tbody tr[data-i]')) {
      tr.querySelector('[data-f=direction]').value = rows[Number(tr.dataset.i)].direction || '';
    }
    updateSummary();
  }

  function onEdit(e) {
    const tr = e.target.closest('tr[data-i]');
    if (!tr || !e.target.dataset.f) return;
    const r = rows[Number(tr.dataset.i)];
    const f = e.target.dataset.f;
    if (f === 'use') r.use = e.target.checked;
    else if (f === 'amount') r.amount = parseAmount(e.target.value) || null;
    else r[f] = e.target.value;
    updateSummary();
  }

  function updateSummary() {
    const sel = rows.filter(r => r.use);
    const inSum = sel.filter(r => r.direction === 'in').reduce((a, r) => a + (r.amount || 0), 0);
    const outSum = sel.filter(r => r.direction === 'out').reduce((a, r) => a + (r.amount || 0), 0);
    const bad = sel.filter(r => !r.date || !r.amount || !r.direction).length;
    $('#pk-summary').innerHTML = `選択 ${sel.length} / ${rows.length} 行　入金 ${fmt(inSum)}　出金 ${fmt(outSum)}`
      + (bad ? `　<span class="badge danger">未入力 ${bad} 行</span>` : '');
  }

  async function register() {
    const pbId = Number(bookSel.value) || (parsed.passbook && parsed.passbook.id);
    if (!pbId) { toast('どの通帳か選んでください', true); return; }
    const sel = rows.filter(r => r.use);
    if (!sel.length) { toast('取り込む行を選んでください', true); return; }
    const bad = sel.find(r => !r.date || !r.amount || !r.direction);
    if (bad) { toast(`${bad.no} 行目: 日付・金額・入出金を入力してください`, true); return; }
    const pb = passbooks.find(p => p.id === pbId);
    if (pb && (!pb.account_id || !pb.counter_account_id)) {
      toast('この通帳に預金科目と相手科目を設定してください (通帳画面)', true);
      return;
    }
    if (!(await confirmDialog(`${sel.length} 行を仕訳にします。よろしいですか？`))) return;

    const lastBal = [...rows].reverse().find(r => r.balance != null);
    try {
      const r = await POST(`/api/clients/${S.client.id}/passbook/register`, {
        passbook_id: pbId,
        rows: sel.map(x => ({ entry_date: x.date, description: x.description || '', amount: x.amount, direction: x.direction })),
        image_path: parsed.image_path || '', ocr_engine: parsed.ocr_engine || '',
        raw_text: parsed.raw_text || '', source: parsed.source || 'image',
        last_balance: lastBal ? lastBal.balance : null,
        skip_duplicates: $('#pk-dup').checked,
      });
      toast(`${r.created} 件の仕訳を登録しました${r.skipped ? ` (登録済みのため ${r.skipped} 件は飛ばしました)` : ''}`);
      passbooks = await GET(`/api/clients/${S.client.id}/passbooks`);
      $('#pk-result').innerHTML = `<div class="panel">
        <span class="badge ok">登録しました</span> ${r.created} 件の仕訳を作成しました。
        ${r.skipped ? `<div class="muted" style="margin-top:6px">登録済みと同じ内容だったため ${r.skipped} 件は飛ばしました。</div>` : ''}
        <div style="margin-top:10px"><a class="btn" href="#/journal">仕訳帳で確認する</a></div></div>`;
      await loadImports();
    } catch (e) { showError(e); }
  }

  // ---- 取込履歴
  async function loadImports() {
    let imports = [];
    try { imports = await GET(`/api/clients/${S.client.id}/passbook/imports?limit=30`); } catch (e) { return; }
    let box = $('#pk-history');
    if (!box) {
      box = el('<div class="panel" id="pk-history"></div>');
      main.appendChild(box);
    }
    box.innerHTML = `<h3 style="margin-top:0">取込履歴</h3>
      <div class="scroll-x"><table class="grid compact"><thead><tr>
        <th>日時</th><th>通帳</th><th>方法</th><th>仕訳</th><th></th></tr></thead><tbody>
      ${imports.map(i => `<tr><td class="code">${esc(i.created_at.replace('T', ' '))}</td>
        <td>${esc(i.passbook_name || '')}</td>
        <td>${i.source === 'text' ? '貼り付け' : '写真'}${i.ocr_engine ? ` <span class="muted">${esc(i.ocr_engine)}</span>` : ''}</td>
        <td class="num">${i.entry_count}</td>
        <td style="white-space:nowrap"><button class="small danger" data-undo="${i.id}" ${i.entry_count ? '' : 'disabled'}>仕訳ごと取消</button>
          <button class="small" data-forget="${i.id}">履歴だけ削除</button></td></tr>`).join('')
      || '<tr><td colspan="5" class="empty">取込履歴はありません</td></tr>'}
      </tbody></table></div>`;
    box.onclick = async (e) => {
      const b = e.target.closest('button');
      if (!b) return;
      try {
        if (b.dataset.undo) {
          if (!(await confirmDialog('この取込で作った仕訳をまとめて削除します。よろしいですか？'))) return;
          await DEL(`/api/passbook/imports/${b.dataset.undo}?with_entries=true`);
          toast('取り消しました');
        } else if (b.dataset.forget) {
          await DEL(`/api/passbook/imports/${b.dataset.forget}`);
          toast('履歴を削除しました');
        }
        await loadImports();
      } catch (err) { showError(err); }
    };
  }

  $('#pk-run').onclick = analyzeFiles;
  $('#pk-paste').onclick = openPasteDialog;
  engSel.onchange = () => {
    const e = engines.engines.find(x => x.code === engSel.value);
    if (e) $('#pk-note').firstElementChild.innerHTML = e.note || '';
  };
  bookSel.onchange();
  await loadImports();
};
