/* The toolbox: techniques you recognise and then write. Each page says when to reach for the tool,
   the idea, the usual traps, and then has you write it. A reference version appears once yours is accepted. */
import {mountTask} from './tasks.js';
import {marks, legend} from './marks.js';

export async function renderTools(ctx) {
  const {api, escape: e} = ctx;
  const root = ctx.root;
  const page = await api('/tools');
  if (ctx.root !== root) return;
  let only = '';
  try { only = localStorage.getItem('derive-tool-filter') || ''; } catch { /* the filter is a convenience */ }
  const paint = () => {
  const shown = page.tools.filter(t => !only || t.marks.includes(only));
  root.innerHTML = `<header class="page-head"><div><p class="eyebrow">Recognise it, then write it</p><h1>Toolbox</h1><p class="muted">Standard techniques that are not derived so much as known. Each page: when to reach for it, the idea, the traps, and then you write it against the judge. ${page.tools.filter(t => t.written).length} of ${page.tools.length} written.</p></div><div><a class="btn btn-secondary" href="#/notebook">Team notebook</a></div></header>
    <section class="surface">${legend(e)}
      <div class="step-actions" role="group" aria-label="Show">${[['', 'All'], ['standard', '★ Standard only'], ['common', '◆ Common only']].map(([k, label]) => `<button class="btn btn-sm ${only === k ? 'btn-secondary' : 'btn-ghost'}" type="button" data-only="${k}" aria-pressed="${only === k}">${label} (${page.tools.filter(t => !k || t.marks.includes(k)).length})</button>`).join('')}</div>
      <ul class="rows tool-rows">${shown.map(t => `<li class="row"><span class="row-mark${t.written ? ' is-done' : ''}" title="${t.written ? 'Written' : 'Not written yet'}">${t.written ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg><span class="sr-only">Written</span>' : ''}</span><span class="row-main"><a class="row-title" href="#/tool/${e(t.id)}">${e(t.title)}</a> ${marks(t.marks, e)}<span class="row-when">Reach for it when you see: ${e(t.when)}</span></span></li>`).join('')}</ul></section>`;
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
  const state = t => t.state === 'solved' ? '<span class="badge badge-success">accepted</span>' : t.state === 'gave up' ? '<span class="badge">given up</span>' : t.state === 'open' ? '<span class="badge badge-primary">open</span>' : '';
  const practice = () => !(tool.practice || []).length ? '' : `<section class="surface"><h2>Practise it</h2><p class="muted small">Standard tasks on CSES that use this page. They open on CSES; submit there.</p><ul class="plain-list">${tool.practice.map(t => `<li><a href="${e(t.url)}" target="_blank" rel="noopener noreferrer">${e(t.title)}</a> <span class="muted small">· ${e(t.site)}</span></li>`).join('')}</ul></section>`;
  const real = () => !tool.problems_total ? '' : !tool.written ? `<p class="muted small">${tool.problems_total} Codeforces problem${tool.problems_total === 1 ? '' : 's'} that use${tool.problems_total === 1 ? 's' : ''} this will be listed here once your own program is accepted.</p>`
    : `<section class="surface"><h2>Codeforces problems that use it</h2><details class="after-set"><summary>${tool.problems.length} problem${tool.problems.length === 1 ? '' : 's'} in the Solve set (opening this list tells you their topic)</summary>
      <p class="muted small">Solve hands these out without a topic, which is how a solve counts as recognised. One you open from here counts as applied instead. Leave the list closed if you would rather meet them cold.</p>
      <ul class="plain-list">${tool.problems.map(t => `<li>${t.state === 'new' ? `<button class="link-btn" type="button" data-open-problem="${e(t.id)}">${e(t.title)}</button>` : `<a href="#/problem/${e(t.id)}">${e(t.title)}</a>`} <span class="muted small">· ${e(t.site)} · rated ${e(t.rating)}</span> ${state(t)}</li>`).join('')}</ul></details></section>`;
  const after = () => practice() + reference() + real();
  root.addEventListener('click', async event => {
    const b = event.target.closest('[data-open-problem]'); if (!b || !alive()) return;
    try { const opened = await ctx.post('/problem/open', {id: b.dataset.openProblem, tool: tool.id}); ctx.navigate('#/problem/' + opened.id); } catch (error) { ctx.toast(error.message, 'error'); }
  });
  root.innerHTML = `<header class="page-head"><div><p class="eyebrow"><a href="#/tools">Toolbox</a></p><h1>${e(tool.title)} ${ctx.star('tool', tool.id)}</h1><p>${marks(tool.marks, e)}</p></div></header>
    <div data-intro></div><div data-task></div>`;
  // The reading comes first, at full width, above the editor: you read the page, then scroll down to write it.
  const intro = `<section class="surface tool-intro"><h2>Reach for it when you see</h2><ul>${tool.when.map(w => `<li>${inline(w)}</li>`).join('')}</ul>
      <h2>The idea</h2>${markdown(tool.idea)}
      ${tool.example ? `<h2>In code</h2><p class="muted small">The core lines in C++. Reading input and printing the answer are left out.</p><pre class="tool-code">${e(tool.example)}</pre>` : ''}
      <h2>Traps</h2><ul>${tool.traps.map(w => `<li>${inline(w)}</li>`).join('')}</ul></section>
    <h2 class="tool-write">Now write it</h2>`;
  root.querySelector('[data-intro]').innerHTML = intro;
  await mountTask(ctx, root.querySelector('[data-task]'), tool.task, {heading: false, hints: false, after: `<div data-reference>${after()}</div>`, onAccepted: async () => { tool = await api('/tool/' + encodeURIComponent(id)); if (alive()) root.querySelector('[data-reference]').innerHTML = after(); }});
}
