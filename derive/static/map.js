/* The map: every idea as a dot, grouped by area. An idea has no name until it is derived. */

const STATE_TEXT = {derived: 'Derived', open: 'Ready to derive', started: 'In progress', locked: 'Builds on something not yet derived', unwritten: 'Chain not written yet'};
const nodeState = i => i.derived ? 'derived' : !i.has_chain ? 'unwritten' : !i.open ? 'locked' : i.steps_done ? 'started' : 'open';

export async function renderMap(ctx, {notice = ''} = {}) {
  const {api, escape: e, icon, inline, navigate} = ctx;
  const root = ctx.root, alive = () => ctx.root === root;
  const data = await api('/map');
  if (!alive()) return;
  const boot = ctx.boot, c = boot.counts, band = boot.band;
  const byId = Object.fromEntries(data.ideas.map(i => [i.id, i]));
  const label = i => i.derived ? i.name : 'not yet derived';
  let selected = null;

  root.classList.add('wide');
  root.innerHTML = `<header class="page-head"><div><p class="eyebrow">derive</p><h1>The map</h1><p class="muted">${data.ideas.length} ideas. Each one stays nameless until you have derived it yourself.</p></div></header>
    ${notice ? `<p class="surface notice">${e(notice)}</p>` : ''}
    <div class="start-grid">
      <section class="surface start-card"><p class="eyebrow">Derive</p><h2>${boot.next_chain ? (byId[boot.next_chain].steps_done ? 'Carry on with your chain' : 'Start the next chain') : 'All written chains derived'}</h2><p class="muted">A chain of small questions. You are not told where it leads. ${c.derived} of ${c.chains} derived so far.</p>${boot.next_chain ? `<a class="btn btn-primary" href="#/chain/${e(boot.next_chain)}">${icon('chain')}${byId[boot.next_chain].steps_done ? `Continue · step ${byId[boot.next_chain].steps_done + 1} of ${byId[boot.next_chain].steps_total}` : 'Begin'}</a>` : ''}</section>
      <section class="surface start-card"><p class="eyebrow">Solve</p><h2>${boot.open_problem ? 'Back to your problem' : 'A real problem, no topic given'}</h2><p class="muted">${c.problems ? `From Codeforces, AtCoder and CSES. Working at ${band.band}; ${band.cold} of your last ${band.recent} at this level were cold solves (7 of 10 moves you up).` : 'The problem set is still being curated.'}</p>${c.problems ? `<a class="btn ${boot.next_chain ? 'btn-secondary' : 'btn-primary'}" href="#/solve">${icon('target')}${boot.open_problem ? 'Continue' : 'Give me a problem'}</a>` : ''}</section>
    </div>
    <div class="map-layout">
      <section class="surface map-card" aria-label="Map of ideas"><div class="map-stage" data-stage><svg class="map-lines" data-lines aria-hidden="true"></svg>
        ${data.areas.map(area => `<div class="map-band"><h3>${e(area.title)}</h3><div class="map-row">${data.ideas.filter(i => i.area === area.id).sort((a, b) => a.level - b.level).map(i => {
          const s = nodeState(i);
          return `<button class="node node-${s}" type="button" data-node="${e(i.id)}" aria-label="${e(label(i))}: ${STATE_TEXT[s]}" aria-pressed="false">${i.derived ? `<span class="node-name">${e(i.name)}</span>` : `<span class="node-mark">${s === 'locked' ? icon('lock') : s === 'unwritten' ? '·' : '?'}</span>`}${s === 'started' ? `<span class="node-progress">${i.steps_done}/${i.steps_total}</span>` : ''}</button>`;
        }).join('')}</div></div>`).join('')}
      </div><p class="map-legend"><span class="key key-open">?</span> ready to derive <span class="key key-locked">${icon('lock')}</span> builds on another <span class="key key-unwritten">·</span> chain not written yet <span class="key key-derived">name</span> derived</p></section>
      <aside class="surface map-side" data-side aria-live="polite"><h2>Pick a dot</h2><p class="muted">Select an idea to see what it rests on and what it is connected to. Lines show connections for the selected idea.</p></aside>
    </div>`;

  const stage = root.querySelector('[data-stage]'), lines = root.querySelector('[data-lines]'), side = root.querySelector('[data-side]');
  const centre = id => { const n = stage.querySelector(`[data-node="${CSS.escape(id)}"]`), a = n.getBoundingClientRect(), b = stage.getBoundingClientRect(); return [a.left - b.left + a.width / 2, a.top - b.top + a.height / 2]; };
  function drawLines() {
    const box = stage.getBoundingClientRect();
    lines.setAttribute('viewBox', `0 0 ${box.width} ${box.height}`);
    lines.setAttribute('width', box.width); lines.setAttribute('height', box.height);
    if (!selected) { lines.innerHTML = ''; return; }
    const related = data.links.filter(l => l.from === selected || l.to === selected);
    const needs = byId[selected].needs.map(n => ({from: n, to: selected, need: true}));
    lines.innerHTML = [...needs, ...related].map(l => { const [x1, y1] = centre(l.from), [x2, y2] = centre(l.to), bend = Math.min(60, Math.abs(x2 - x1) / 2 + 20); return `<path class="${l.need ? 'line-need' : 'line-link'}" d="M${x1},${y1} C${x1},${y1 + bend} ${x2},${y2 - bend} ${x2},${y2}"/>`; }).join('');
  }
  function select(id) {
    selected = id;
    const i = byId[id], s = nodeState(i), ev = i.evidence;
    stage.querySelectorAll('[data-node]').forEach(n => { const on = n.dataset.node === id, near = i.needs.includes(n.dataset.node) || data.links.some(l => (l.from === id && l.to === n.dataset.node) || (l.to === id && l.from === n.dataset.node)); n.setAttribute('aria-pressed', String(on)); n.classList.toggle('is-near', near && !on); });
    const others = data.links.filter(l => l.from === id || l.to === id).map(l => ({other: byId[l.from === id ? l.to : l.from], out: l.from === id, kind: l.kind, note: l.note}));
    const action = s === 'derived' ? `<a class="btn btn-secondary btn-sm" href="#/chain/${e(id)}">Reread the chain</a>`
      : s === 'open' || s === 'started' ? `<a class="btn btn-primary btn-sm" href="#/chain/${e(id)}">${s === 'started' ? `Continue · step ${i.steps_done + 1} of ${i.steps_total}` : 'Begin deriving'}</a>` : '';
    side.innerHTML = `<p class="eyebrow">${e(data.areas.find(a => a.id === i.area).title)}</p><h2>${i.derived ? e(i.name) : 'An idea you have not derived yet'}</h2>
      ${i.derived ? `<p class="map-statement">${inline(i.statement)}</p>` : `<p class="muted">${STATE_TEXT[s]}.${s === 'unwritten' ? ' Its problems can still come up when you solve.' : ''}</p>`}
      ${action ? `<p>${action}</p>` : ''}
      ${i.needs.length ? `<h3>Rests on</h3><ul class="plain-list">${i.needs.map(n => `<li><button class="link-btn" type="button" data-jump="${e(n)}">${e(label(byId[n]))}</button></li>`).join('')}</ul>` : ''}
      ${others.length ? `<h3>Connections</h3><ul class="plain-list">${others.map(o => `<li><button class="link-btn" type="button" data-jump="${e(o.other.id)}">${e(label(o.other))}</button> <span class="muted">· ${e(o.kind)}</span>${o.note ? `<br><span class="link-note">${inline(o.note)}</span>` : '<br><span class="link-note muted">Derive both ends to see why they are connected.</span>'}</li>`).join('')}</ul>` : ''}
      <h3>Evidence</h3><dl class="evidence"><div><dt>Derived</dt><dd>${ev.derived ? 'yes' : 'no'}</dd></div><div><dt>Applied</dt><dd>${ev.applied}</dd></div><div><dt>Recognised cold</dt><dd>${ev.recognised}</dd></div><div><dt>Combined cold</dt><dd>${ev.combined}</dd></div></dl>
      <p class="muted" style="font-size:.875rem">${ev.problems} real problem${ev.problems === 1 ? '' : 's'} in the set rest${ev.problems === 1 ? 's' : ''} on this.</p>`;
    side.querySelectorAll('[data-jump]').forEach(b => b.addEventListener('click', () => select(b.dataset.jump)));
    drawLines();
  }
  stage.querySelectorAll('[data-node]').forEach(n => n.addEventListener('click', () => select(n.dataset.node)));
  const onResize = () => drawLines();
  window.addEventListener('resize', onResize);
  ctx.onCleanup(() => window.removeEventListener('resize', onResize));
  if (boot.next_chain) select(boot.next_chain);
}
