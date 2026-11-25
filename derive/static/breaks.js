/* Break it: a solution that looks right and is not. Read it, find what it gets wrong,
   and type an input that proves it. The program shown is the one that is run. */
import {sideButton, wireSplit} from './split.js';

export async function renderBreaks(ctx) {
  const {api, escape: e} = ctx;
  const root = ctx.root;
  const page = await api('/breaks');
  if (ctx.root !== root) return;
  const done = page.items.filter(i => i.broken).length;
  root.innerHTML = `<header class="page-head"><div><p class="eyebrow">Find the input that proves it wrong</p><h1>Break it</h1>
    <p class="muted">Each page shows a task and a solution that passes the examples but is wrong. Your job is not to fix it: it is to type a small input on which it prints the wrong answer. The first ones fall quickly; the later ones need the right shape of input. ${done} of ${page.items.length} broken.</p></div></header>
    <section class="surface"><ol class="task-list">${page.items.map(i => `<li><a href="#/break/${e(i.id)}">${e(i.title)}</a> ${i.broken ? `<span class="badge badge-success">broken${i.tries > 1 ? ` · ${i.tries} tries` : ' first try'}</span>` : i.tries ? `<span class="badge">${i.tries} ${i.tries === 1 ? 'try' : 'tries'}</span>` : ''}</li>`).join('')}</ol></section>`;
}

export async function renderBreak(ctx, id) {
  const {api, post, waitFor, escape: e, markdown, inline, toast} = ctx;
  const root = ctx.root, alive = () => ctx.root === root;
  const [list, first] = await Promise.all([api('/breaks'), api('/break/' + encodeURIComponent(id))]);
  if (!alive()) return;
  let item = first, busy = false, result = null;
  const at = list.items.findIndex(i => i.id === id), prev = list.items[at - 1], next = list.items[at + 1];
  const box = (title, text) => `<div><h4>${e(title)}</h4><pre>${e(text)}</pre></div>`;
  const link = (t, label, cls) => t ? `<a class="btn ${cls} btn-sm" href="#/break/${e(t.id)}" title="${e(t.title)}">${label}</a>` : `<span class="btn btn-ghost btn-sm" aria-disabled="true">${label}</span>`;
  const numbered = source => source.replace(/\n$/, '').split('\n').map(line => `<span class="ln">${e(line) || ' '}</span>`).join('\n');

  function results() {
    if (busy) return '<h3>Result</h3><p><span class="spinner"></span> Running the program on your input…</p>';
    if (!result) return item.broken ? `<h3>Broken</h3><p class="result-detail">You broke it with the input shown above${item.tries > 1 ? `, on try ${item.tries}` : ', on the first try'}.</p>` : '<h3>Result</h3><p class="results-empty">Type an input and run the program on it. It counts when the program\'s answer is wrong.</p>';
    if (result.valid === false) return `<h3>Result</h3><p class="inline-error">That input cannot be used: ${e(result.reason)}</p>`;
    const broke = result.verdict === 'BROKEN';
    return `<h3>Result</h3><div class="result-head"><span class="verdict ${broke ? 'verdict-ok' : result.verdict === 'SAME' ? 'verdict-neutral' : 'verdict-bad'}">${broke ? 'Broken' : result.verdict === 'SAME' ? 'Still standing' : 'Not judged'}</span><strong>${e(result.detail || '')}</strong></div>
      <div class="io-grid">${result.output != null ? box('The program printed', result.output || '(nothing)') : ''}${result.expected != null ? box('The right answer', result.expected) : ''}</div>`;
  }
  function paint() {
    const typed = root.querySelector('[data-input]')?.value;
    root.innerHTML = `<header class="page-head"><div><p class="eyebrow"><a href="#/break">Break it</a></p><h1>${e(item.title)}</h1></div><div>${item.broken ? '<span class="badge badge-success">Broken</span>' : item.tries ? `<span class="badge">${item.tries} ${item.tries === 1 ? 'try' : 'tries'} so far</span>` : ''}</div></header>
      <nav class="task-nav" aria-label="Other pages"><span class="muted small">${at + 1} of ${list.items.length}</span>${link(prev, '← Previous', 'btn-ghost')}${link(next, 'Next →', 'btn-secondary')}</nav>
      <div class="split" data-split><div class="split-pane split-text"><section class="surface reading task-statement"><h2>The task</h2>${markdown(item.statement)}
          <h3>Example${item.samples.length > 1 ? 's' : ''}</h3>${item.samples.map(s => `<div class="io-grid">${box('Input', s[0])}${box('Output', s[1])}</div>`).join('')}
          <h3>Your input</h3><p>It must follow the input format above, and stay small: <strong>${e(item.limits)}</strong>. Anything else is refused rather than counted.</p>
          ${item.why ? `<h3>Why it fails</h3><p>${inline(item.why)}</p>` : ''}
          ${item.nudges.length ? `<h3>Questions to think about</h3><ul>${item.nudges.map(n => `<li>${inline(n)}</li>`).join('')}</ul>` : ''}
          ${!item.broken && item.nudges_left ? `<p><button class="btn btn-ghost btn-sm" type="button" data-nudge>Ask me a smaller question (${item.nudges_left} left)</button></p>` : ''}</section></div>
        <div class="split-pane split-code"><section class="surface editor-card" aria-label="The solution to break"><div class="editor-bar"><span class="muted small">The solution to break (C++). It passes the example${item.samples.length > 1 ? 's' : ''}.</span><div class="editor-meta">${sideButton()}</div></div>
          <pre class="break-code" tabindex="0">${numbered(item.wrong)}</pre>
          <label class="field">An input that makes it print a wrong answer<textarea data-input rows="4" spellcheck="false" autocapitalize="off" autocomplete="off">${e(typed ?? item.input ?? '')}</textarea></label>
          <div class="run-bar"><span class="spacer"></span><button class="btn btn-primary" type="button" data-try ${busy ? 'disabled' : ''}>Run it on this input</button></div></section>
        <section class="surface results" aria-live="polite">${results()}</section></div></div>`;
    wireSplit(root.querySelector('[data-split]'));
    root.querySelector('[data-try]').addEventListener('click', go);
    root.querySelector('[data-input]').addEventListener('keydown', event => { if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') go(); });
    root.querySelector('[data-nudge]')?.addEventListener('click', async () => {
      try { item = await post('/break/nudge', {id}); paint(); } catch (error) { toast(error.message, 'error'); }
    });
  }
  async function go() {
    if (busy) return;
    const input = root.querySelector('[data-input]').value;
    busy = true; paint();
    try {
      const queued = await post('/break/try', {id, input});
      if (queued.valid === false) result = queued;
      else {
        const job = await waitFor(queued.job, alive);
        if (!job || !alive()) return;
        result = job.status === 'error' ? {verdict: 'ERROR', detail: job.result?.error || 'The run could not finish.'} : job.result;
        item = await api('/break/' + encodeURIComponent(id));
        ctx.sync();
      }
    } catch (error) { toast(error.message, 'error'); }
    finally { busy = false; if (alive()) paint(); }
  }
  paint();
}
