import {askTutor} from './tutor.js';
/* A real problem from a real judge, with no topic given.
   Order of events: (an optional first approach), work, (help), the judge's verdict, then what cracked it. */

const VERDICTS = {OK: 'Ran', TLE: 'Time limit exceeded', MLE: 'Memory limit exceeded', RE: 'Runtime error', CE: 'Did not compile', OLE: 'Too much output',
  SAME: 'No difference found', DIFF: 'Different answers', GEN: 'Generator failed', BRUTE: 'Brute force failed'};
const CAUSES = [['unknown-fact', 'I did not know the fact it rests on'], ['unrecognised', 'I knew the idea but did not see that it applied'], ['wrong-conjecture', 'I believed something false'],
  ['no-proof', 'I had the idea but could not prove it'], ['implementation', 'The idea was right; the code was wrong']];
const FILES = [['main', 'Solution'], ['brute', 'Brute force'], ['gen', 'Generator']];

let editorModule;
export async function makeEditor(parent, options) {
  if (editorModule === undefined) { try { editorModule = await import('./vendor/editor.js'); } catch { editorModule = null; } }
  if (editorModule) { try { return editorModule.createEditor(parent, options); } catch { /* plain box below */ } }
  const area = document.createElement('textarea');
  area.className = 'editor-fallback'; area.spellcheck = false; area.value = options.value || '';
  area.setAttribute('aria-label', 'Code editor');
  area.addEventListener('input', () => options.onChange(area.value));
  parent.append(area);
  return {getValue: () => area.value, setValue: v => { area.value = v; }, setLanguage: () => {}, focus: () => area.focus(), destroy: () => area.remove()};
}

/* "Solve" opens the problem in progress, or asks for the next one. */
export async function renderSolve(ctx) {
  const root = ctx.root;
  if (!ctx.boot.counts.problems) {
    root.innerHTML = '<section class="surface empty-state"><h1>No problems yet</h1><p>The set of real problems is still being curated. The chains are ready now.</p><a class="btn btn-primary" href="#/derive">Derive something</a></section>';
    return;
  }
  const next = await ctx.post('/problem/next');
  if (ctx.root !== root) return;
  if (!next.id) {
    root.innerHTML = '<section class="surface empty-state"><h1>You have been through every problem in the set</h1><p>More are added in batches.</p><a class="btn btn-primary" href="#/mastery">See what you can do</a></section>';
    return;
  }
  ctx.navigate('#/problem/' + next.id);
}

export async function renderProblem(ctx, id) {
  const {api, post, waitFor, escape: e, icon, inline, toast, dialog, navigate} = ctx;
  const root = ctx.root, alive = () => ctx.root === root;
  let p = await api('/problem/' + encodeURIComponent(id));
  if (!alive()) return;
  if (!p.opened) {
    root.innerHTML = `<section class="surface empty-state"><h1>This problem has not come up yet</h1><p>Problems are handed out one at a time, without their topic.</p><a class="btn btn-primary" href="#/solve">Give me a problem</a></section>`;
    return;
  }
  const settings = ctx.boot.settings;
  let language = settings.language, files = (await api(`/code/${encodeURIComponent(id)}?language=${language}`)).files;
  if (!alive()) return;
  let file = 'main', editor = null, saveTimer = null, noteTimer = null, running = false, stopped = false;
  const dirty = {main: false, brute: false, gen: false};

  root.innerHTML = `<div class="reading wide-reading">
    <header class="chain-head"><p class="eyebrow">${e(p.site)} · rated ${e(p.rating)}${p.returned_for ? ' · something you have met before' : ''}</p><h1>${e(p.title)}</h1>
      <p><a class="btn btn-secondary" href="${e(p.url)}" target="_blank" rel="noopener noreferrer">${icon('external')}Read it on ${e(p.site)}</a></p></header>
    <section class="surface" data-commit></section>
    <section class="surface" aria-label="Notes"><h2>Scratch notes</h2><p class="muted small">Small cases, observations, dead ends. Saved as you type.</p><textarea class="input notes" data-notes rows="5" spellcheck="false" placeholder="n = 1: …">${e(p.notes || '')}</textarea></section>
    <section class="surface editor-card" aria-label="Code">
      <div class="editor-bar"><div class="file-tabs" role="tablist" aria-label="Files">${FILES.map(([k, label]) => `<button class="file-tab" role="tab" data-file="${k}" aria-selected="${k === 'main'}">${label}</button>`).join('')}</div>
        <div class="editor-meta"><span data-save role="status">Saved</span><label><span class="sr-only">Language</span><select data-language><option value="cpp">C++20</option><option value="python">Python</option></select></label></div></div>
      <div class="editor-host" data-editor></div>
      <p class="editor-note" data-file-note hidden></p>
      <div class="custom-input"><label class="field" style="padding-top:.75rem">Input<textarea data-input rows="4" spellcheck="false" placeholder="Paste a sample from the problem page, or a case of your own."></textarea></label></div>
      <div class="run-bar"><button class="btn btn-secondary btn-sm" type="button" data-run="run">${icon('play')}Run on this input</button><span class="spacer"></span><label>Generated tests<input type="number" data-cases min="1" max="1000" value="200"></label><button class="btn btn-secondary btn-sm" type="button" data-run="stress">Stress against my brute force</button></div>
    </section>
    <section class="surface results" aria-label="Results" aria-live="polite" data-results><h3>Results</h3><p class="results-empty">Your code runs here in a sandbox. The real verdict comes from ${e(p.site)}.</p></section>
    <section class="surface" data-help></section>
    <section class="surface" data-finish></section>
    <div data-after></div>
  </div>`;
  const $ = s => root.querySelector(s);
  const results = $('[data-results]'), saveNode = $('[data-save]');
  $('[data-language]').value = language;

  /* ----- commit to an approach ----- */
  function paintCommit() {
    $('[data-commit]').hidden = p.finished && !p.committed;
    $('[data-commit]').innerHTML = p.committed
      ? `<h2>Your first approach</h2><p class="committed">${e(p.approach)}</p>${p.cue ? `<p class="muted small">What in the statement suggested it: ${e(p.cue)}</p>` : ''}`
      : `<details class="optional"><summary><strong>Write down your approach first</strong> <span class="muted small">· optional</span></summary><p class="muted small">If you want a record of your first idea to compare with what cracked it. It is saved once and cannot be edited. A tutor, if you ask one, starts from it.</p>
        <form data-commit-form><label class="field">The approach, and why you think it works<textarea name="approach" rows="3" maxlength="6000" placeholder="Sort by …, then …, because …"></textarea></label>
        <label class="field" style="margin-top:.75rem">The words or numbers in the statement that suggested it<input type="text" name="cue" maxlength="2000" placeholder="“n ≤ 20”, “any order”, “minimum number of moves” …"></label>
        <div class="step-actions"><button class="btn btn-secondary btn-sm" type="submit">Record my approach</button></div></form></details>`;
    $('[data-commit-form]')?.addEventListener('submit', async event => {
      event.preventDefault();
      try { p = await post('/problem/commit', {id, approach: event.target.elements.approach.value, cue: event.target.elements.cue.value}); paintAll(); toast('Approach recorded.', 'success'); }
      catch (error) { toast(error.message, 'error'); }
    });
  }

  /* ----- help: smaller questions, then the editorial ----- */
  function paintHelp() {
    const host = $('[data-help]');
    if (p.finished) { host.hidden = true; return; }
    host.hidden = false;
    const more = p.nudges.length < p.nudges_total;
    host.innerHTML = `<h2>Help</h2><p class="muted small">Any help means this cannot count as a cold solve, and the idea will come back later inside a different problem.</p>
      ${p.nudges.length ? `<ol class="nudges">${p.nudges.map(n => `<li>${inline(n)}</li>`).join('')}</ol>` : ''}
      <div class="step-actions">${more ? `<button class="btn btn-secondary btn-sm" type="button" data-nudge>Ask a smaller question (${p.nudges.length + 1} of ${p.nudges_total})</button>` : p.nudges_total ? '<span class="muted small">No more questions for this one.</span>' : ''}
      ${p.editorial_opened ? (p.editorial ? `<a class="btn btn-secondary btn-sm" href="${e(p.editorial)}" target="_blank" rel="noopener noreferrer">${icon('external')}Editorial</a>` : '<span class="muted small">Editorial marked as opened; find it on the problem page.</span>') : '<button class="btn btn-ghost btn-sm" type="button" data-editorial>I am going to read the editorial</button>'}
      <button class="btn btn-ghost btn-sm" type="button" data-tutor>Talk it through with a tutor</button></div>`;
    host.querySelector('[data-tutor]')?.addEventListener('click', () => askTutor(ctx, {scope: 'problem', id}, {unfinished: true, warn: 'After this the problem can no longer count as a cold solve.'}));
    host.querySelector('[data-nudge]')?.addEventListener('click', async () => {
      if (!p.nudges.length && !p.editorial_opened && !await dialog({title: 'Ask a smaller question?', body: 'After this the problem can no longer count as a cold solve.', confirm: 'Ask'})) return;
      try { const r = await post('/nudge', {scope: 'problem', id}); p.nudges = r.nudges; paintHelp(); } catch (error) { toast(error.message, 'error'); }
    });
    host.querySelector('[data-editorial]')?.addEventListener('click', async () => {
      if (!await dialog({title: 'Open the editorial?', body: 'It is recorded. Try to stop reading at the first sentence that gives you the idea, then come back and finish it yourself.', confirm: 'Record it and open'})) return;
      try { p = await post('/problem/editorial', {id}); paintHelp(); if (p.editorial) window.open(p.editorial, '_blank', 'noopener'); } catch (error) { toast(error.message, 'error'); }
    });
  }

  /* ----- the verdict ----- */
  function paintFinish() {
    const host = $('[data-finish]');
    if (p.finished) { host.hidden = true; return; }
    host.hidden = false;
    const handle = p.site === 'Codeforces' ? settings.cf_handle : settings.atcoder_handle;
    host.innerHTML = `<h2>The verdict</h2>${p.verifiable
      ? `<p class="muted small">Submit on ${e(p.site)}. When it is accepted there, check here: the app reads your public submission list${handle ? ` for <strong>${e(handle)}</strong>` : ''}.</p>${handle ? '' : `<p class="inline-error">Add your ${e(p.site)} handle in <a href="#/settings">Settings</a> first.</p>`}`
      : `<p class="muted small">${e(p.site)} has no public submission list, so this one is your word. It counts as applied, never as a cold solve.</p>`}
      <div class="step-actions">${p.verifiable ? `<button class="btn btn-primary" type="button" data-check ${handle ? '' : 'disabled'}>Check my submissions</button>` : `<button class="btn btn-primary" type="button" data-report>It was accepted</button>`}
      <button class="btn btn-ghost" type="button" data-giveup>Give up and see what cracked it</button></div>`;
    host.querySelector('[data-check]')?.addEventListener('click', async event => {
      event.target.disabled = true;
      try {
        await flush();
        const r = await post('/problem/check', {id});
        if (!r.found) { toast(`No accepted submission for this problem on ${p.site} yet.`, 'info'); event.target.disabled = false; return; }
        p = r; paintAll(); done(r);
      } catch (error) { toast(error.message, 'error'); event.target.disabled = false; }
    });
    host.querySelector('[data-report]')?.addEventListener('click', async () => { try { const r = await post('/problem/report', {id}); p = r; paintAll(); done(r); } catch (error) { toast(error.message, 'error'); } });
    host.querySelector('[data-giveup]')?.addEventListener('click', async () => {
      if (!await dialog({title: 'Give up on this one?', body: 'You will see the observations that crack it. The ideas involved come back later in a different problem.', confirm: 'Show me', danger: true})) return;
      try { p = await post('/problem/giveup', {id}); paintAll(); $('[data-after]').scrollIntoView({behavior: 'smooth'}); } catch (error) { toast(error.message, 'error'); }
    });
  }
  function done(r) {
    toast(r.cold ? 'Accepted, cold. That is real evidence.' : r.before_open ? 'Accepted earlier, before it was opened here: counted as applied.' : 'Accepted.', 'success');
    if (r.band_raised_to) toast(`Seven cold solves in ten: you now work at ${r.band_raised_to}.`, 'success');
    ctx.sync();
    $('[data-after]').scrollIntoView({behavior: 'smooth'});
  }

  /* ----- afterwards: what cracked it, and why it went as it did ----- */
  function paintAfter() {
    const host = $('[data-after]');
    if (!p.finished) { host.innerHTML = ''; return; }
    const status = p.solved ? (p.cold ? '<span class="badge badge-success">Solved cold</span>' : `<span class="badge badge-primary">Solved${p.verdict_source === 'self' ? ' (your report)' : ' with help or history'}</span>`) : '<span class="badge">Given up</span>';
    const causes = [...CAUSES, ...(p.cold ? [['none', 'Nothing was in the way: I saw it']] : [])];
    host.innerHTML = `<section class="surface reveal"><p class="eyebrow">What cracked it</p><h2>${status}</h2>
      <ol class="observations">${p.observations.map(o => `<li>${inline(o)}</li>`).join('')}</ol>
      <h3>It rests on</h3><ul class="plain-list">${p.ideas.map(i => `<li>${i.derived ? `<strong>${e(i.name)}</strong>` : i.has_chain ? `an idea you have not derived yet · <a href="#/chain/${e(i.id)}">derive it</a>` : 'an idea whose chain is not written yet'}</li>`).join('')}</ul>
      ${p.editorial ? `<p><a href="${e(p.editorial)}" target="_blank" rel="noopener noreferrer">Editorial</a></p>` : ''}
      <h3>${p.cold ? 'Anything in the way?' : 'What was in the way?'}</h3>
      <form data-cause class="choices">${causes.map(([k, label]) => `<label class="choice"><input type="radio" name="cause" value="${k}" ${p.cause === k ? 'checked' : ''}><span>${label}</span></label>`).join('')}</form>
      <div class="step-actions"><a class="btn btn-primary" href="#/solve">Next problem</a><button class="btn btn-secondary" type="button" data-teach>Have a tutor teach the solution</button><a class="btn btn-ghost" href="#/mastery">What you can do</a></div></section>`;
    host.querySelector('[data-teach]').addEventListener('click', () => askTutor(ctx, {scope: 'problem', id}));
    host.querySelector('[data-cause]').addEventListener('change', async event => {
      try { p = await post('/problem/cause', {id, cause: event.target.value}); toast('Recorded.', 'success'); } catch (error) { toast(error.message, 'error'); }
    });
  }
  function paintAll() { paintCommit(); paintHelp(); paintFinish(); paintAfter(); }

  /* ----- notes and code, saved as typed ----- */
  $('[data-notes]').addEventListener('input', event => { clearTimeout(noteTimer); noteTimer = setTimeout(() => post('/problem/notes', {id, notes: event.target.value}).catch(() => {}), 800); });
  const saveFile = async name => { if (!dirty[name]) return; dirty[name] = false; try { await post('/code', {id, language, file: name, code: files[name]}); } catch (error) { dirty[name] = true; throw error; } };
  const flush = async () => {
    clearTimeout(saveTimer);
    if (editor) files[file] = editor.getValue();
    if (!Object.values(dirty).some(Boolean)) return;
    saveNode.textContent = 'Saving…';
    try { for (const [name] of FILES) await saveFile(name); saveNode.textContent = 'Saved'; } catch (error) { saveNode.textContent = 'Not saved'; toast('Could not save: ' + error.message, 'error'); }
  };
  const changed = value => { files[file] = value; dirty[file] = true; saveNode.textContent = 'Unsaved changes'; clearTimeout(saveTimer); saveTimer = setTimeout(flush, 900); };
  const NOTES = {brute: 'The obviously correct, slow solution. Stress compares your real solution against it.', gen: 'Reads one whole number (a seed) and prints one small random test. Use the seed to seed your random numbers.'};
  const showFile = name => {
    file = name;
    const pending = {...dirty};
    editor.setValue(files[name]);
    Object.assign(dirty, pending);                         // switching tabs is not an edit
    if (!Object.values(dirty).some(Boolean)) { clearTimeout(saveTimer); saveNode.textContent = 'Saved'; }
    root.querySelectorAll('.file-tab').forEach(t => t.setAttribute('aria-selected', String(t.dataset.file === name)));
    const note = $('[data-file-note]'); note.hidden = !NOTES[name]; note.textContent = NOTES[name] || '';
  };
  editor = await makeEditor($('[data-editor]'), {value: files.main, language, fontSize: settings.font_size, tabSize: 4, onChange: changed, onRun: () => run('run')});
  if (!alive()) { editor.destroy(); return; }
  root.querySelectorAll('.file-tab').forEach(tab => tab.addEventListener('click', () => { files[file] = editor.getValue(); showFile(tab.dataset.file); }));
  $('[data-language]').addEventListener('change', async event => {
    await flush();
    language = event.target.value;
    try { files = (await api(`/code/${encodeURIComponent(id)}?language=${language}`)).files; editor.setLanguage(language); showFile(file); Object.keys(dirty).forEach(k => { dirty[k] = false; }); saveNode.textContent = 'Saved'; }
    catch (error) { toast(error.message, 'error'); }
  });

  /* ----- running code ----- */
  const box = (title, text) => `<div class="io-box"><h4>${title}</h4><pre>${e(text === '' ? '(empty)' : text)}</pre></div>`;
  async function run(kind) {
    if (running) return;
    files[file] = editor.getValue();
    clearTimeout(saveTimer);
    const body = {kind, id, language, main: files.main, input: $('[data-input]').value};
    if (kind === 'stress') Object.assign(body, {brute: files.brute, gen: files.gen, cases: Math.min(1000, Math.max(1, Number($('[data-cases]').value) || 200))});
    running = true;
    root.querySelectorAll('[data-run]').forEach(b => { b.disabled = true; });
    results.innerHTML = `<h3>Results</h3><div class="loading-block" style="min-height:5rem" role="status"><span class="spinner"></span>${kind === 'run' ? 'Compiling and running…' : 'Generating tests and comparing…'}</div>`;
    results.scrollIntoView({behavior: 'smooth', block: 'nearest'});
    try {
      const queued = await post('/run', body);
      Object.keys(dirty).forEach(k => { if (k in body) dirty[k] = false; });
      saveNode.textContent = 'Saved';
      const job = await waitFor(queued.job, () => !stopped);
      if (!job || stopped) return;
      const r = job.result || {};
      if (job.status === 'error') results.innerHTML = `<h3>Results</h3><p class="inline-error" role="alert">${e(r.error || 'The run could not finish.')}</p>`;
      else {
        const good = r.verdict === 'OK' || r.verdict === 'SAME';
        const stats = [r.seconds != null ? `${Number(r.seconds).toFixed(3)} s` : '', r.memory_kb ? `${(r.memory_kb / 1024).toFixed(1)} MiB` : '', r.cases != null ? `${r.cases} tests passed` : ''].filter(Boolean).join(' · ');
        results.innerHTML = `<h3>${kind === 'run' ? 'Run' : 'Stress test'}</h3><div class="result-head"><span class="verdict ${good ? 'verdict-ok' : 'verdict-bad'}">${e(r.verdict)}</span><strong>${e(VERDICTS[r.verdict] || r.verdict)}</strong><span class="result-stats">${e(stats)}</span></div>
          ${r.detail ? `<p class="result-detail">${e(r.detail)}</p>` : ''}<div class="io-grid">${r.input != null ? box('The test', r.input) : ''}${kind === 'run' && r.verdict === 'OK' || r.output != null && kind === 'stress' ? box('Your output', r.output ?? '') : ''}${r.expected != null ? box('Brute force says', r.expected) : ''}</div>`;
      }
    } catch (error) { if (!stopped) results.innerHTML = `<h3>Results</h3><p class="inline-error" role="alert">${e(error.message)}</p>`; }
    finally { running = false; if (!stopped) root.querySelectorAll('[data-run]').forEach(b => { b.disabled = false; }); }
  }
  root.querySelectorAll('[data-run]').forEach(b => b.addEventListener('click', () => run(b.dataset.run)));

  ctx.onCleanup(() => {
    stopped = true;
    clearTimeout(saveTimer); clearTimeout(noteTimer);
    try { files[file] = editor.getValue(); } catch { /* editor already gone */ }
    // Leaving the page: send what is unsaved without waiting for the reply.
    const send = (path, body) => fetch('/api' + path, {method: 'POST', keepalive: true, headers: {'Content-Type': 'application/json', 'X-Derive-Token': ctx.boot.csrf}, body: JSON.stringify(body)}).catch(() => {});
    for (const [name] of FILES) if (dirty[name]) send('/code', {id, language, file: name, code: files[name]});
    const notes = root.querySelector('[data-notes]'); if (notes && notes.value !== (p.notes || '')) send('/problem/notes', {id, notes: notes.value});
    try { editor.destroy(); } catch { /* ignore */ }
  });
  paintAll();
}
