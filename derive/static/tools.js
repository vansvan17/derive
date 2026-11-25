/* The toolbox: techniques you recognise and then write. Each page says when to reach for the tool,
   the idea, the usual traps, and then has you write it. A reference version appears once yours is accepted. */
import {mountTask} from './tasks.js';

/* Two marks. Standard: a named technique everyone at a regional is assumed to know, so not knowing it costs a problem.
   Common: it turns up often in recent rounds. A page can carry both. */
const MARKS = {
  standard: {symbol: '★', label: 'Standard', cls: 'mark-standard', meaning: 'a textbook technique everyone at a regional is assumed to know'},
  common: {symbol: '◆', label: 'Common', cls: 'mark-common', meaning: 'turns up often in recent rounds'},
};
const marks = (list, e) => (list || []).filter(m => MARKS[m]).map(m => `<span class="mark ${MARKS[m].cls}" title="${e(MARKS[m].label + ': ' + MARKS[m].meaning)}"><span aria-hidden="true">${MARKS[m].symbol}</span> ${MARKS[m].label}</span>`).join(' ');

export async function renderTools(ctx) {
  const {api, escape: e} = ctx;
  const root = ctx.root;
  const page = await api('/tools');
  if (ctx.root !== root) return;
  let only = '';
  try { only = localStorage.getItem('derive-tool-filter') || ''; } catch { /* the filter is a convenience */ }
  const paint = () => {
  const shown = page.tools.filter(t => !only || t.marks.includes(only));
  root.innerHTML = `<header class="page-head"><div><p class="eyebrow">Recognise it, then write it</p><h1>Toolbox</h1><p class="muted">Standard techniques that are not derived so much as known. Each page: when to reach for it, the idea, the traps, and then you write it against the judge. ${page.tools.filter(t => t.written).length} of ${page.tools.length} written.</p></div></header>
    <section class="surface"><p class="mark-legend">${Object.entries(MARKS).map(([k, m]) => `<span>${marks([k], e)} <span class="muted small">${e(m.meaning)}</span></span>`).join('')}</p>
      <div class="step-actions" role="group" aria-label="Show">${[['', 'All'], ['standard', '★ Standard only'], ['common', '◆ Common only']].map(([k, label]) => `<button class="btn btn-sm ${only === k ? 'btn-secondary' : 'btn-ghost'}" type="button" data-only="${k}" aria-pressed="${only === k}">${label} (${page.tools.filter(t => !k || t.marks.includes(k)).length})</button>`).join('')}</div>
      <ul class="tool-list">${shown.map(t => `<li><a href="#/tool/${e(t.id)}"><strong>${e(t.title)}</strong></a> ${marks(t.marks, e)} ${t.written ? '<span class="badge badge-success">written</span>' : ''}<br><span class="muted small">Reach for it when you see: ${e(t.when)}</span></li>`).join('')}</ul></section>`;
  root.querySelectorAll('[data-only]').forEach(b => b.addEventListener('click', () => { only = b.dataset.only; try { localStorage.setItem('derive-tool-filter', only); } catch { /* fine */ } paint(); }));
  };
  paint();
}

export async function renderTool(ctx, id) {
  const {api, escape: e, inline, markdown} = ctx;
  const root = ctx.root, alive = () => ctx.root === root;
  let tool = await api('/tool/' + encodeURIComponent(id));
  if (!alive()) return;
  const reference = () => tool.reference ? `<section class="surface"><h2>A reference version</h2><p class="muted small">Yours is accepted, so here is one clean way to write it. Compare the loop structure and the edge cases with your own.</p><pre class="tool-code">${e(tool.reference)}</pre></section>` : '<p class="muted small">A reference version appears here once your own program is accepted.</p>';
  root.innerHTML = `<header class="page-head"><div><p class="eyebrow"><a href="#/tools">Toolbox</a></p><h1>${e(tool.title)}</h1><p>${marks(tool.marks, e)}</p></div></header>
    <section class="surface reading"><h2>Reach for it when you see</h2><ul>${tool.when.map(w => `<li>${inline(w)}</li>`).join('')}</ul>
      <h2>The idea</h2>${markdown(tool.idea)}
      <h2>Traps</h2><ul>${tool.traps.map(w => `<li>${inline(w)}</li>`).join('')}</ul></section>
    <h2 class="tool-write">Now write it</h2><div data-task></div><div data-reference>${reference()}</div>`;
  await mountTask(ctx, root.querySelector('[data-task]'), tool.task, {heading: false, onAccepted: async () => { tool = await api('/tool/' + encodeURIComponent(id)); if (alive()) root.querySelector('[data-reference]').innerHTML = reference(); }});
}
