/* 起動処理 */
'use strict';

(async function boot() {
  try {
    await loadMeta();
    await loadClients();
  } catch (e) {
    showError(e);
  }
  $('#sel-client').addEventListener('change', async (e) => {
    await selectClient(Number(e.target.value) || null);
    render();
  });
  $('#sel-fy').addEventListener('change', (e) => {
    S.fy = S.fiscalYears.find(f => f.id === Number(e.target.value)) || null;
    if (S.fy) localStorage.setItem('fyId:' + S.client.id, S.fy.id);
    render();
  });
  window.addEventListener('hashchange', render);
  if (!S.client && !location.hash.startsWith('#/clients')) location.hash = '#/clients';
  render();
})();
