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
  // 編集中の行データ。id が null の行は新規追加。
  let rows = [];
  let deleted = [];
  let dirty = false;

  function snapshot() {
    return S.accounts.map(a => ({
      id: a.id, code: a.code, name: a.name, kana: a.kana, grp: a.grp,
      default_tax_class: a.default_tax_class, role: a.role, sort_order: a.sort_order,
      active: !!a.active, sub_count: (S.subsByAccount[a.id] || []).length,
    }));
  }

  main.className = 'wide';
  main.innerHTML = `<h2>勘定科目 / 補助科目</h2>
  <div class="toolbar no-print">
    <div class="field"><span>検索</span><input id="a-q" style="width:170px" placeholder="コード・名称・かな"></div>
    <div class="field"><span>表示区分</span><select id="a-grp"><option value="">(すべて)</option>${S.meta.groups.map(g => `<option>${esc(g.grp)}</option>`).join('')}</select></div>
    <label><input type="checkbox" id="a-inactive" checked> 無効科目も表示</label>
    <button id="a-add">行を追加</button>
    <button id="a-renumber" title="表示区分とコード順に並び順を振り直します">並び順を整理</button>
    <span style="flex:1"></span>
    <button id="a-chart">科目表を入れ替える</button>
    <button id="a-import">CSV 取込</button>
    <button id="a-copy">他の顧問先から複写</button>
    <a class="btn" href="/api/clients/${S.client.id}/export/accounts.csv">CSV 出力</a>
    <button id="a-save" class="primary">変更を保存</button>
  </div>
  <div id="a-todo"></div>
  <div class="panel" style="padding-top:6px">
    <div class="row between" style="margin-bottom:4px">
      <span class="muted">コード・科目名はそのまま書き換えられます。仕訳は科目 ID で結び付いているため、コードを変えても過去の入力は失われません。</span>
      <span id="a-status" class="muted"></span>
    </div>
    <div class="scroll-x"><table class="grid compact sticky-head" id="a-table"><thead><tr>
      <th style="width:90px">コード</th><th style="width:200px">科目名</th><th style="width:150px">かな</th>
      <th style="width:170px">表示区分</th><th style="width:160px">既定の税区分</th><th style="width:150px">役割</th>
      <th style="width:70px">並び順</th><th style="width:60px">有効</th><th style="width:110px">補助科目</th><th style="width:50px"></th>
    </tr></thead><tbody></tbody></table></div>
  </div>`;

  const grpOptions = S.meta.groups.map(g => `<option value="${esc(g.grp)}">${esc(g.grp)}</option>`).join('');
  const taxOptions = S.meta.tax_classes.map(t => `<option value="${t.code}">${t.code} ${esc(t.name)}</option>`).join('');
  const roleOptions = (S.meta.roles || [{ code: '', name: '(なし)' }])
    .map(r => `<option value="${r.code}">${esc(r.name)}</option>`).join('');

  function markDirty() {
    dirty = true;
    $('#a-status').innerHTML = '<span class="badge warn">未保存の変更があります</span>';
  }
  function clearDirty() {
    dirty = false;
    deleted = [];
    $('#a-status').textContent = '';
  }

  function visible() {
    const q = $('#a-q').value.trim().toLowerCase();
    const grp = $('#a-grp').value;
    const inactive = $('#a-inactive').checked;
    return rows.filter(r => {
      if (!inactive && !r.active) return false;
      if (grp && r.grp !== grp) return false;
      if (q && !((r.code || '').toLowerCase().includes(q) || (r.name || '').toLowerCase().includes(q) || (r.kana || '').includes(q))) return false;
      return true;
    });
  }

  function draw() {
    const list = visible();
    const out = [];
    let lastGrp = null;
    for (const r of list) {
      if (r.grp !== lastGrp) { out.push(`<tr class="group"><td colspan="10">【${esc(r.grp)}】</td></tr>`); lastGrp = r.grp; }
      const i = rows.indexOf(r);
      out.push(`<tr data-i="${i}">
        <td><input class="code" data-f="code" value="${esc(r.code)}" maxlength="10"></td>
        <td><input data-f="name" value="${esc(r.name)}"></td>
        <td><input data-f="kana" value="${esc(r.kana || '')}"></td>
        <td><select data-f="grp">${grpOptions}</select></td>
        <td><select data-f="default_tax_class">${taxOptions}</select></td>
        <td><select data-f="role">${roleOptions}</select></td>
        <td><input class="num" data-f="sort_order" value="${r.sort_order}"></td>
        <td class="center"><input type="checkbox" data-f="active" ${r.active ? 'checked' : ''}></td>
        <td class="center">${r.id === null ? '<span class="muted">保存後に設定</span>'
          : `<button class="small" data-subs="${r.id}">${r.sub_count} 件 編集</button>`}</td>
        <td class="center"><button class="small danger" data-del="${i}" title="この行を削除">×</button></td>
      </tr>`);
    }
    $('#a-table tbody').innerHTML = out.join('') || '<tr><td colspan="10" class="empty">該当する科目がありません</td></tr>';
    // select の初期値は value 属性では指定できないので個別に設定する
    for (const tr of $$('#a-table tbody tr[data-i]')) {
      const r = rows[Number(tr.dataset.i)];
      tr.querySelector('[data-f=grp]').value = r.grp;
      tr.querySelector('[data-f=default_tax_class]').value = r.default_tax_class;
      tr.querySelector('[data-f=role]').value = r.role || '';
    }
    $('#a-status').innerHTML = dirty ? '<span class="badge warn">未保存の変更があります</span>'
      : `<span class="muted">${rows.length} 科目</span>`;
    drawTodo();
  }

  /** コードが未確認の暫定科目と、不足している役割を知らせる。 */
  function drawTodo() {
    const prefix = S.meta.provisional_prefix || 'Z';
    const prov = rows.filter(r => String(r.code).startsWith(prefix));
    const roles = new Set(rows.filter(r => r.active).map(r => r.role).filter(Boolean));
    const missing = [];
    if (S.client.tax_method === 'exclusive') {
      for (const c of ['tax_receivable', 'tax_payable']) if (!roles.has(c)) missing.push(c);
    }
    missing.push(...(S.client.entity_type === 'sole' ? ['owner_capital'] : ['retained']).filter(c => !roles.has(c)));
    const roleName = (c) => ((S.meta.roles || []).find(r => r.code === c) || {}).name || c;

    const parts = [];
    if (prov.length) {
      parts.push(`<div><b>コードが未確認の科目が ${prov.length} 件あります。</b>
        TKC のコードが分かり次第、下の一覧でコードと科目名を書き換えてください。<br>
        ${prov.map(r => `<span class="mono">${esc(r.code)}</span> ${esc(r.name)}`).join(' / ')}</div>`);
    }
    if (missing.length) {
      parts.push(`<div><b>役割が設定されていない科目があります。</b>
        ${missing.map(c => esc(roleName(c))).join('、')} の役割を持つ科目が必要です。
        該当する科目の「役割」欄で選んでください。</div>`);
    }
    $('#a-todo').innerHTML = parts.length
      ? `<div class="panel" style="border-color:#f59e0b;background:var(--warn-bg)">${parts.join('<div style="height:6px"></div>')}</div>` : '';
  }

  $('#a-table').addEventListener('input', (e) => {
    const tr = e.target.closest('tr[data-i]');
    if (!tr || !e.target.dataset.f) return;
    const r = rows[Number(tr.dataset.i)];
    const f = e.target.dataset.f;
    if (f === 'active') r[f] = e.target.checked;
    else if (f === 'sort_order') r[f] = parseAmount(e.target.value);
    else r[f] = e.target.value;
    markDirty();
  });
  $('#a-table').addEventListener('change', (e) => {
    const tr = e.target.closest('tr[data-i]');
    if (!tr || !e.target.dataset.f) return;
    const r = rows[Number(tr.dataset.i)];
    const f = e.target.dataset.f;
    r[f] = f === 'active' ? e.target.checked : e.target.value;
    markDirty();
    if (f === 'grp') draw();   // 表示区分が変わると並ぶ位置が変わる
  });
  $('#a-table').addEventListener('click', async (e) => {
    const b = e.target.closest('button');
    if (!b) return;
    if (b.dataset.del !== undefined) {
      const i = Number(b.dataset.del);
      const r = rows[i];
      if (r.id !== null && !(await confirmDialog(`${r.code} ${r.name} を削除します。仕訳で使用されている科目は削除できません。よろしいですか？`))) return;
      if (r.id !== null) deleted.push(r.id);
      rows.splice(i, 1);
      markDirty();
      draw();
    } else if (b.dataset.subs) {
      openSubs(Number(b.dataset.subs));
    }
  });

  $('#a-add').onclick = () => {
    const grp = $('#a-grp').value || '販売費及び一般管理費';
    const max = rows.filter(r => r.grp === grp).reduce((m, r) => Math.max(m, Number(r.sort_order) || 0), 0);
    rows.push({ id: null, code: '', name: '', kana: '', grp, default_tax_class: '00', role: '', sort_order: max + 1, active: true, sub_count: 0 });
    markDirty();
    draw();
    const trs = $$('#a-table tbody tr[data-i]');
    const last = trs[trs.length - 1];
    if (last) last.querySelector('[data-f=code]').focus();
  };
  $('#a-renumber').onclick = () => {
    const order = Object.fromEntries(S.meta.groups.map((g, i) => [g.grp, i]));
    rows.sort((a, b) => (order[a.grp] - order[b.grp]) || String(a.code).localeCompare(String(b.code)));
    rows.forEach((r, i) => { r.sort_order = (i + 1) * 10; });
    markDirty();
    draw();
    toast('表示区分とコード順に並び順を振り直しました。保存してください');
  };

  $('#a-save').onclick = async () => {
    const dup = {};
    for (const r of rows) {
      const code = String(r.code).trim();
      if (!code || !String(r.name).trim()) { toast('コードと科目名は必須です', true); return; }
      if (dup[code]) { toast(`コード ${code} が重複しています`, true); return; }
      dup[code] = true;
    }
    try {
      const body = {
        items: rows.map(r => ({
          id: r.id, code: String(r.code).trim(), name: String(r.name).trim(), kana: String(r.kana || '').trim(),
          grp: r.grp, default_tax_class: r.default_tax_class, role: r.role || '',
          sort_order: Number(r.sort_order) || 0, active: !!r.active,
        })),
        delete_ids: deleted,
      };
      const res = await PUT(`/api/clients/${S.client.id}/accounts/bulk`, body);
      await loadAccounts();
      rows = snapshot();
      clearDirty();
      draw();
      toast(`保存しました (追加 ${res.created} / 更新 ${res.updated} / 削除 ${res.deleted})`);
    } catch (e) { showError(e); }
  };

  // ---------------------------------------------------------------- 補助科目
  function openSubs(accountId) {
    const acct = S.accountById[accountId];
    modal(`<h3>${esc(acct.code)} ${esc(acct.name)} の補助科目</h3>
      <table class="grid compact" id="sub-table"><thead><tr><th style="width:80px">コード</th><th>名称</th><th style="width:140px">かな</th><th style="width:60px">有効</th><th style="width:40px"></th></tr></thead><tbody></tbody></table>
      <div class="row" style="margin-top:8px"><button id="sub-add">行を追加</button></div>
      <div class="actions"><button data-close>閉じる</button><button class="primary" id="sub-save">保存</button></div>`, {
      onOpen(bg, close) {
        const list = (S.subsByAccount[accountId] || []).map(s => ({ ...s }));
        const removed = [];
        const drawSubs = () => {
          $('#sub-table tbody', bg).innerHTML = list.map((s, i) => `<tr data-i="${i}">
            <td><input class="code" data-f="code" value="${esc(s.code)}" maxlength="10"></td>
            <td><input data-f="name" value="${esc(s.name)}"></td>
            <td><input data-f="kana" value="${esc(s.kana || '')}"></td>
            <td class="center"><input type="checkbox" data-f="active" ${s.active ? 'checked' : ''}></td>
            <td class="center"><button class="small danger" data-del="${i}">×</button></td></tr>`).join('')
            || '<tr><td colspan="5" class="empty">補助科目はありません</td></tr>';
        };
        const onEdit = (e) => {
          const tr = e.target.closest('tr[data-i]');
          if (!tr || !e.target.dataset.f) return;
          const s = list[Number(tr.dataset.i)];
          s[e.target.dataset.f] = e.target.dataset.f === 'active' ? e.target.checked : e.target.value;
        };
        $('#sub-table', bg).addEventListener('input', onEdit);
        $('#sub-table', bg).addEventListener('change', onEdit);
        $('#sub-table', bg).addEventListener('click', (e) => {
          const b = e.target.closest('[data-del]');
          if (!b) return;
          const i = Number(b.dataset.del);
          if (list[i].id) removed.push(list[i].id);
          list.splice(i, 1);
          drawSubs();
        });
        $('#sub-add', bg).onclick = () => {
          list.push({ id: null, code: String(list.length + 1), name: '', kana: '', active: true });
          drawSubs();
          const trs = $$('#sub-table tbody tr[data-i]', bg);
          const last = trs[trs.length - 1];
          if (last) last.querySelector('[data-f=name]').focus();
        };
        $('#sub-save', bg).onclick = async () => {
          for (const s of list) {
            if (!String(s.code).trim() || !String(s.name).trim()) { toast('コードと名称は必須です', true); return; }
          }
          try {
            for (const id of removed) await DEL(`/api/sub-accounts/${id}`);
            for (const s of list) {
              const body = { code: String(s.code).trim(), name: String(s.name).trim(), kana: String(s.kana || '').trim(), active: !!s.active };
              if (s.id) await PUT(`/api/sub-accounts/${s.id}`, body);
              else await POST(`/api/accounts/${accountId}/sub-accounts`, body);
            }
            await loadAccounts();
            rows = snapshot();
            draw();
            close();
            toast('補助科目を保存しました');
          } catch (e) { showError(e); }
        };
        drawSubs();
      },
    });
  }

  // ------------------------------------------------- 用意された科目表を適用
  $('#a-chart').onclick = () => {
    const charts = (S.meta.charts || []).filter(c => c.code !== 'none');
    modal(`<h3>科目表を入れ替える</h3>
      <p class="muted" style="margin-top:0">既にある顧問先に、用意された科目表を後から適用します。
      コードが一致する科目は名称などが上書きされるだけなので、入力済みの仕訳は失われません。</p>
      <div class="form">
        <label class="field wide"><span>適用する科目表</span>
          <select id="chart-chart">${charts.map(c => `<option value="${c.code}">${esc(c.name)}</option>`).join('')}</select></label>
        <label class="field wide"><span>適用方法</span>
          <select id="chart-mode">
            <option value="merge">追加・更新のみ (今ある科目はそのまま残す)</option>
            <option value="replace">入れ替える (科目表に無い既存科目は削除または無効化)</option>
          </select></label>
      </div>
      <div id="chart-result" style="margin-top:10px"></div>
      <div class="actions"><button data-close>キャンセル</button><button class="primary" id="chart-run">適用</button></div>`, {
      onOpen(bg, close) {
        $('#chart-run', bg).onclick = async () => {
          const chart = $('#chart-chart', bg).value;
          const mode = $('#chart-mode', bg).value;
          const label = (charts.find(c => c.code === chart) || {}).name || chart;
          const msg = mode === 'replace'
            ? `「${label}」で科目表を入れ替えます。科目表に無い既存科目は削除され、仕訳で使用中のものは無効化されます。よろしいですか？`
            : `「${label}」の科目を追加・更新します。よろしいですか？`;
          if (!(await confirmDialog(msg))) return;
          try {
            const r = await POST(`/api/clients/${S.client.id}/accounts/apply-chart?chart=${chart}&mode=${mode}`);
            await loadAccounts();
            rows = snapshot();
            clearDirty();
            draw();
            close();
            toast(`適用しました (追加 ${r.created} / 更新 ${r.updated} / 削除 ${r.deleted} / 無効化 ${r.deactivated})`);
          } catch (e) { showError(e); }
        };
      },
    });
  };

  // ---------------------------------------------------------------- CSV 取込
  $('#a-import').onclick = () => {
    modal(`<h3>勘定科目 CSV の取込</h3>
      <p class="muted" style="margin-top:0">列: コード, 科目名, かな, 表示区分, 既定の税区分, 役割, 並び順, 有効<br>
      「コード」で既存の科目と照合します。文字コードは UTF-8 / Shift_JIS のどちらでも構いません。</p>
      <div class="form">
        <label class="field wide"><span>CSV ファイル</span><input type="file" id="ai-file" accept=".csv,text/csv"></label>
        <label class="field wide"><span>取込方法</span>
          <select id="ai-mode">
            <option value="merge">追加・更新のみ (CSV に無い既存科目はそのまま残す)</option>
            <option value="replace">CSV の内容に置き換える (CSV に無い既存科目は削除または無効化)</option>
          </select></label>
      </div>
      <div id="ai-result" style="margin-top:10px"></div>
      <div class="actions">
        <a class="btn" href="/api/export/accounts-template.csv" style="margin-right:auto">記入例をダウンロード</a>
        <button data-close>閉じる</button><button id="ai-check">内容を確認</button><button class="primary" id="ai-run">取込</button>
      </div>`, {
      onOpen(bg) {
        const res = $('#ai-result', bg);
        const send = async (dry) => {
          const f = $('#ai-file', bg).files[0];
          if (!f) { toast('CSV ファイルを選択してください', true); return; }
          const fd = new FormData();
          fd.append('file', f);
          res.innerHTML = '処理中...';
          try {
            const mode = $('#ai-mode', bg).value;
            const r = await api('POST', `/api/clients/${S.client.id}/import/accounts?mode=${mode}&dry_run=${dry}`, fd);
            const warn = (r.warnings || []).map(w => `<div class="badge danger" style="display:block;margin-top:4px">${esc(w)}</div>`).join('');
            const names = [];
            if (r.deleted_names && r.deleted_names.length) names.push(`削除: ${r.deleted_names.map(esc).join(', ')}`);
            if (r.deactivated_names && r.deactivated_names.length) names.push(`無効化 (仕訳で使用中): ${r.deactivated_names.map(esc).join(', ')}`);
            res.innerHTML = `<span class="badge ok">${dry ? '確認' : '取込完了'}</span>
              追加 ${r.created} / 更新 ${r.updated} / 削除 ${r.deleted} / 無効化 ${r.deactivated}${r.kept ? ` / 変更なし ${r.kept}` : ''}
              ${names.length ? `<div class="muted" style="margin-top:4px">${names.join('<br>')}</div>` : ''}${warn}`;
            if (!dry) {
              await loadAccounts();
              rows = snapshot();
              clearDirty();
              draw();
              toast(`科目表を取り込みました (追加 ${r.created} / 更新 ${r.updated})`);
            }
          } catch (e) {
            res.innerHTML = `<span class="badge danger">エラー</span> ${esc(e.message)}`;
          }
        };
        $('#ai-check', bg).onclick = () => send(true);
        $('#ai-run', bg).onclick = async () => {
          if (await confirmDialog('CSV の内容で科目表を更新します。よろしいですか？')) await send(false);
        };
      },
    });
  };

  // ---------------------------------------------------------------- 他顧問先から複写
  $('#a-copy').onclick = () => {
    const others = S.clients.filter(c => c.id !== S.client.id);
    if (!others.length) { toast('複写元にできる顧問先がありません', true); return; }
    modal(`<h3>他の顧問先から科目表を複写</h3>
      <p class="muted" style="margin-top:0">事務所共通の科目表を 1 件の顧問先で整えておき、他の顧問先へ複写できます。</p>
      <div class="form">
        <label class="field wide"><span>複写元の顧問先</span>
          <select id="ac-src">${others.map(c => `<option value="${c.id}">${esc(c.code)} ${esc(c.name)}</option>`).join('')}</select></label>
        <label class="field wide"><span>複写方法</span>
          <select id="ac-mode">
            <option value="merge">追加・更新のみ</option>
            <option value="replace">複写元に無い科目は削除または無効化する</option>
          </select></label>
        <label class="field wide"><input type="checkbox" id="ac-subs"> 補助科目も複写する</label>
      </div>
      <div class="actions"><button data-close>キャンセル</button><button class="primary" id="ac-run">複写</button></div>`, {
      onOpen(bg, close) {
        $('#ac-run', bg).onclick = async () => {
          const src = $('#ac-src', bg).value;
          const mode = $('#ac-mode', bg).value;
          const subs = $('#ac-subs', bg).checked;
          if (!(await confirmDialog('選択した顧問先の科目表を複写します。よろしいですか？'))) return;
          try {
            const r = await POST(`/api/clients/${S.client.id}/accounts/copy-from/${src}?mode=${mode}&with_subs=${subs}`);
            await loadAccounts();
            rows = snapshot();
            clearDirty();
            draw();
            close();
            toast(`複写しました (追加 ${r.created} / 更新 ${r.updated} / 削除 ${r.deleted} / 無効化 ${r.deactivated}${r.sub_accounts ? ` / 補助 ${r.sub_accounts}` : ''})`);
          } catch (e) { showError(e); }
        };
      },
    });
  };

  $('#a-q').oninput = $('#a-grp').onchange = $('#a-inactive').onchange = draw;

  const warnUnsaved = (e) => { if (dirty) { e.preventDefault(); e.returnValue = ''; } };
  window.addEventListener('beforeunload', warnUnsaved);

  rows = snapshot();
  draw();
  return () => window.removeEventListener('beforeunload', warnUnsaved);
};

// ---------------------------------------------------------------- 摘要プリセット
routes.descriptions = async function (main) {
  let rows = [];
  let removed = [];
  let dirty = false;

  const snapshot = () => S.descriptions.map(d => ({
    id: d.id, code: d.code, text: d.text, kana: d.kana,
    account_id: d.account_id, sort_order: d.sort_order, active: !!d.active,
  }));

  main.innerHTML = `<h2>摘要</h2>
  <div class="toolbar no-print">
    <div class="field"><span>検索</span><input id="d-q" style="width:180px" placeholder="コード・摘要・かな"></div>
    <button id="d-add">行を追加</button>
    <button id="d-history">過去の仕訳から取り込む</button>
    <span style="flex:1"></span>
    <button id="d-import">CSV 取込</button>
    <a class="btn" href="/api/clients/${S.client.id}/export/descriptions.csv">CSV 出力</a>
    <button id="d-save" class="primary">変更を保存</button>
  </div>
  <div class="panel" style="padding-top:6px">
    <div class="row between" style="margin-bottom:4px">
      <span class="muted">よく使う摘要 (売上先・仕入先など) を登録しておくと、仕訳入力の摘要欄で呼び出せます。
        コードを付けておくと、そのコードを打って <kbd>Enter</kbd> で本文に展開されます。</span>
      <span id="d-status" class="muted"></span>
    </div>
    <div class="scroll-x"><table class="grid compact sticky-head" id="d-table"><thead><tr>
      <th style="width:80px">コード</th><th style="width:280px">摘要</th><th style="width:180px">かな</th>
      <th style="width:200px">関連科目</th><th style="width:70px">並び順</th><th style="width:60px">有効</th><th style="width:50px"></th>
    </tr></thead><tbody></tbody></table></div>
  </div>`;

  const acctOptions = '<option value="">(なし)</option>' +
    S.accounts.filter(a => a.active).map(a => `<option value="${a.id}">${esc(a.code)} ${esc(a.name)}</option>`).join('');

  function markDirty() { dirty = true; $('#d-status').innerHTML = '<span class="badge warn">未保存の変更があります</span>'; }
  function clearDirty() { dirty = false; removed = []; $('#d-status').textContent = ''; }

  function draw() {
    const q = $('#d-q').value.trim().toLowerCase();
    const list = rows.filter(r => !q || (r.code || '').toLowerCase().includes(q)
      || (r.text || '').toLowerCase().includes(q) || (r.kana || '').includes(q));
    $('#d-table tbody').innerHTML = list.map(r => {
      const i = rows.indexOf(r);
      return `<tr data-i="${i}">
        <td><input class="code" data-f="code" value="${esc(r.code || '')}" maxlength="10"></td>
        <td><input data-f="text" value="${esc(r.text)}"></td>
        <td><input data-f="kana" value="${esc(r.kana || '')}"></td>
        <td><select data-f="account_id">${acctOptions}</select></td>
        <td><input class="num" data-f="sort_order" value="${r.sort_order}"></td>
        <td class="center"><input type="checkbox" data-f="active" ${r.active ? 'checked' : ''}></td>
        <td class="center"><button class="small danger" data-del="${i}">×</button></td></tr>`;
    }).join('') || '<tr><td colspan="7" class="empty">摘要が登録されていません。「行を追加」または「過去の仕訳から取り込む」で登録してください。</td></tr>';
    for (const tr of $$('#d-table tbody tr[data-i]')) {
      tr.querySelector('[data-f=account_id]').value = rows[Number(tr.dataset.i)].account_id || '';
    }
    if (!dirty) $('#d-status').innerHTML = `<span class="muted">${rows.length} 件</span>`;
  }

  const onEdit = (e) => {
    const tr = e.target.closest('tr[data-i]');
    if (!tr || !e.target.dataset.f) return;
    const r = rows[Number(tr.dataset.i)];
    const f = e.target.dataset.f;
    if (f === 'active') r[f] = e.target.checked;
    else if (f === 'sort_order') r[f] = parseAmount(e.target.value);
    else if (f === 'account_id') r[f] = Number(e.target.value) || null;
    else r[f] = e.target.value;
    markDirty();
  };
  $('#d-table').addEventListener('input', onEdit);
  $('#d-table').addEventListener('change', onEdit);
  $('#d-table').addEventListener('click', (e) => {
    const b = e.target.closest('[data-del]');
    if (!b) return;
    const i = Number(b.dataset.del);
    if (rows[i].id) removed.push(rows[i].id);
    rows.splice(i, 1);
    markDirty();
    draw();
  });

  $('#d-add').onclick = () => {
    const max = rows.reduce((m, r) => Math.max(m, Number(r.sort_order) || 0), 0);
    rows.push({ id: null, code: '', text: '', kana: '', account_id: null, sort_order: max + 10, active: true });
    markDirty();
    draw();
    const trs = $$('#d-table tbody tr[data-i]');
    const last = trs[trs.length - 1];
    if (last) last.querySelector('[data-f=text]').focus();
  };

  $('#d-save').onclick = async () => {
    const seen = {};
    for (const r of rows) {
      const t = String(r.text).trim();
      if (!t) { toast('摘要は必須です', true); return; }
      if (seen[t]) { toast(`摘要「${t}」が重複しています`, true); return; }
      seen[t] = true;
    }
    try {
      const res = await PUT(`/api/clients/${S.client.id}/descriptions/bulk`, {
        items: rows.map(r => ({
          id: r.id, code: String(r.code || '').trim(), text: String(r.text).trim(),
          kana: String(r.kana || '').trim(), account_id: r.account_id || null,
          sort_order: Number(r.sort_order) || 0, active: !!r.active,
        })),
        delete_ids: removed,
      });
      await loadDescriptions();
      rows = snapshot();
      clearDirty();
      draw();
      toast(`保存しました (追加 ${res.created} / 更新 ${res.updated} / 削除 ${res.deleted})`);
    } catch (e) { showError(e); }
  };

  $('#d-history').onclick = () => {
    modal(`<h3>過去の仕訳から摘要を取り込む</h3>
      <p class="muted" style="margin-top:0">これまでに入力した仕訳の摘要のうち、指定回数以上使ったものをプリセットに登録します。</p>
      <div class="form"><label class="field wide"><span>何回以上使った摘要を取り込むか</span>
        <input type="number" id="dh-min" value="2" min="1" max="99"></label></div>
      <div class="actions"><button data-close>キャンセル</button><button class="primary" id="dh-run">取り込む</button></div>`, {
      onOpen(bg, close) {
        $('#dh-run', bg).onclick = async () => {
          try {
            const n = Number($('#dh-min', bg).value) || 2;
            const r = await POST(`/api/clients/${S.client.id}/descriptions/from-history?min_count=${n}`);
            await loadDescriptions();
            rows = snapshot();
            clearDirty();
            draw();
            close();
            toast(r.added ? `${r.added} 件の摘要を登録しました` : '新しく登録できる摘要はありませんでした');
          } catch (e) { showError(e); }
        };
      },
    });
  };

  $('#d-import').onclick = () => {
    modal(`<h3>摘要 CSV の取込</h3>
      <p class="muted" style="margin-top:0">列: コード, 摘要, かな, 関連科目コード, 並び順, 有効<br>
      「摘要」の文字列で既存と照合します。文字コードは UTF-8 / Shift_JIS のどちらでも構いません。</p>
      <div class="form">
        <label class="field wide"><span>CSV ファイル</span><input type="file" id="di-file" accept=".csv,text/csv"></label>
        <label class="field wide"><span>取込方法</span>
          <select id="di-mode">
            <option value="merge">追加・更新のみ</option>
            <option value="replace">CSV の内容に置き換える</option>
          </select></label>
      </div>
      <div id="di-result" style="margin-top:10px"></div>
      <div class="actions"><button data-close>閉じる</button><button id="di-check">内容を確認</button><button class="primary" id="di-run">取込</button></div>`, {
      onOpen(bg) {
        const res = $('#di-result', bg);
        const send = async (dry) => {
          const f = $('#di-file', bg).files[0];
          if (!f) { toast('CSV ファイルを選択してください', true); return; }
          const fd = new FormData();
          fd.append('file', f);
          res.innerHTML = '処理中...';
          try {
            const mode = $('#di-mode', bg).value;
            const r = await api('POST', `/api/clients/${S.client.id}/import/descriptions?mode=${mode}&dry_run=${dry}`, fd);
            res.innerHTML = `<span class="badge ok">${dry ? '確認' : '取込完了'}</span>
              追加 ${r.created} / 更新 ${r.updated} / 削除 ${r.deleted}${r.kept ? ` / 変更なし ${r.kept}` : ''}`;
            if (!dry) {
              await loadDescriptions();
              rows = snapshot();
              clearDirty();
              draw();
              toast(`摘要を取り込みました (追加 ${r.created} / 更新 ${r.updated})`);
            }
          } catch (e) { res.innerHTML = `<span class="badge danger">エラー</span> ${esc(e.message)}`; }
        };
        $('#di-check', bg).onclick = () => send(true);
        $('#di-run', bg).onclick = async () => {
          if (await confirmDialog('CSV の内容で摘要を更新します。よろしいですか？')) await send(false);
        };
      },
    });
  };

  $('#d-q').oninput = draw;
  const warnUnsaved = (e) => { if (dirty) { e.preventDefault(); e.returnValue = ''; } };
  window.addEventListener('beforeunload', warnUnsaved);
  rows = snapshot();
  draw();
  return () => window.removeEventListener('beforeunload', warnUnsaved);
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
      (isNew ? field('入れる勘定科目表', selectInput('chart', (S.meta.charts || []).map(x => ({ value: x.code, label: x.name })), 'tkc'), true) +
        '<div class="field wide muted">作成後も「勘定科目」画面で自由に変更できます。会計期間は当期が自動作成されます。</div>' : ''),
      async (d) => {
        const body = { code: d.code.trim(), name: d.name.trim(), kana: d.kana.trim(), entity_type: d.entity_type, tax_method: d.tax_method, fiscal_start_month: Number(d.fiscal_start_month), note: d.note };
        if (isNew) body.chart = d.chart;
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
    <div class="panel"><h3 style="margin-top:0">DocuWorks (.xdw) の変換</h3>
      <p>通帳取込で DocuWorks のファイルを読み取れない場合、変換コマンドを設定すると
      そのコマンドで PDF に変換してから取り込みます。空欄のままでも、埋め込まれた画像の取り出しは試みます。</p>
      <div class="row"><input type="text" id="xdw-cmd" style="flex:1;min-width:280px"
        placeholder='例: "C:\\Program Files\\DocuWorks\\変換ツール.exe" "{input}" "{output}"'>
        <button id="xdw-save" class="primary">保存</button></div>
      <p class="help"><code>{input}</code> が取り込むファイル、<code>{output}</code> が変換後の PDF の場所に置き換わります。
      設定しない場合は、DocuWorks Desk で PDF に書き出してから取り込んでください。</p>
    </div>
    <div class="panel"><h3 style="margin-top:0">バックアップ</h3>
      <p>全データ (SQLite ファイル) をダウンロードします。復元するときは、サーバー停止後に <code>data/kaikei.db</code> をこのファイルで置き換えてください。</p>
      <a class="btn" href="/api/backup">バックアップをダウンロード</a>
    </div>
  </div>`;
  try {
    $('#xdw-cmd').value = (await GET('/api/settings')).xdw_converter || '';
  } catch (e) { /* 設定が読めなくても他の機能は使える */ }
  $('#xdw-save').onclick = async () => {
    try {
      const r = await PUT('/api/settings', { xdw_converter: $('#xdw-cmd').value });
      toast(r.xdw_converter ? '変換コマンドを保存しました' : '変換コマンドを解除しました');
    } catch (e) { showError(e); }
  };

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
