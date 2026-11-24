/* Puzzles: one short question at a time, in sets. Each has a single checked answer and,
   once you have it (or give up), the one-line reason behind it. */

export async function renderPuzzles(ctx, wanted = '') {
  const {api, post, escape: e, inline, markdown, toast} = ctx;
  const root = ctx.root, alive = () => ctx.root === root;
  let page = await api('/puzzles?set=' + encodeURIComponent(wanted));
  if (!alive()) return;
  let after = null;      // {correct, showed, first_try, shown} once the current puzzle is finished
  let feedback = '';

  function paint() {
    const p = page.puzzle, set = page.sets.find(s => s.id === page.set);
    const field = !p ? '' : p.kind === 'choice'
      ? `<fieldset class="choices"><legend class="sr-only">Options</legend>${p.options.map((o, i) => `<label class="choice"><input type="radio" name="answer" value="${i}"><span>${inline(o)}</span></label>`).join('')}</fieldset>`
      : `<label class="field"><span class="sr-only">Your answer</span><input type="text" name="answer" autocomplete="off" spellcheck="false" placeholder="${p.kind === 'list' ? 'Numbers separated by commas' : 'A whole number'}"></label>`;
    root.innerHTML = `<header class="page-head"><div><p class="eyebrow">Short and sharp</p><h1>Puzzles</h1><p class="muted">One question each. Most are settled by finding the one quantity that cannot change, or the one count whose parity decides everything. Answers are checked; the reason is shown once you have it.</p></div></header>
      <div class="puzzle-sets" role="tablist">${page.sets.map(s => `<button class="btn ${s.id === page.set ? 'btn-primary' : 'btn-secondary'} btn-sm" type="button" role="tab" aria-selected="${s.id === page.set}" data-set="${e(s.id)}">${e(s.title)} · ${s.done}/${s.total}</button>`).join('')}</div>
      ${set ? `<p class="muted small">${e(set.about)} ${set.done ? `Solved on the first try: ${set.first_try} of ${set.done} finished.` : ''}</p>` : ''}
      <section class="surface reading">${after ? `<div class="step-prompt">${markdown(after.prompt)}</div><div class="grade ${after.correct ? '' : 'grade-fail'}" role="status"><strong>${after.correct ? (after.first_try ? 'Right, first try.' : 'Right.') : 'Shown.'}</strong> ${inline(after.showed)}</div><div class="step-actions"><button class="btn btn-primary" type="button" data-next>Next puzzle</button></div>`
        : p ? `<div class="step-prompt">${markdown(p.prompt)}</div><form data-answer novalidate>${field}${feedback ? `<p class="step-feedback wrong" role="alert">${e(feedback)}</p>` : ''}<div class="step-actions"><button class="btn btn-primary" type="submit">Check</button>${p.wrong ? '<button class="btn btn-ghost" type="button" data-show>Show me the reason</button>' : ''}</div></form>`
        : '<p class="muted">You have finished every puzzle in this set. More are added regularly.</p>'}</section>`;
    root.querySelectorAll('[data-set]').forEach(b => b.addEventListener('click', async () => { after = null; feedback = ''; page = await api('/puzzles?set=' + encodeURIComponent(b.dataset.set)); if (alive()) paint(); }));
    root.querySelector('[data-next]')?.addEventListener('click', async () => { after = null; feedback = ''; page = await api('/puzzles?set=' + encodeURIComponent(page.set)); if (alive()) { paint(); root.querySelector('input')?.focus(); } });
    const form = root.querySelector('[data-answer]');
    if (!form) return;
    const send = async body => {
      try {
        const r = await post('/puzzle/answer', {id: p.id, ...body});
        if (r.correct || r.shown) { after = {...r, prompt: p.prompt}; feedback = ''; }
        else { feedback = r.unreadable ? r.message : 'Not that. ' + (r.message || 'Look for what cannot change.'); p.wrong += r.unreadable ? 0 : 1; }
      } catch (error) { toast(error.message, 'error'); }
      if (alive()) paint();
    };
    form.addEventListener('submit', event => {
      event.preventDefault();
      const value = p.kind === 'choice' ? form.querySelector('input[name=answer]:checked')?.value : form.elements.answer.value;
      if (value == null || !String(value).trim()) { feedback = p.kind === 'choice' ? 'Pick one of the options.' : 'Write an answer first.'; return paint(); }
      send({answer: p.kind === 'choice' ? Number(value) : value});
    });
    root.querySelector('[data-show]')?.addEventListener('click', () => send({show: true}));
  }
  paint();
}
