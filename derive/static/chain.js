/* A derivation chain: one small question at a time. The next question appears only
   when this one is right, and the name of the result only at the very end. */

import {askTutor} from './tutor.js';

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
  if (!alive()) return;
  let feedback = null;      // {kind: 'wrong'|'unreadable', text} for the current step

  function doneStep(step, index) {
    return `<li class="step is-done"><div class="step-num" aria-hidden="true">${icon('check')}</div><div class="step-body"><div class="step-prompt">${markdown(step.prompt)}</div>
      <p class="step-answer"><span class="muted">Your answer:</span> ${step.kind === 'choice' ? inline(step.options[Number(step.answer)] ?? step.answer) : e(step.answer)}</p>
      <p class="step-showed">${inline(step.showed)}</p></div></li>`;
  }
  function input(step) {
    if (step.kind === 'choice') return `<fieldset class="choices"><legend class="sr-only">Options</legend>${step.options.map((o, i) => `<label class="choice"><input type="radio" name="answer" value="${i}"><span>${inline(o)}</span></label>`).join('')}</fieldset>`;
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
  function currentStep(step, index) {
    const more = step.nudges.length < step.nudges_total;
    return `<li class="step is-current" data-current><div class="step-num" aria-hidden="true">${index + 1}</div><div class="step-body"><div class="step-prompt">${markdown(step.prompt)}</div>
      <form data-answer novalidate>${input(step)}
        ${feedback ? `<p class="step-feedback ${feedback.kind}" role="alert">${e(feedback.text)}</p>` : ''}
        ${step.nudges.length ? `<ol class="nudges">${step.nudges.map(n => `<li>${inline(n)}</li>`).join('')}</ol>` : ''}
        <div class="step-actions"><button class="btn btn-primary" type="submit">${step.kind === 'proof' ? 'Submit proof' : 'Check'}</button>${more ? `<button class="btn btn-ghost" type="button" data-nudge>Ask a smaller question (${step.nudges.length + 1} of ${step.nudges_total})</button>` : ''}<button class="btn btn-ghost" type="button" data-tutor>Ask a tutor</button></div>
      </form></div></li>`;
  }

  function paint(focus = false) {
    const done = chain.steps.filter(s => s.done).length;
    const reveal = chain.complete ? `<section class="surface reveal" data-reveal><p class="eyebrow">You have just derived</p><h2>${e(chain.reveal.name)}</h2><div class="reveal-statement">${markdown(chain.reveal.statement)}</div>${chain.reveal.remark ? `<p class="muted">${inline(chain.reveal.remark)}</p>` : ''}<div class="step-actions"><a class="btn btn-primary" href="#/derive">Next chain</a>${chain.reveal.problems ? `<a class="btn btn-secondary" href="#/solve">Use it on a real problem</a>` : ''}<a class="btn btn-ghost" href="#/">See it on the map</a></div><p class="muted small">Want it explained properly now that you have derived it? <button class="link-btn" type="button" data-teach>Have a tutor teach it in full</button></p></section>` : '';
    root.innerHTML = `<div class="reading"><header class="chain-head"><p class="eyebrow">${e(chain.area)} · ${chain.complete ? 'derived' : `step ${Math.min(done + 1, chain.total)} of ${chain.total}`}</p><h1>${chain.complete ? e(chain.reveal.name) : 'A chain of questions'}</h1><p class="chain-opening">${inline(chain.opening)}</p>
      <div class="dots" role="img" aria-label="${done} of ${chain.total} steps done">${Array.from({length: chain.total}, (_, i) => `<span class="${i < done ? 'is-done' : i === done ? 'is-here' : ''}"></span>`).join('')}</div></header>
      <ol class="steps">${chain.steps.map((s, i) => s.done ? doneStep(s, i) : currentStep(s, i)).join('')}</ol>${reveal}</div>`;
    const form = root.querySelector('[data-answer]');
    const step = chain.steps.find(s => !s.done);
    if (form && step) {
      form.addEventListener('submit', event => { event.preventDefault(); step.kind === 'proof' ? submitProof(form, step) : submit(form, step); });
      root.querySelector('[data-nudge]')?.addEventListener('click', () => nudge(step));
      root.querySelector('[data-tutor]')?.addEventListener('click', () => askTutor(ctx, {scope: 'chain', idea, step: step.id}, {unfinished: true}));
      root.querySelector('[data-manual]')?.replaceChildren(manualLink(step));
      if (step.kind === 'proof' && step.proof?.status === 'grading') watch(step);
      if (focus) { root.querySelector('[data-current]').scrollIntoView({behavior: 'smooth', block: 'center'}); form.querySelector('input[type=text], textarea')?.focus({preventScroll: true}); }
    }
    root.querySelector('[data-teach]')?.addEventListener('click', () => askTutor(ctx, {scope: 'chain', idea}));
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
