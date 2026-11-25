/* Implement tasks: a statement with no hint, real code in the editor, judged on this computer
   against generated tests with a time limit. */
import {makeEditor} from './problem.js';
import {sideButton, wireSplit} from './split.js';

export async function renderTasks(ctx) {
  const {api, escape: e} = ctx;
  const root = ctx.root;
  const page = await api('/tasks');
  if (ctx.root !== root) return;
  const done = page.tasks.filter(t => t.solved).length;
  root.innerHTML = `<header class="page-head"><div><p class="eyebrow">Write it</p><h1>Code</h1><p class="muted">Short tasks where you write the program yourself. No topic is given; the tests include inputs large enough that the first loop you think of is too slow. ${done} of ${page.tasks.length} accepted.</p></div></header>
    ${page.tracks.map(track => { const mine = page.tasks.filter(t => t.track === track.id); return mine.length ? `<section class="surface"><h2>${e(track.title)}</h2><p class="muted small">${e(track.about)}</p>
      <ol class="task-list">${mine.map(t => `<li><a href="#/task/${e(t.id)}">${e(t.title)}</a> ${t.solved ? '<span class="badge badge-success">accepted</span>' : t.tries ? `<span class="badge">${e(t.last)} · ${t.tries} ${t.tries === 1 ? 'try' : 'tries'}</span>` : ''}</li>`).join('')}</ol></section>` : ''; }).join('')}`;
}

/* The whole task (statement, editor, run, judge) inside any host element. Used by the task page and by code steps of a chain. */
export async function mountTask(ctx, host, id, {onAccepted = null, heading = true, before = '', after = ''} = {}) {
  const {api, post, waitFor, escape: e, markdown, toast} = ctx;
  const root = ctx.root, alive = () => ctx.root === root && host.isConnected;
  let task = await api('/task/' + encodeURIComponent(id));
  let language = ctx.boot.settings.language || 'cpp';
  let files = (await api(`/code/${encodeURIComponent(id)}?language=${language}`)).files;
  if (!alive()) return;
  let busy = false, saveTimer = null;
  const box = (title, text) => `<div><h4>${e(title)}</h4><pre>${e(text)}</pre></div>`;
  host.innerHTML = `${heading ? `<header class="page-head"><div><p class="eyebrow"><a href="#/code">Code</a> · time limit ${task.seconds} s (C++)</p><h1>${e(task.title)}</h1></div><div data-status></div></header>` : `<p class="muted small">Time limit ${task.seconds} s (C++). <span data-status></span></p>`}
    <div class="split" data-split><div class="split-pane split-text">${before}<section class="surface reading task-statement">${markdown(task.statement)}
      <h3>Example${task.samples.length > 1 ? 's' : ''}</h3>${task.samples.map(s => `<div class="io-grid">${box('Input', s[0])}${box('Output', s[1])}</div>`).join('')}</section>${after}</div>
    <div class="split-pane split-code"><section class="surface editor-card" aria-label="Code"><div class="editor-bar"><span class="muted small" data-save role="status">Saved</span><div class="editor-meta">${sideButton()}<label><span class="sr-only">Language</span><select data-language><option value="cpp" ${language === 'cpp' ? 'selected' : ''}>C++20</option><option value="python" ${language === 'python' ? 'selected' : ''}>Python</option></select></label></div></div>
      <div class="editor-host" data-editor></div>
      <label class="field">Your own input<textarea data-input rows="4" spellcheck="false">${e(task.samples[0][0])}</textarea></label>
      <div class="run-bar"><button class="btn btn-secondary btn-sm" type="button" data-run>Run on this input</button><span class="spacer"></span><button class="btn btn-primary" type="button" data-judge>Judge</button></div></section>
    <section class="surface results" aria-live="polite" data-results><h3>Results</h3><p class="results-empty">Run it on your own input, or judge it against the hidden tests.</p></section></div></div>`;
  wireSplit(host.querySelector('[data-split]'));
  const $ = s => host.querySelector(s);
  const status = () => { $('[data-status]').innerHTML = task.solved ? '<span class="badge badge-success">Accepted</span>' : task.tries ? `<span class="badge">${task.tries} ${task.tries === 1 ? 'try' : 'tries'} so far</span>` : ''; };
  status();
  const save = async () => { try { await post('/code', {id, language, file: 'main', code: files.main}); if (host.isConnected) $('[data-save]').textContent = 'Saved'; } catch { if (host.isConnected) $('[data-save]').textContent = 'Not saved'; } };
  const changed = value => { files.main = value; $('[data-save]').textContent = 'Editing…'; clearTimeout(saveTimer); saveTimer = setTimeout(save, 800); };
  const editor = await makeEditor($('[data-editor]'), {value: files.main, language, fontSize: ctx.boot.settings.font_size, tabSize: 4, onChange: changed, onRun: () => go('run')});
  if (!alive()) { editor.destroy(); return; }
  ctx.onCleanup(() => { clearTimeout(saveTimer); try { files.main = editor.getValue(); save(); editor.destroy(); } catch { /* already gone */ } });
  $('[data-language]').addEventListener('change', async event => {
    files.main = editor.getValue(); await save();
    language = event.target.value;
    files = (await api(`/code/${encodeURIComponent(id)}?language=${language}`)).files;
    editor.setLanguage(language); editor.setValue(files.main);
  });
  async function go(kind) {
    if (busy) return;
    busy = true; files.main = editor.getValue();
    host.querySelectorAll('[data-run],[data-judge]').forEach(b => { b.disabled = true; });
    const results = $('[data-results]');
    results.innerHTML = `<h3>Results</h3><p><span class="spinner"></span> ${kind === 'judge' ? 'Judging…' : 'Running…'}</p>`;
    let accepted = false;
    try {
      const queued = kind === 'judge' ? await post('/task/judge', {id, language, main: files.main}) : await post('/run', {kind: 'run', id, language, main: files.main, input: $('[data-input]').value});
      const job = await waitFor(queued.job, alive);
      if (!job || !alive()) return;
      const r = job.result || {};
      if (job.status === 'error') { results.innerHTML = `<h3>Results</h3><p class="inline-error">${e(r.error || 'The run could not finish.')}</p>`; return; }
      const good = r.verdict === 'AC' || r.verdict === 'OK';
      results.innerHTML = `<h3>${kind === 'judge' ? 'Verdict' : 'Run'}</h3><div class="result-head"><span class="verdict ${good ? 'verdict-ok' : 'verdict-bad'}">${e(r.verdict)}</span>${kind === 'judge' ? `<strong>${r.passed} of ${r.of} tests passed</strong>` : `<span class="muted">${r.seconds != null ? Number(r.seconds).toFixed(2) + ' s' : ''}</span>`}</div>
        ${r.detail ? `<p class="result-detail">${e(r.detail)}</p>` : ''}<div class="io-grid">${r.input != null ? box('The test', r.input) : ''}${r.expected != null ? box('Expected', r.expected) : ''}${r.output != null && (kind === 'run' || r.verdict !== 'AC') ? box('Your output', r.output) : ''}</div>`;
      if (kind === 'judge') { task = await api('/task/' + encodeURIComponent(id)); status(); ctx.sync(); accepted = r.verdict === 'AC'; }
    } catch (error) { toast(error.message, 'error'); results.innerHTML = '<h3>Results</h3><p class="results-empty">Nothing was run.</p>'; }
    finally { busy = false; if (alive()) host.querySelectorAll('[data-run],[data-judge]').forEach(b => { b.disabled = false; }); }
    if (accepted && onAccepted) onAccepted();
  }
  $('[data-run]').addEventListener('click', () => go('run'));
  $('[data-judge]').addEventListener('click', () => go('judge'));
}

export async function renderTask(ctx, id) {
  const {api, escape: e} = ctx;
  const root = ctx.root;
  // The tasks in the order the Code page lists them: track by track.
  const page = await api('/tasks');
  const order = page.tracks.flatMap(track => page.tasks.filter(t => t.track === track.id));
  const at = order.findIndex(t => t.id === id);
  await mountTask(ctx, root, id);
  if (ctx.root !== root || at < 0) return;
  const prev = order[at - 1], next = order[at + 1];
  const track = page.tracks.find(t => t.id === order[at].track);
  const mine = order.filter(t => t.track === order[at].track);
  const link = (t, label, cls) => t ? `<a class="btn ${cls} btn-sm" href="#/task/${e(t.id)}" title="${e(t.title)}">${label}</a>` : `<span class="btn btn-ghost btn-sm" aria-disabled="true">${label}</span>`;
  const nav = document.createElement('nav');
  nav.className = 'task-nav';
  nav.setAttribute('aria-label', 'Other tasks');
  nav.innerHTML = `<span class="muted small">${e(track?.title || '')} · ${mine.findIndex(t => t.id === id) + 1} of ${mine.length}</span>${link(prev, '← Previous', 'btn-ghost')}${link(next, 'Next →', 'btn-secondary')}`;
  root.querySelector('.page-head')?.after(nav);
  window.dispatchEvent(new Event('resize'));                 // the split below is re-fitted now that this row is above it
}
