
const API = '/api';
const state = { assets: [], selected: [], allowed: [], ai: {}, status: {}, confluence: [], logs: [] };

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '')
  .replaceAll('&', '&amp;')
  .replaceAll('<', '&lt;')
  .replaceAll('>', '&gt;')
  .replaceAll('"', '&quot;')
  .replaceAll("'", '&#39;');

function fmtMoney(v){
  const n = Number(v || 0);
  return (n >= 0 ? '$' : '-$') + Math.abs(n).toFixed(2);
}
function badgeColor(dir){ return String(dir || '').toUpperCase() === 'BUY' ? 'green' : 'red'; }
function setError(msg){
  const el = $('error-banner');
  if (!el) return;
  if (!msg){ el.style.display = 'none'; el.textContent = ''; return; }
  el.style.display = 'block';
  el.textContent = msg;
}

async function requestJSON(url, opts = {}){
  try{
    const r = await fetch(url, {
      headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
      ...opts
    });
    const raw = await r.text();
    let data = null;
    if (raw && raw.trim()){
      try { data = JSON.parse(raw); }
      catch { data = { raw }; }
    } else {
      data = null;
    }
    return { ok: r.ok, status: r.status, data };
  }catch(err){
    return { ok: false, status: 0, data: null, error: err?.message || String(err) };
  }
}

function setOffline(msg){
  $('dot-api').className = 'dot bad';
  $('api-health').textContent = 'offline';
  setError(msg || 'Falha ao conectar na API.');
}

async function loadHealth(){
  const res = await requestJSON(API + '/health');
  if (!res.ok || !res.data){
    setOffline('Falha ao conectar na API.');
    return;
  }
  $('dot-api').className = 'dot ok';
  $('api-state').textContent = 'API';
  $('api-health').textContent = 'online';
  $('mode').textContent = res.data.signal_only ? 'Signal only' : 'Live';
  $('timeframe').textContent = res.data.signal_only ? 'Modo sinalizador' : '';
}

function renderStatus(status){
  $('balance').textContent = fmtMoney(status.balance);
  $('balance-sub').textContent = `Inicial: ${fmtMoney(status.initial_balance)}`;
  $('winrate').textContent = `${Number(status.winrate || 0).toFixed(1)}%`;
  $('wr-sub').textContent = `${status.wins || 0}W / ${status.losses || 0}L`;
  $('active-count').textContent = (status.active_trades || []).length;
  $('pending-count').textContent = status.pending_count ?? 0;
  $('max-trades').textContent = status.max_trades_allowed ?? '—';
  $('mode').textContent = status.signal_only ? 'Signal only' : 'Live';
  $('timeframe').textContent = status.timeframe || '—';
  $('allowed-symbols').textContent = `${(status.allowed_symbols || []).length} liberados`;
  $('wins-tag').textContent = `${status.wins || 0}W`;
  $('losses-tag').textContent = `${status.losses || 0}L`;
  $('dd-tag').textContent = `DD ${Number(status.max_drawdown_pct || 0).toFixed(1)}%`;
  $('updated-at').textContent = new Date().toLocaleTimeString('pt-BR');
  renderActiveTrades(status.active_trades || []);
}

async function loadStatus(){
  const res = await requestJSON(API + '/status');
  if (!res.ok || !res.data){
    $('balance').textContent = '—';
    $('winrate').textContent = '—';
    $('active-count').textContent = '—';
    $('pending-count').textContent = '—';
    return;
  }
  state.status = res.data;
  renderStatus(res.data);
}

async function loadAssets(){
  const res = await requestJSON(API + '/assets');
  if (!res.ok || !res.data){
    $('assets-meta').textContent = 'Ativos indisponíveis no momento.';
    $('assets-grid').innerHTML = '';
    return;
  }
  const data = res.data || {};
  state.assets = data.assets || [];
  state.selected = data.selected_symbols || [];
  state.allowed = data.allowed_symbols || [];
  $('assets-meta').textContent = `${state.selected.length} ativos selecionados • ${state.allowed.length} permitidos pela banca`;
  $('assets-grid').innerHTML = state.assets.length ? state.assets.map(a => `
    <label class="asset">
      <div>
        <strong>${esc(a.symbol)}</strong>
        <small>${esc(a.name)}</small>
      </div>
      <div style="display:flex;gap:8px;align-items:center">
        <span class="tag ${a.allowed ? 'green' : 'red'}">${a.allowed ? 'OK' : 'Bloq.'}</span>
        <input type="checkbox" data-symbol="${esc(a.symbol)}" ${a.selected ? 'checked' : ''} ${a.allowed ? '' : 'disabled'}>
      </div>
    </label>
  `).join('') : '<div class="row"><span class="muted">Nenhum ativo disponível.</span></div>';
}

function selectedAssetSymbols(){
  return [...document.querySelectorAll('#assets-grid input[type="checkbox"]')]
    .filter(el => el.checked)
    .map(el => el.dataset.symbol);
}

async function saveAssets(){
  const selected_symbols = selectedAssetSymbols();
  const res = await requestJSON(API + '/assets', {
    method: 'POST',
    body: JSON.stringify({ selected_symbols })
  });
  if (res.ok){
    setError('');
    await refreshAll();
    return;
  }
  setError((res.data && (res.data.message || res.data.error)) || res.error || 'Falha ao salvar ativos');
}

function renderActiveTrades(list){
  const el = $('active-trades');
  if (!list || !list.length){
    el.innerHTML = '<div class="row"><span class="muted">Nenhum trade ativo no momento.</span></div>';
    return;
  }
  el.innerHTML = list.map(t => `
    <div class="row">
      <div class="left">
        <strong>${esc(t.symbol)}</strong>
        <span class="tag ${badgeColor(t.dir)}">${esc(t.dir)}</span>
        <span class="tag ${Number(t.pnl) >= 0 ? 'green' : 'red'}">${fmtMoney(t.pnl)}</span>
        <span class="tag blue">RR 1:${esc(t.rr ?? '—')}</span>
      </div>
      <div class="left">
        <span class="muted">Entrada ${esc(Number(t.entry || 0).toFixed(5))}</span>
        <button class="ghost" onclick="closeTrade(${JSON.stringify(t.symbol)})">Fechar</button>
      </div>
    </div>
  `).join('');
}

async function loadPending(){
  const res = await requestJSON(API + '/pending');
  const list = Array.isArray(res.data) ? res.data : (res.data?.pending || []);
  $('pending-meta').textContent = `${list.length} sinal(is)`;
  const el = $('pending-list');
  if (!list.length){
    el.innerHTML = '<div class="row"><span class="muted">Nenhum sinal pendente.</span></div>';
    return;
  }
  el.innerHTML = list.map((p, idx) => {
    const pid = p.pending_id ?? p.id ?? idx;
    return `
      <div class="row" style="display:block">
        <div style="display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;align-items:center">
          <div class="left">
            <strong>${esc(p.symbol)}</strong>
            <span class="tag ${badgeColor(p.dir)}">${esc(p.dir)}</span>
            <span class="tag amber">Score ${esc(p.score)}/${esc(p.max_score)}</span>
            <span class="tag purple">IA ${esc(p.ai_confidence ?? 0)}/10</span>
          </div>
          <div class="left muted">${esc(p.created_at || '')}</div>
        </div>
        <div class="tiny" style="margin-top:8px;line-height:1.6">
          Entrada ${esc(Number(p.entry || 0).toFixed(5))} • SL ${esc(Number(p.sl || 0).toFixed(5))} • TP ${esc(Number(p.tp || 0).toFixed(5))}<br>
          RR 1:${esc(p.rr ?? '—')} • Risco sugerido ${fmtMoney(p.suggested_risk_usd)} • Margem mínima ${fmtMoney(p.min_lot_margin)}
        </div>
        <div class="toolbar" style="margin-top:10px">
          <input id="amt-${esc(pid)}" type="number" min="0" step="1" value="${Math.max(1, Math.ceil(Number(p.min_lot_margin || 1)))}" style="max-width:140px;padding:10px 12px;border-radius:12px;border:1px solid var(--line);background:var(--panel2);color:var(--text)">
          <button class="success" onclick="executePending(${JSON.stringify(pid)})">Executar</button>
          <button class="danger" onclick="rejectPending(${JSON.stringify(pid)})">Rejeitar</button>
        </div>
      </div>
    `;
  }).join('');
}

async function loadHistory(){
  const res = await requestJSON(API + '/history');
  const list = Array.isArray(res.data) ? res.data : [];
  const body = $('history-body');
  if (!list.length){
    body.innerHTML = '<tr><td colspan="6" class="muted">Nenhuma operação ainda.</td></tr>';
    return;
  }
  body.innerHTML = list.slice().reverse().map(h => `
    <tr>
      <td>${esc(h.closed_at || '')}</td>
      <td><strong>${esc(h.symbol)}</strong></td>
      <td><span class="tag ${badgeColor(h.dir)}">${esc(h.dir)}</span></td>
      <td><span class="tag ${h.result === 'WIN' ? 'green' : 'red'}">${esc(h.result)}</span></td>
      <td style="color:${Number(h.pnl || 0) >= 0 ? 'var(--green)' : 'var(--red)'};font-weight:700">${fmtMoney(h.pnl)}</td>
      <td>${esc(h.ai_confidence ?? 0)}/10</td>
    </tr>
  `).join('');
}

async function loadAI(){
  const res = await requestJSON(API + '/ai_params');
  const a = res.data && typeof res.data === 'object' ? res.data : {};
  state.ai = a;
  $('live-conf').textContent = `${a.live_confluence ?? 7}/11`;
  $('ai-bias').textContent = `Viés: ${a.strategy_bias || 'balanced'}`;
  $('adx-avg').textContent = a.live_adx_avg ?? '—';
  $('min-rr').textContent = a.min_rr ?? '—';
  $('regime-badge').textContent = (a.live_regime || 'neutral').toUpperCase();
  $('regime-summary').textContent = a.opus_summary || 'Sem resumo estratégico ainda.';
  $('ai-summary').textContent = a.last_suggestion || (res.ok ? 'Sem sugestão da IA no momento.' : 'IA indisponível no momento.');
}

async function loadConfluence(){
  const res = await requestJSON(API + '/confluence');
  const data = Array.isArray(res.data) ? res.data : [];
  $('conf-refresh').textContent = new Date().toLocaleTimeString('pt-BR');
  $('confluence-list').innerHTML = data.slice(0, 10).map(item => `
    <div class="row">
      <div class="left">
        <strong>${esc(item.symbol)}</strong>
        <span class="tag ${badgeColor(item.best_dir)}">${esc(item.best_dir)}</span>
      </div>
      <div class="left muted">${esc(item.best_score)}/${esc(item.total)}</div>
    </div>
  `).join('') || '<div class="row"><span class="muted">Sem dados de confluência.</span></div>';
}

async function loadLogs(){
  const res = await requestJSON(API + '/logs?limit=12&hours=24');
  const payload = res.data && typeof res.data === 'object' ? res.data : {};
  const logs = Array.isArray(payload.logs) ? payload.logs : [];
  $('log-count').textContent = `${payload.count ?? logs.length} entradas`;
  $('logs-list').innerHTML = logs.length ? logs.map(l => `
    <div class="row">
      <div class="left"><strong>${esc(l.type || 'log')}</strong><span class="muted">${esc(l.created_at || '')}</span></div>
      <div class="muted" style="max-width:70ch;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(l.message || JSON.stringify(l))}</div>
    </div>
  `).join('') : '<div class="row"><span class="muted">Nenhum log recente.</span></div>';
}

async function closeTrade(symbol){
  if (!confirm(`Fechar trade de ${symbol}?`)) return;
  const res = await requestJSON(API + '/close_trade', {
    method: 'POST',
    body: JSON.stringify({ symbol })
  });
  if (!res.ok){
    setError((res.data && (res.data.message || res.data.error)) || res.error || 'Erro ao fechar trade');
    return;
  }
  setError('');
  await refreshAll();
}

async function executePending(pid){
  const inp = document.getElementById('amt-' + pid);
  const amount = Number(inp?.value || 0);
  if (!amount || amount <= 0){ alert('Margem inválida'); return; }
  const res = await requestJSON(API + '/execute', {
    method: 'POST',
    body: JSON.stringify({ pending_id: pid, amount })
  });
  if (!res.ok){
    setError((res.data && (res.data.message || res.data.error)) || res.error || 'Erro ao executar');
    return;
  }
  setError('');
  await refreshAll();
}

async function rejectPending(pid){
  const res = await requestJSON(API + '/reject', {
    method: 'POST',
    body: JSON.stringify({ pending_id: pid })
  });
  if (!res.ok){
    setError((res.data && (res.data.message || res.data.error)) || res.error || 'Erro ao rejeitar');
    return;
  }
  await refreshAll();
}

async function refreshAll(){
  const errors = [];
  try { await loadHealth(); } catch (e) { errors.push(`health: ${e.message}`); }
  try { await loadStatus(); } catch (e) { errors.push(`status: ${e.message}`); }
  try { await loadAssets(); } catch (e) { errors.push(`assets: ${e.message}`); }
  try { await loadAI(); } catch (e) { errors.push(`ai: ${e.message}`); }
  try { await loadConfluence(); } catch (e) { errors.push(`confluence: ${e.message}`); }
  try { await loadPending(); } catch (e) { errors.push(`pending: ${e.message}`); }
  try { await loadHistory(); } catch (e) { errors.push(`history: ${e.message}`); }
  try { await loadLogs(); } catch (e) { errors.push(`logs: ${e.message}`); }

  if (errors.length){
    setError(`Algumas áreas ficaram indisponíveis:\n- ${errors.slice(0, 4).join('\n- ')}`);
  } else {
    setError('');
  }
}

$('btn-refresh').addEventListener('click', refreshAll);
$('btn-save-assets').addEventListener('click', saveAssets);

refreshAll();
setInterval(refreshAll, 15000);
