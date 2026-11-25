/* Recognise: read a real statement, say in a sentence what cracks it, then compare with what does.
   No code. The clock is only a guide: about three minutes a problem. */

const clock = s => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;

export async function renderRecognise(ctx) {
  const {api, post, escape: e, icon, inline, toast} = ctx;
  const root = ctx.root, alive = () => ctx.root === root;
  let page = await api('/recognise');
  if (!alive()) return;
  let started = null, tick = null, draft = '';
  ctx.onCleanup(() => clearInterval(tick));
  const elapsed = () => started ? Math.round((Date.now() - started) / 1000) : 0;

  function paint() {
    clearInterval(tick);
    const c = page.card, done = page.counts.reduce((a, x) => a + x.count, 0);
    const head = `<header class="page-head"><div><p class="eyebrow">See it before you code it</p><h1>Recognise</h1>
      <p class="muted">Read a real statement and say, in a sentence or two, what cracks it and which technique that leads to. Then compare with what does. No code; aim for about ${Math.round(page.target / 60)} minutes each. You rate yourself, so this never counts on the record page.</p></div></header>
      <section class="surface recog-counts"><dl class="evidence">${page.counts.map(x => `<div><dt>${e(x.label)}</dt><dd>${x.count}</dd></div>`).join('')}<div><dt>Not tried yet</dt><dd>${page.pool - page.drilled}</dd></div></dl>
      <p class="muted small">${page.pool} problems can come up: ${page.parked} below your working level, which Solve never hands out, and ${page.pool - page.parked} you have already finished under Solve. A problem still waiting for you under Solve is never shown here, because seeing what cracks it would spoil it.</p></section>`;
    if (!c) {
      root.innerHTML = head + `<section class="surface empty-state"><h2>${done ? 'Nothing left for now' : 'No problems yet'}</h2><p>${done ? 'You saw the idea in every problem that can be shown here. Each problem you finish under Solve comes back here later.' : 'Problems appear here as you finish them under Solve.'}</p><a class="btn btn-primary" href="#/solve">Solve one</a></section>`;
      return;
    }
    const about = `${e(c.site)} · rated ${e(c.rating)} · ${c.source === 'parked' ? 'below your working level' : 'one you finished earlier'}${c.times_before ? ` · tried here ${c.times_before} time${c.times_before === 1 ? '' : 's'} before` : ''}`;
    if (!c.revealed) {
      root.innerHTML = head + `<section class="surface recog-card"><p class="eyebrow">${about}</p><h2>${e(c.title)}</h2>
        <div class="recog-row"><a class="btn btn-secondary" href="${e(c.url)}" target="_blank" rel="noopener noreferrer" data-open>${icon('external')}Read it on ${e(c.site)}</a>
          <span class="recog-clock" data-clock aria-live="off">${started ? clock(elapsed()) : 'The clock starts when you open the statement'}</span></div>
        <label class="field">What cracks it? The observation, and the technique it leads to.<textarea data-guess rows="5" placeholder="e.g. Only the parity of each prefix matters, so count prefixes by parity with a map.">${e(draft)}</textarea></label>
        <div class="step-actions"><button class="btn btn-primary" type="button" data-reveal>Show what cracks it</button><span class="muted small">Commit to an answer first, even a wrong one. Being unsure is the point of the exercise.</span></div></section>`;
      const node = root.querySelector('[data-clock]');
      const show = () => { const s = elapsed(); node.textContent = `${clock(s)} of ${clock(page.target)}`; node.classList.toggle('is-over', s > page.target); };
      if (started) { show(); tick = setInterval(show, 1000); }
      root.querySelector('[data-open]').addEventListener('click', () => { if (!started) { started = Date.now(); show(); tick = setInterval(show, 1000); } });
      root.querySelector('[data-guess]').addEventListener('input', event => { draft = event.target.value; if (!started) { started = Date.now(); show(); tick = setInterval(show, 1000); } });
      root.querySelector('[data-reveal]').addEventListener('click', async () => {
        try { page = await post('/recognise/reveal', {id: c.id, guess: draft, seconds: elapsed()}); if (alive()) paint(); } catch (error) { toast(error.message, 'error'); }
      });
      return;
    }
    root.innerHTML = head + `<section class="surface recog-card"><p class="eyebrow">${about}</p><h2>${e(c.title)}</h2>
      <p><a href="${e(c.url)}" target="_blank" rel="noopener noreferrer">The statement on ${e(c.site)}</a>${c.editorial ? ` · <a href="${e(c.editorial)}" target="_blank" rel="noopener noreferrer">the editorial</a>` : ''}</p>
      <div class="recog-compare"><div><h3>You said${c.seconds ? ` <span class="muted small">after ${clock(c.seconds)}</span>` : ''}</h3><p class="recog-guess">${e(c.guess)}</p></div>
        <div><h3>What cracks it</h3><ol>${c.observations.map(o => `<li>${inline(o)}</li>`).join('')}</ol>
          <p class="muted small">It rests on: ${c.ideas.map(i => i.derived ? `<a href="#/chain/${e(i.id)}">${e(i.name)}</a>` : i.has_chain ? `<a href="#/chain/${e(i.id)}">an idea you have not derived yet</a>` : 'an idea whose chain is not written').join(', ')}.</p></div></div>
      <h3>Compared with that, you…</h3>
      <div class="step-actions">${[['saw', 'Saw it', 'btn-primary'], ['part', 'Had part of it', 'btn-secondary'], ['missed', 'Missed it', 'btn-secondary']].map(([k, label, cls]) => `<button class="btn ${cls}" type="button" data-rate="${k}">${label}</button>`).join('')}</div>
      <p class="muted small">"Saw it" means you named the observation the solution turns on, not just the topic. Anything else comes back later.</p></section>`;
    root.querySelectorAll('[data-rate]').forEach(b => b.addEventListener('click', async () => {
      try { page = await post('/recognise/rate', {id: c.id, rating: b.dataset.rate}); started = null; draft = ''; if (alive()) { paint(); window.scrollTo(0, 0); } } catch (error) { toast(error.message, 'error'); }
    }));
  }
  paint();
}
