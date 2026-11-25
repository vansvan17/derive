/* The CSES dynamic programming section. Every task of the CSES DP list has its own chain of questions
   that leads to its solution; the tasks are grouped by what they teach. The statement stays on CSES. */

export async function renderCses(ctx) {
  const {api, post, escape: e, icon, toast} = ctx;
  const root = ctx.root;
  const page = await api('/cses');
  if (ctx.root !== root) return;
  const derived = page.problems.filter(p => p.derived).length, accepted = page.problems.filter(p => p.accepted).length;
  const row = p => {
    const state = p.derived ? '<span class="badge badge-success">derived</span>' : p.steps_done ? `<span class="badge badge-primary">step ${p.steps_done + 1} of ${p.steps_total}</span>` : '';
    return `<li><a href="#/chain/${e(p.id)}"><strong>${e(p.title)}</strong></a> ${state}
      <a class="muted small" href="${e(p.url)}" target="_blank" rel="noopener noreferrer">statement on CSES</a>
      <label class="muted small cses-tick"><input type="checkbox" data-accepted="${e(p.url)}" ${p.accepted ? 'checked' : ''}> accepted on CSES</label>
      ${p.lesson ? `<br><span class="muted small">What it taught: ${e(p.lesson)}</span>` : ''}</li>`;
  };
  root.innerHTML = `<header class="page-head"><div><p class="eyebrow">Every task teaches one thing</p><h1>CSES: dynamic programming</h1>
    <p class="muted">The ${page.problems.length} tasks of the CSES dynamic programming list, grouped by topic. For each one: read the statement on CSES, work through the chain of questions here until the solution is yours, then code it and submit there. ${derived} of ${page.problems.length} derived, ${accepted} accepted.</p></div></header>
    ${page.topics.map(t => `<section class="surface"><h2>${e(t.title)}</h2><p class="muted small">${e(t.about)}</p><ul class="tool-list">${page.problems.filter(p => p.topic === t.id).map(row).join('')}</ul></section>`).join('')}`;
  root.querySelectorAll('[data-accepted]').forEach(box => box.addEventListener('change', async () => {
    try { await post('/practice', {url: box.dataset.accepted, done: box.checked}); } catch (error) { box.checked = !box.checked; toast(error.message, 'error'); }
  }));
}
