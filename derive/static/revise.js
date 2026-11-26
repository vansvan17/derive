/* Revise: everything you starred, as cards. A card shows its front; the back appears when you ask for it,
   and only exists for things you have finished. No due dates and no scores: you decide what to look at. */

export async function renderRevise(ctx) {
  const {api, escape: e, icon, inline, markdown, star} = ctx;
  const root = ctx.root, alive = () => ctx.root === root;
  let page = await api('/revise');
  if (!alive()) return;
  let filter = '', one = false, order = [], at = 0;
  const open = new Set();
  const key = c => c.kind + ':' + c.ref;
  const shown = () => page.cards.filter(c => !filter || c.kind === filter);
  const shuffle = list => { const a = list.map(key); for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; } return a; };

  const part = b => `<div class="card-part"><h4>${e(b.label)}</h4>${b.list ? `<ol>${b.list.map(x => `<li>${inline(x)}</li>`).join('')}</ol>` : b.code != null ? `<pre class="card-code">${e(b.code)}</pre>` : b.plain != null ? `<p>${e(b.plain)}</p>` : `<div>${markdown(b.text || '')}</div>`}</div>`;
  const card = (c, big) => { const k = key(c), flipped = open.has(k);
    return `<article class="surface revise-card ${big ? 'is-big' : ''}" data-card="${e(k)}">
      <div class="revise-head"><p class="eyebrow">${e(c.label)} · ${e(c.title)}</p>${star(c.kind, c.ref)}</div>
      ${c.note != null ? (c.note.trim() ? `<pre class="card-note">${e(c.note)}</pre>` : '<p class="muted">These notes are empty.</p>') : `<div class="step-prompt">${markdown(c.front)}</div>`}
      ${c.options ? `<ol class="card-options" type="A">${c.options.map(o => `<li>${inline(o)}</li>`).join('')}</ol>` : ''}
      ${c.url ? `<p><a class="btn btn-secondary btn-sm" href="${e(c.url)}" target="_blank" rel="noopener noreferrer">${icon('external')}Read it on ${e(c.site)}</a></p>` : ''}
      ${c.back && flipped ? `<div class="card-back">${c.back.map(part).join('')}</div>` : ''}
      <div class="step-actions">${c.back ? `<button class="btn ${flipped ? 'btn-ghost' : 'btn-primary'} btn-sm" type="button" data-flip="${e(k)}">${flipped ? 'Hide the back' : 'Show the back'}</button>` : ''}
        <a class="btn btn-ghost btn-sm" href="${e(c.link)}">Open it</a>${c.back || c.note != null ? '' : `<span class="muted small">${page.locked ? 'The back is hidden while a contest runs.' : c.finished ? '' : 'Not finished yet, so there is no back.'}</span>`}</div></article>`; };

  function paint() {
    const list = shown();
    const head = `<header class="page-head"><div><p class="eyebrow">What you starred</p><h1>Revise</h1><p class="muted">Star a question, a problem, a task, a Toolbox page or your own notes with the <span class="inline-icon">${icon('star')}</span> button on its page, and it is kept here as a card. The back of a card is only there for things you have finished.</p></div></header>`;
    if (!page.cards.length) { root.innerHTML = head + `<section class="surface empty-state"><h2>Nothing starred yet</h2><p>Look for the star next to a chain question, a puzzle, a problem title, a task title, or your notes.</p><a class="btn btn-primary" href="#/derive">Go to a chain</a></section>`; return; }
    const chips = `<div class="puzzle-sets" role="tablist"><button class="btn ${filter ? 'btn-secondary' : 'btn-primary'} btn-sm" type="button" data-filter="">All · ${page.cards.length}</button>${page.kinds.filter(k => k.count).map(k => `<button class="btn ${filter === k.id ? 'btn-primary' : 'btn-secondary'} btn-sm" type="button" data-filter="${e(k.id)}">${e(k.label)} · ${k.count}</button>`).join('')}
      <span class="spacer"></span><button class="btn btn-secondary btn-sm" type="button" data-one>${one ? 'Show them all' : 'One at a time, shuffled'}</button></div>`;
    let body;
    if (one) {
      order = order.filter(k => list.some(c => key(c) === k)); if (!order.length) { order = shuffle(list); at = 0; }
      at = Math.min(at, order.length - 1);
      const current = list.find(c => key(c) === order[at]);
      body = `${card(current, true)}<div class="puzzle-nav"><button class="btn btn-ghost btn-sm" type="button" data-step="-1" ${at ? '' : 'disabled'}>← Previous</button><span class="muted small">${at + 1} of ${order.length}</span><button class="btn btn-ghost btn-sm" type="button" data-step="1" ${at < order.length - 1 ? '' : 'disabled'}>Next →</button></div>`;
    } else body = list.length ? `<div class="revise-grid">${list.map(c => card(c, false)).join('')}</div>` : '<p class="muted">Nothing of this kind is starred.</p>';
    root.innerHTML = head + (page.locked ? '<p class="muted small">A contest is running, so the backs of the cards are hidden until it ends.</p>' : '') + chips + body;
    root.querySelectorAll('[data-filter]').forEach(b => b.addEventListener('click', () => { filter = b.dataset.filter; order = []; paint(); }));
    root.querySelector('[data-one]').addEventListener('click', () => { one = !one; order = []; open.clear(); paint(); });
    root.querySelectorAll('[data-flip]').forEach(b => b.addEventListener('click', () => { open.has(b.dataset.flip) ? open.delete(b.dataset.flip) : open.add(b.dataset.flip); paint(); }));
    root.querySelectorAll('[data-step]').forEach(b => b.addEventListener('click', () => { at += Number(b.dataset.step); paint(); window.scrollTo(0, 0); }));
  }
  // A card that is unstarred here goes away once the server has dropped it.
  const onStar = async () => { page = await api('/revise'); if (alive()) paint(); };
  document.addEventListener('derive-star', onStar);
  ctx.onCleanup(() => document.removeEventListener('derive-star', onStar));
  paint();
}
