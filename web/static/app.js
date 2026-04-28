// wqbus console — vanilla JS. All paths relative (reverse-proxy friendly).
const $  = (s, r=document) => r.querySelector(s);
const $$ = (s, r=document) => Array.from(r.querySelectorAll(s));

async function api(path, opts={}) {
  const res = await fetch(path, {
    headers: opts.body ? {'Content-Type': 'application/json'} : {},
    ...opts,
  });
  const ct = res.headers.get('Content-Type') || '';
  if (ct.includes('application/json')) {
    const j = await res.json();
    if (!res.ok) throw new Error(j.error || j.detail || res.status);
    return j;
  }
  if (!res.ok) throw new Error(await res.text());
  return await res.text();
}

// ---------------- tabs ----------------
const TAB_INIT = {
  pipe: () => { loadPipeCatalog(); refreshPipeList(); },
  trace: refreshTraces,
  sumr:  refreshSumrModes,
  cfg:   loadCfgList,
};
$$('nav a').forEach(a => a.addEventListener('click', e => {
  e.preventDefault();
  const id = a.dataset.tab;
  $$('nav a').forEach(x => x.classList.toggle('active', x === a));
  $$('section.tab').forEach(s => s.classList.toggle('active', s.id === id));
  (TAB_INIT[id] || (() => {}))();
}));

// ---------------- state pill ----------------
async function pollState() {
  try {
    const j = await api('api/state');
    const c = j.counts;
    $('#state-pill').textContent =
      `tasks ${c.tasks_running ?? '?'}/${c.tasks_total ?? '?'}  ` +
      `traces ${c.traces_running}/${c.traces_total}  paused ${c.traces_paused}  ` +
      `events ${c.events_total}  alphas ${c.alphas_total ?? '?'}  dlq ${c.sim_dlq_open ?? '?'}`;
  } catch (e) {
    $('#state-pill').textContent = 'offline: ' + e.message;
  }
}
setInterval(pollState, 4000);
pollState();

// ====================================================================
// PIPELINES (R6-C tasks)
// ====================================================================
let _pipeCatalog = {tasks: [], pipelines: []};

async function loadPipeCatalog() {
  try {
    const j = await api('api/pipeline/catalog');
    _pipeCatalog = {tasks: j.tasks || [], pipelines: j.pipelines || []};
    const sel = $('#pipe-name'); sel.innerHTML = '';
    _pipeCatalog.tasks.forEach(t => {
      const o = document.createElement('option');
      o.value = t.name; o.textContent = `${t.name}  →  ${t.pipeline || '(?)'}`;
      sel.appendChild(o);
    });
    sel.dispatchEvent(new Event('change'));
  } catch (e) { console.warn('catalog', e); }
}
$('#pipe-name').addEventListener('change', () => {
  const t = _pipeCatalog.tasks.find(x => x.name === $('#pipe-name').value);
  if (!t) { $('#pipe-desc').textContent = ''; return; }
  const goal = t.goal ? JSON.stringify(t.goal) : '(no goal)';
  $('#pipe-desc').textContent =
    `pipeline=${t.pipeline}  max_iter=${t.max_iterations ?? '?'}  goal=${goal}`;
});

$('#pipe-form').addEventListener('submit', async e => {
  e.preventDefault();
  const f = e.target;
  const body = {
    task_name: f.task_name.value,
    dataset_tag: f.dataset_tag.value || '_global',
  };
  if (f.max_iterations.value) body.max_iterations = Number(f.max_iterations.value);
  try {
    const r = await api('api/pipeline/start', {method:'POST', body: JSON.stringify(body)});
    flash(`started ${r.task_name || body.task_name}: ${r.task_id}`);
    refreshPipeList();
  } catch (err) { alert('start failed: ' + err.message); }
});

$('#pipe-refresh').addEventListener('click', refreshPipeList);
$('#pipe-filter').addEventListener('change', refreshPipeList);

async function refreshPipeList() {
  const status = $('#pipe-filter').value;
  const qs = new URLSearchParams({limit: '50'});
  if (status) qs.set('status', status);
  let j;
  try { j = await api('api/pipeline/list?' + qs); }
  catch (e) { console.warn('pipe list', e); return; }
  const tb = $('#pipe-tbl tbody'); tb.innerHTML = '';
  for (const t of (j.tasks || [])) {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><code class="pipe-link" data-id="${t.task_id}">${t.task_id}</code></td>
      <td>${t.name || ''}</td>
      <td>${t.dataset_tag || ''}</td>
      <td class="status-${t.status}">${t.status}</td>
      <td>${t.iterations ?? 0}</td>
      <td class="muted">${t.started_at || ''}</td>
      <td class="muted">${t.ended_at || ''}</td>
      <td>
        <button class="actbtn act-pause"  data-act="pause"  data-id="${t.task_id}">pause</button>
        <button class="actbtn act-resume" data-act="resume" data-id="${t.task_id}">resume</button>
        <button class="actbtn act-cancel" data-act="cancel" data-id="${t.task_id}">cancel</button>
      </td>`;
    tb.appendChild(tr);
  }
  $$('.pipe-link').forEach(el =>
    el.addEventListener('click', () => showPipe(el.dataset.id)));
  $$('#pipe-tbl .actbtn').forEach(b =>
    b.addEventListener('click', () => controlPipe(b.dataset.id, b.dataset.act)));
}

async function controlPipe(id, action) {
  if (action === 'cancel' && !confirm(`cancel task ${id}?`)) return;
  try {
    await api(`api/pipeline/${id}/${action}`, {method:'POST', body:'{}'});
    refreshPipeList();
  } catch (e) { alert('failed: ' + e.message); }
}

async function showPipe(task_id) {
  const j = await api('api/pipeline/' + task_id);
  $('#pd-id').textContent = task_id;
  $('#pd-name').textContent = j.task.name || '';
  const meta = $('#pd-meta'); meta.innerHTML = '';
  const fields = ['status','dataset_tag','pipeline','iterations',
                  'max_iterations','wall_time_secs','started_at','ended_at','origin','error'];
  for (const k of fields) {
    if (j.task[k] === undefined || j.task[k] === null || j.task[k] === '') continue;
    meta.insertAdjacentHTML('beforeend',
      `<div><span class=muted>${k}</span><br><code>${j.task[k]}</code></div>`);
  }
  if (j.task.goal_json) {
    meta.insertAdjacentHTML('beforeend',
      `<div class=full><span class=muted>goal</span><br><code>${j.task.goal_json}</code></div>`);
  }
  if (j.progress && Object.keys(j.progress).length) {
    meta.insertAdjacentHTML('beforeend',
      `<div class=full><span class=muted>progress</span><br><code>${JSON.stringify(j.progress)}</code></div>`);
  }
  const itb = $('#pd-iters tbody'); itb.innerHTML = '';
  (j.iterations || []).forEach(it => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${it.iteration ?? ''}</td>
      <td><code class="trace-link" data-id="${it.trace_id}">${it.trace_id}</code></td>
      <td>${it.pipeline || ''}</td>
      <td>${it.current_step || ''}</td>
      <td class="status-${it.status}">${it.status}</td>
      <td class="muted">${it.started_at || ''}</td>
      <td class="muted">${it.ended_at || ''}</td>`;
    itb.appendChild(tr);
  });
  $$('#pd-iters .trace-link').forEach(el =>
    el.addEventListener('click', () => { showTrace(el.dataset.id);
      $$('nav a').forEach(x => x.classList.toggle('active', x.dataset.tab === 'trace'));
      $$('section.tab').forEach(s => s.classList.toggle('active', s.id === 'trace')); }));
  $('#pipe-detail').hidden = false;
  $('#pipe-detail').scrollIntoView({behavior: 'smooth'});
}

// ====================================================================
// TRACES
// ====================================================================
$('#trace-refresh').addEventListener('click', refreshTraces);

async function refreshTraces() {
  const limit = $('#trace-limit').value || 50;
  const j = await api('api/traces?limit=' + limit);
  const tb = $('#trace-tbl tbody'); tb.innerHTML = '';
  for (const t of j.traces) {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><code class="trace-link" data-id="${t.trace_id}">${t.trace_id}</code></td>
      <td>${t.task_kind || ''}</td>
      <td class="status-${t.status}">${t.status}</td>
      <td>${t.dataset_tag || ''}</td>
      <td class="muted">${t.parent_task_id || ''}</td>
      <td class="muted">${t.started_at || ''}</td>
      <td class="muted">${t.ended_at || ''}</td>
      <td>
        <button class="actbtn act-pause"  data-act="pause"  data-id="${t.trace_id}">pause</button>
        <button class="actbtn act-resume" data-act="resume" data-id="${t.trace_id}">resume</button>
        <button class="actbtn act-cancel" data-act="cancel" data-id="${t.trace_id}">cancel</button>
      </td>`;
    tb.appendChild(tr);
  }
  $$('#trace-tbl .trace-link').forEach(el =>
    el.addEventListener('click', () => showTrace(el.dataset.id)));
  $$('#trace-tbl .actbtn').forEach(b =>
    b.addEventListener('click', () => controlTrace(b.dataset.id, b.dataset.act)));
}

async function controlTrace(id, action) {
  if (action === 'cancel' && !confirm(`cancel trace ${id}?`)) return;
  try {
    await api(`api/task/${id}/${action}`, {method:'POST', body:'{}'});
    refreshTraces();
  } catch (e) { alert('failed: ' + e.message); }
}

async function showTrace(id) {
  const j = await api('api/trace/' + id);
  $('#td-id').textContent = id;
  $('#td-body').textContent = JSON.stringify(j, null, 2);
  $('#trace-detail').hidden = false;
  $('#trace-detail').scrollIntoView({behavior: 'smooth'});
}

// ====================================================================
// AGENTS (legacy single-shot)
// ====================================================================
$('#agent-form').addEventListener('submit', async e => {
  e.preventDefault();
  const f = e.target;
  const body = {
    agent: f.agent.value, mode: f.mode.value,
    dataset_tag: f.dataset_tag.value || '_global',
    n: Number(f.n.value || 3),
    goal: f.goal.value || undefined,
    url:  f.url.value  || undefined,
  };
  try {
    const r = await api('api/task', {method:'POST', body: JSON.stringify(body)});
    flash('agent task started: trace ' + r.trace_id);
  } catch (err) { alert('start failed: ' + err.message); }
});

// ====================================================================
// SUMMARIZER
// ====================================================================
$('#sumr-refresh').addEventListener('click', refreshSumrModes);

async function refreshSumrModes() {
  let j;
  try { j = await api('api/summarizer/modes'); }
  catch (e) { $('#sumr-out').textContent = 'load failed: ' + e.message; return; }
  const tb = $('#sumr-tbl tbody'); tb.innerHTML = '';
  (j.modes || []).forEach(m => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><code>${m.name}</code></td>
      <td>${m.enabled ? 'yes' : '<span class=muted>no</span>'}</td>
      <td class=muted>${m.source || ''}</td>
      <td class=muted>${m.prompt_kind || ''}</td>
      <td class=muted>${m.wake_interval ?? ''}</td>
      <td><button class="actbtn act-resume sumr-run" data-mode="${m.name}">run now</button></td>`;
    tb.appendChild(tr);
  });
  $$('.sumr-run').forEach(b =>
    b.addEventListener('click', () => runSumr(b.dataset.mode)));
}

async function runSumr(mode) {
  $('#sumr-out').textContent = `running ${mode}…`;
  try {
    const j = await api('api/summarizer/run/' + mode, {method:'POST', body:'{}'});
    $('#sumr-out').textContent = JSON.stringify(j, null, 2);
  } catch (e) {
    $('#sumr-out').textContent = 'failed: ' + e.message;
  }
}

// ====================================================================
// LOGS
// ====================================================================
let _es = null;
$('#log-tail-btn').addEventListener('click', async () => {
  const tag = $('#log-tag').value.trim();
  const n   = $('#log-lines').value;
  const qs  = new URLSearchParams({lines: n}); if (tag) qs.set('tag', tag);
  const j = await api('api/log/tail?' + qs);
  $('#log-out').textContent = (j.lines || []).join('\n');
  const box = $('#log-out'); box.scrollTop = box.scrollHeight;
});
$('#log-stream-btn').addEventListener('click', () => {
  if (_es) _es.close();
  const tag = $('#log-tag').value.trim();
  const qs  = new URLSearchParams(); if (tag) qs.set('tag', tag);
  _es = new EventSource('api/log/stream?' + qs);
  $('#log-out').textContent = '— streaming —\n';
  _es.onmessage = ev => {
    const box = $('#log-out');
    box.textContent += ev.data + '\n';
    if (box.scrollHeight - box.scrollTop - box.clientHeight < 80) box.scrollTop = box.scrollHeight;
  };
  _es.onerror = () => { $('#log-out').textContent += '\n— stream error —\n'; };
});
$('#log-stop-btn').addEventListener('click', () => { if (_es) { _es.close(); _es = null; } });
$('#log-clear-btn').addEventListener('click', () => { $('#log-out').textContent = ''; });

// ====================================================================
// CONFIG
// ====================================================================
async function loadCfgList() {
  const j = await api('api/config');
  const sel = $('#cfg-list'); sel.innerHTML = '';
  (j.files || []).forEach(f => {
    const o = document.createElement('option'); o.value = f.name;
    o.textContent = `${f.name}  (${f.size}B)`; sel.appendChild(o);
  });
}
$('#cfg-load').addEventListener('click', async () => {
  const name = $('#cfg-list').value;
  if (!name) return;
  const txt = await api('api/config/' + name);
  $('#cfg-edit').value = txt;
  $('#cfg-status').textContent = `loaded ${name}`;
});
$('#cfg-save').addEventListener('click', async () => {
  const name = $('#cfg-list').value;
  if (!name) return;
  if (!confirm(`save ${name}?  (a .bak-<ts> backup will be created)`)) return;
  try {
    const res = await fetch('api/config/' + name, {method:'PUT', body: $('#cfg-edit').value});
    if (!res.ok) {
      const t = await res.text();
      throw new Error(t);
    }
    $('#cfg-status').textContent = `saved ${name}`;
  } catch (e) { alert('save failed: ' + e.message); }
});

// ====================================================================
// KB
// ====================================================================
$('#kb-run-quick').addEventListener('click', async () => {
  const name = $('#kb-quick').value;
  if (!name) return;
  await runKb('api/kb/quick/' + name);
});
$('#kb-run').addEventListener('click', async () => {
  const sql = $('#kb-sql').value.trim();
  if (!sql) return;
  await runKb('api/kb/query', {method:'POST', body: JSON.stringify({sql})});
});

async function runKb(path, opts={}) {
  $('#kb-status').textContent = 'running…';
  try {
    const j = await api(path, opts);
    $('#kb-status').textContent = `${j.count} rows`;
    renderTable($('#kb-out'), j.rows);
  } catch (e) {
    $('#kb-status').textContent = 'error';
    $('#kb-out').innerHTML = '<pre>' + escapeHtml(e.message) + '</pre>';
  }
}

function renderTable(host, rows) {
  if (!rows || !rows.length) { host.innerHTML = '<em class="muted">(no rows)</em>'; return; }
  const cols = Object.keys(rows[0]);
  const t = document.createElement('table');
  t.innerHTML = '<thead><tr>' + cols.map(c => `<th>${c}</th>`).join('') + '</tr></thead>';
  const tb = document.createElement('tbody');
  rows.forEach(r => {
    const tr = document.createElement('tr');
    tr.innerHTML = cols.map(c => {
      const v = r[c];
      if (v === null) return '<td><span class=muted>null</span></td>';
      const s = String(v);
      return `<td>${escapeHtml(s.length > 200 ? s.slice(0, 200) + '…' : s)}</td>`;
    }).join('');
    tb.appendChild(tr);
  });
  t.appendChild(tb);
  host.innerHTML = ''; host.appendChild(t);
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => (
    {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c]);
}

// ---------------- toast ----------------
function flash(msg) {
  let el = $('#toast');
  if (!el) {
    el = document.createElement('div'); el.id = 'toast';
    document.body.appendChild(el);
  }
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(flash._t);
  flash._t = setTimeout(() => el.classList.remove('show'), 3000);
}

// initial paint
loadPipeCatalog();
refreshPipeList();
