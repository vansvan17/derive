/* A derivation chain: one small question at a time. The next question appears only
   when this one is right, and the name of the result only at the very end. */

import {marks} from './marks.js';

/* The stored options list the right one first. On screen they are shown in an order that is fixed for
   each question (so it does not jump about while you think) but differs from question to question.
   The value sent is still the stored index. */
function shownOrder(key, n) {
  let h = 2166136261;
  for (const ch of key) { h ^= ch.codePointAt(0); h = Math.imul(h, 16777619) >>> 0; }
  const order = [...Array(n).keys()];
  for (let i = n - 1; i > 0; i--) {
    h ^= h << 13; h >>>= 0; h ^= h >>> 17; h ^= h << 5; h >>>= 0;
    const j = h % (i + 1);
    [order[i], order[j]] = [order[j], order[i]];
  }
  return order;
}
import {askTutor} from './tutor.js';
import {mountTask} from './tasks.js';
import {makeEditor} from './problem.js';

const HINTS = {
  number: 'A whole number, or a fraction like 3/4.',
  list: 'Numbers separated by commas or spaces.',
  formula: 'A formula. Write powers as ^, e.g. n*(n+1)/2. You may use gcd, min, max, C(n,k), fact.',
  counterexample: 'Whole numbers separated by commas.',
};

export async function renderChain(ctx, idea) {
  const {api, post, waitFor, escape: e, icon, inline, markdown, toast, dialog, navigate} = ctx;
  const root = ctx.root, alive = () => ctx.root === root;
  let chain = await api('/chain/' + encodeURIComponent(idea));
  let notes = chain.notes || '', notesTimer = null, notesSaved = true, notesSent = notes;
  const saveNotes = async () => { if (notes === notesSent) return; const sending = notes; try { await post('/chain/notes', {idea, notes: sending}); notesSent = sending; notesSaved = true; } catch { notesSaved = false; } };
  let pad = null, padInput = '', padLanguage = '';            // the code pad's editor while it is open
  const padCode = {};                                         // what was last in the pad, per language, so a redraw loses nothing
  try { padLanguage = localStorage.getItem('derive-codepad-language') || ''; } catch { /* default below */ }
  ctx.onCleanup(() => { clearTimeout(notesTimer); saveNotes(); pad?.destroy(); });
  if (!alive()) return;
  let feedback = null;      // {kind: 'wrong'|'unreadable', text} for the current step

  function doneStep(step, index) {
    return `<li class="step is-done"><div class="step-num" aria-hidden="true">${icon('check')}</div><div class="step-body"><div class="step-prompt">${markdown(step.prompt)}</div>
      <p class="step-answer"><span class="muted">${step.kind === 'code' ? 'Your program:' : 'Your answer:'}</span> ${step.kind === 'choice' ? inline(step.options[Number(step.answer)] ?? step.answer) : e(step.answer)}</p>
      <p class="step-showed">${inline(step.showed)}</p></div></li>`;
  }
  function input(step) {
    if (step.kind === 'choice') return `<fieldset class="choices"><legend class="sr-only">Options</legend>${shownOrder(chain.idea + '/' + step.id, step.options.length).map(i => `<label class="choice"><input type="radio" name="answer" value="${i}"><span>${inline(step.options[i])}</span></label>`).join('')}</fieldset>`;
    if (step.kind === 'proof') {
      const p = step.proof, status = p?.status;
      const note = status === 'fail' ? `<div class="grade grade-fail" role="status"><strong>Not yet.</strong> ${e(p.feedback.gap || '')}${p.feedback.question ? `<p class="grade-question">${e(p.feedback.question)}</p>` : ''}</div>`
        : status === 'awaiting' ? `<div class="grade" role="status"><strong>Saved, waiting for a grade.</strong> ${e(p.feedback.reason || 'Automatic grading is off.')} <span data-manual></span></div>`
        : status === 'grading' ? '<div class="grade" role="status"><span class="spinner"></span> Being graded…</div>' : '';
      return `<label class="field"><span class="sr-only">Your proof</span><textarea name="proof" rows="8" maxlength="12000" placeholder="State each claim and why it is true. Full sentences; no need for symbols.">${e(p && status !== 'pass' ? p.text : '')}</textarea></label>${note}`;
    }
    const names = step.vars ? ` (${step.vars.join(', ')})` : '';
    return `<label class="field"><span class="sr-only">Your answer</span><input type="text" name="answer" autocomplete="off" spellcheck="false" inputmode="${step.kind === 'number' ? 'text' : 'text'}" placeholder="${step.kind === 'counterexample' ? e(step.vars.join(', ')) : 'Your answer'}"></label><p class="step-hint">${HINTS[step.kind] || ''}${step.kind === 'counterexample' ? e(names) : ''}</p>`;
  }
  /* A scratch pad for the chain: small cases, tables, guesses. It belongs to the chain, not to one question,
     so what you wrote for an earlier question is still there for the next. Saved as you type. */
  function scratch() {
    let open = true;
    try { open = localStorage.getItem('derive-scratch') !== 'closed'; } catch { /* stays open */ }
    return `<details class="scratch" data-scratch ${open ? 'open' : ''}><summary>Scratch pad <span class="muted small" data-scratch-status></span></summary>
      <textarea class="input notes" data-scratch-text rows="6" spellcheck="false" aria-label="Scratch pad" placeholder="Small cases, a table, a guess. Not checked, only saved.">${e(notes)}</textarea></details>`;
  }
  /* A code pad for the chain: a small editor to compute something instead of doing it by hand
     (how many ways for 15, the first number with some property). It runs on this computer; nothing judges it. */
  function codePadShell() {
    let open = false;
    try { open = localStorage.getItem('derive-codepad') === 'open'; } catch { /* stays closed */ }
    return `<details class="scratch" data-codepad ${open ? 'open' : ''}><summary>Code pad <span class="muted small">· run a quick program</span></summary><div data-codepad-body></div></details>`;
  }
  async function mountPad(host) {
    if (pad || !host || host.dataset.mounted) return;
    host.dataset.mounted = '1';
    let language = ['cpp', 'python'].includes(padLanguage) ? padLanguage : (ctx.boot.settings.language || 'cpp');
    const load = async lang => padCode[lang] != null ? {main: padCode[lang]} : (await api(`/code/${encodeURIComponent(idea)}?language=${lang}`)).files;
    let files = await load(language);
    if (!host.isConnected) return;
    host.innerHTML = `<div class="codepad"><div class="editor-bar"><span class="muted small" data-pad-save role="status">Saved</span><div class="editor-meta"><label><span class="sr-only">Language</span><select data-pad-language><option value="python" ${language === 'python' ? 'selected' : ''}>Python</option><option value="cpp" ${language === 'cpp' ? 'selected' : ''}>C++20</option></select></label><button class="btn btn-primary btn-sm" type="button" data-pad-run>Run</button></div></div>
      <div class="editor-host codepad-host" data-pad-editor></div>
      <label class="field codepad-input">Input <span class="muted small">(optional)</span><textarea data-pad-input rows="2" spellcheck="false">${e(padInput)}</textarea></label>
      <pre class="codepad-out" data-pad-out aria-live="polite">Output appears here. Ctrl or Cmd + Enter runs it.</pre></div>`;
    const $ = q => host.querySelector(q);
    let timer = null, busy = false;
    const save = async () => { try { await post('/code', {id: idea, language, file: 'main', code: files.main}); if (host.isConnected) $('[data-pad-save]').textContent = 'Saved'; } catch { if (host.isConnected) $('[data-pad-save]').textContent = 'Not saved'; } };
    const run = async () => {
      if (busy) return;
      busy = true; files.main = editor.getValue(); padInput = $('[data-pad-input]').value;
      const out = $('[data-pad-out]'); out.textContent = 'Running…'; out.className = 'codepad-out';
      try {
        const job = await waitFor((await post('/run', {kind: 'run', id: idea, language, main: files.main, input: padInput})).job, () => host.isConnected);
        if (!job || !host.isConnected) return;
        const r = job.result || {};
        if (job.status === 'error') { out.textContent = r.error || 'The run could not finish.'; out.classList.add('is-bad'); }
        else if (r.verdict === 'OK') out.textContent = (r.output === '' ? '(no output)' : r.output) + (r.seconds != null ? `\n\n[${Number(r.seconds).toFixed(2)} s]` : '');
        else { out.textContent = `${r.verdict}${r.detail ? ': ' + r.detail : ''}${r.output ? '\n' + r.output : ''}`; out.classList.add('is-bad'); }
      } catch (error) { out.textContent = error.message; out.classList.add('is-bad'); }
      finally { busy = false; }
    };
    const editor = await makeEditor($('[data-pad-editor]'), {value: files.main, language, fontSize: ctx.boot.settings.font_size, tabSize: 4, onRun: run,
      onChange: value => { files.main = value; padCode[language] = value; $('[data-pad-save]').textContent = 'Editing…'; clearTimeout(timer); timer = setTimeout(save, 800); }});
    if (!host.isConnected) { editor.destroy(); return; }
    pad = {destroy: () => { clearTimeout(timer); try { files.main = editor.getValue(); padCode[language] = files.main; save(); editor.destroy(); } catch { /* already gone */ } pad = null; }};
    $('[data-pad-run]').addEventListener('click', run);
    $('[data-pad-language]').addEventListener('change', async event => {
      files.main = editor.getValue(); padCode[language] = files.main; await save();
      language = padLanguage = event.target.value;
      try { localStorage.setItem('derive-codepad-language', language); } catch { /* fine */ }
      files = await load(language);
      editor.setLanguage(language); editor.setValue(files.main);
    });
  }
  function currentStep(step, index) {
    const more = step.nudges.length < step.nudges_total;
    if (step.kind === 'code') return `<li class="step is-current step-code" data-current><div class="step-num" aria-hidden="true">${index + 1}</div><div class="step-body">${step.hard ? '<p class="eyebrow">Hard part · write it</p>' : '<p class="eyebrow">Write it</p>'}<div class="step-prompt">${markdown(step.prompt)}</div>
      ${step.nudges.length ? `<ol class="nudges">${step.nudges.map(n => `<li>${inline(n)}</li>`).join('')}</ol>` : ''}
      <div class="step-actions">${more ? `<button class="btn btn-ghost" type="button" data-nudge>Ask a smaller question (${step.nudges.length + 1} of ${step.nudges_total})</button>` : ''}<button class="btn btn-ghost" type="button" data-tutor>Ask a tutor</button></div>
      <div data-code-step></div></div></li>`;
    return `<li class="step is-current" data-current><div class="step-num" aria-hidden="true">${index + 1}</div><div class="step-body">${step.hard ? '<p class="eyebrow">Hard part</p>' : ''}<div class="step-prompt">${markdown(step.prompt)}</div>
      <form data-answer novalidate>${input(step)}
        ${feedback ? `<p class="step-feedback ${feedback.kind}" role="alert">${e(feedback.text)}</p>` : ''}
        ${step.nudges.length ? `<ol class="nudges">${step.nudges.map(n => `<li>${inline(n)}</li>`).join('')}</ol>` : ''}
        <div class="step-actions"><button class="btn btn-primary" type="submit">${step.kind === 'proof' ? 'Submit proof' : 'Check'}</button>${more ? `<button class="btn btn-ghost" type="button" data-nudge>Ask a smaller question (${step.nudges.length + 1} of ${step.nudges_total})</button>` : ''}<button class="btn btn-ghost" type="button" data-tutor>Ask a tutor</button></div>
      </form>${scratch()}${codePadShell()}</div></li>`;
  }

  function paint(focus = false) {
    pad?.destroy();                                          // the page is redrawn: the code pad is saved and rebuilt
    const done = chain.steps.filter(s => s.done).length;
    const reveal = chain.complete ? `<section class="surface reveal" data-reveal><p class="eyebrow">You have just derived</p><h2>${e(chain.reveal.name)}</h2><div class="reveal-statement">${markdown(chain.reveal.statement)}</div>${chain.reveal.remark ? `<p class="muted">${inline(chain.reveal.remark)}</p>` : ''}<div class="step-actions"><a class="btn btn-primary" href="#/derive">Next chain</a>${chain.reveal.problems ? `<a class="btn btn-secondary" href="#/solve">Use it on a real problem</a>` : ''}<a class="btn btn-ghost" href="#/">See it on the map</a></div>${chain.practice.length ? `<h3>Practise it</h3><p class="muted small">Standard tasks from the CSES problem set that lean on this idea (some also need a little standard implementation). Tick them off as you get them accepted there.</p><ul class="plain-list practice">${chain.practice.map(t => `<li><label class="choice"><input type="checkbox" data-practice="${e(t.url)}" ${t.done ? 'checked' : ''}><span><a href="${e(t.url)}" target="_blank" rel="noopener noreferrer">${e(t.title)}</a> <span class="muted small">· CSES</span></span></label></li>`).join('')}</ul>` : ''}<p class="muted small">Want it explained properly now that you have derived it? <button class="link-btn" type="button" data-teach>Have a tutor teach it in full</button></p></section>` : '';
    root.innerHTML = `<div class="reading"><header class="chain-head"><p class="eyebrow">${e(chain.area)} · ${chain.complete ? 'derived' : `step ${Math.min(done + 1, chain.total)} of ${chain.total}`}</p><h1>${chain.cses ? e(chain.cses.title) : chain.complete ? e(chain.reveal.name) : 'A chain of questions'}</h1>${chain.cses ? `<p class="muted"><a href="#/cses">CSES dynamic programming</a> · read the statement first: <a href="${e(chain.cses.url)}" target="_blank" rel="noopener noreferrer">${e(chain.cses.title)} on CSES</a></p>` : ''}${chain.marks.length ? `<p>${marks(chain.marks, e)}</p>` : ''}<p class="chain-opening">${inline(chain.opening)}</p>
      ${chain.can_skip ? `<p class="muted small">Finding this too easy? ${chain.has_hard ? `The last ${chain.hard_total} questions of this chain are the hard ones, with no pointers.` : 'You can skip the opening questions and go straight to the part that counts.'} <button class="link-btn" type="button" data-skip>Skip the warm-up</button></p>` : ''}<div class="dots" role="img" aria-label="${done} of ${chain.total} steps done">${Array.from({length: chain.total}, (_, i) => `<span class="${i < done ? 'is-done' : i === done ? 'is-here' : ''}"></span>`).join('')}</div></header>
      <ol class="steps">${chain.steps.map((s, i) => s.done ? doneStep(s, i) : currentStep(s, i)).join('')}</ol>${reveal}</div>`;
    const step = chain.steps.find(s => !s.done);
    const codeHost = root.querySelector('[data-code-step]');
    if (codeHost && step?.kind === 'code') {
      // The step is finished by the judge: mount the task here and move on when it is accepted.
      mountTask(ctx, codeHost, step.task, {heading: false, onAccepted: () => refresh(true)});
      root.querySelector('[data-nudge]')?.addEventListener('click', () => nudge(step));
      root.querySelector('[data-tutor]')?.addEventListener('click', () => askTutor(ctx, {scope: 'chain', idea, step: step.id}, {unfinished: true}));
    }
    const form = root.querySelector('[data-answer]');
    if (form && step) {
      form.addEventListener('submit', event => { event.preventDefault(); step.kind === 'proof' ? submitProof(form, step) : submit(form, step); });
      root.querySelector('[data-nudge]')?.addEventListener('click', () => nudge(step));
      root.querySelector('[data-tutor]')?.addEventListener('click', () => askTutor(ctx, {scope: 'chain', idea, step: step.id}, {unfinished: true}));
      root.querySelector('[data-manual]')?.replaceChildren(manualLink(step));
      if (step.kind === 'proof' && step.proof?.status === 'grading') watch(step);
      if (focus) { root.querySelector('[data-current]').scrollIntoView({behavior: 'smooth', block: 'center'}); form.querySelector('input[type=text], textarea')?.focus({preventScroll: true}); }
    }
    const codepad = root.querySelector('[data-codepad]');
    if (codepad) {
      const body = codepad.querySelector('[data-codepad-body]');
      if (codepad.open) mountPad(body);
      codepad.addEventListener('toggle', () => { try { localStorage.setItem('derive-codepad', codepad.open ? 'open' : 'closed'); } catch { /* fine */ } if (codepad.open) mountPad(body); });
    }
    const padText = root.querySelector('[data-scratch-text]');
    if (padText) {
      const status = root.querySelector('[data-scratch-status]');
      padText.addEventListener('input', () => { notes = padText.value; status.textContent = '· editing'; clearTimeout(notesTimer); notesTimer = setTimeout(async () => { await saveNotes(); if (status.isConnected) status.textContent = notesSaved ? '· saved' : '· not saved'; }, 700); });
      root.querySelector('[data-scratch]').addEventListener('toggle', event => { try { localStorage.setItem('derive-scratch', event.target.open ? 'open' : 'closed'); } catch { /* fine */ } });
    }
    root.querySelector('[data-teach]')?.addEventListener('click', () => askTutor(ctx, {scope: 'chain', idea}));
    root.querySelector('[data-skip]')?.addEventListener('click', async () => { try { chain = await post('/chain/skip', {idea}); feedback = null; paint(true); ctx.sync(); } catch (error) { toast(error.message, 'error'); } });
    root.querySelectorAll('[data-practice]').forEach(box => box.addEventListener('change', async () => {
      try { await post('/practice', {url: box.dataset.practice, done: box.checked}); } catch (error) { box.checked = !box.checked; toast(error.message, 'error'); }
    }));
    if (focus && chain.complete) root.querySelector('[data-reveal]').scrollIntoView({behavior: 'smooth', block: 'center'});
  }

  async function refresh(focus) { chain = await api('/chain/' + encodeURIComponent(idea)); if (alive()) { paint(focus); ctx.sync(); } }

  async function submit(form, step) {
    const field = form.elements.answer;
    const value = step.kind === 'choice' ? (form.querySelector('input[name=answer]:checked')?.value ?? '') : field.value;
    if (value === '' || (typeof value === 'string' && !value.trim())) { feedback = {kind: 'unreadable', text: step.kind === 'choice' ? 'Pick one of the options.' : 'Write an answer first.'}; return keep(form, value); }
    const button = form.querySelector('button[type=submit]');
    button.disabled = true;
    try {
      const result = await post('/chain/answer', {idea, step: step.id, answer: step.kind === 'choice' ? Number(value) : value});
      if (result.correct) { feedback = null; await refresh(true); return; }
      feedback = result.unreadable ? {kind: 'unreadable', text: result.message} : {kind: 'wrong', text: 'Not that. ' + (result.message || 'Look again, or ask a smaller question.')};
    } catch (error) { feedback = {kind: 'unreadable', text: error.message}; }
    keep(form, value);
  }
  /* Repaint with the message, keeping what was typed. */
  function keep(form, value) {
    paint();
    const again = root.querySelector('[data-answer]');
    if (!again) return;
    const field = again.querySelector('input[type=text]');
    if (field) { field.value = value; field.focus(); field.select(); }
    else again.querySelectorAll('input[type=radio]').forEach(r => { r.checked = r.value === String(value); });
  }
  async function nudge(step) {
    const typed = root.querySelector('[data-answer] input[type=text], [data-answer] textarea')?.value;
    try { await post('/nudge', {idea, step: step.id}); chain = await api('/chain/' + encodeURIComponent(idea)); }
    catch (error) { toast(error.message, 'error'); return; }
    if (!alive()) return;
    paint();
    const field = root.querySelector('[data-answer] input[type=text], [data-answer] textarea');
    if (field && typed != null) field.value = typed;
  }

  async function submitProof(form, step) {
    const text = form.elements.proof.value.trim();
    const button = form.querySelector('button[type=submit]');
    button.disabled = true;
    try {
      const result = await post('/chain/proof', {idea, step: step.id, text});
      feedback = null;
      await refresh(false);
      if (result.status === 'awaiting') toast('Saved. Turn on proof grading in Settings, or grade it by hand.', 'info');
    } catch (error) { feedback = {kind: 'unreadable', text: error.message}; paint(); const area = root.querySelector('textarea[name=proof]'); if (area) area.value = text; }
  }
  /* A proof is being graded in the background: wait for the verdict, then show it. */
  let watching = false;
  async function watch(step) {
    if (watching) return;
    watching = true;
    try {
      for (let i = 0; i < 400 && alive(); i++) {
        await new Promise(resolve => setTimeout(resolve, 1500));
        const fresh = await api('/chain/' + encodeURIComponent(idea));
        const now = fresh.steps.find(s => s.id === step.id);
        if (fresh.complete || now?.done || now?.proof?.status !== 'grading') { chain = fresh; if (alive()) { paint(true); ctx.sync(); } return; }
      }
    } finally { watching = false; }
  }
  /* Grading by hand: copy the prompt into any Claude session, paste the JSON verdict back. */
  function manualLink(step) {
    const button = document.createElement('button');
    button.type = 'button'; button.className = 'link-btn'; button.textContent = 'Grade it by hand';
    button.addEventListener('click', async () => {
      const info = await api('/proof/' + step.proof.id);
      try { await navigator.clipboard.writeText(info.prompt); toast('Grading prompt copied. Paste it into Claude, then paste the reply here.', 'success'); } catch { /* shown in the dialog instead */ }
      const verdict = await dialog({title: 'Grade this proof by hand', body: 'The prompt is on your clipboard (and below). Paste it into a Claude session, then paste the whole JSON reply here.', html: `<details><summary class="muted">Show the prompt</summary><pre>${e(info.prompt)}</pre></details>`, confirm: 'Record the verdict', input: {label: 'The reply', placeholder: '{"pass": …}', rows: 6}, wide: true});
      if (!verdict || verdict === true) return;
      try { await post('/proof/verdict', {proof: step.proof.id, verdict}); await refresh(true); }
      catch (error) { toast(error.message, 'error'); }
    });
    return button;
  }

  paint();
  if (!chain.complete) root.querySelector('[data-current]')?.scrollIntoView({block: 'center'});
}
