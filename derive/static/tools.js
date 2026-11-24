/* The toolbox: techniques you recognise and then write. Each page says when to reach for the tool,
   the idea, the usual traps, and then has you write it. A reference version appears once yours is accepted. */
import {mountTask} from './tasks.js';

export async function renderTools(ctx) {
  const {api, escape: e} = ctx;
  const root = ctx.root;
  const page = await api('/tools');
  if (ctx.root !== root) return;
  root.innerHTML = `<header class="page-head"><div><p class="eyebrow">Recognise it, then write it</p><h1>Toolbox</h1><p class="muted">Standard techniques that are not derived so much as known. Each page: when to reach for it, the idea, the traps, and then you write it against the judge. ${page.tools.filter(t => t.written).length} of ${page.tools.length} written.</p></div></header>
    <section class="surface"><ul class="tool-list">${page.tools.map(t => `<li><a href="#/tool/${e(t.id)}"><strong>${e(t.title)}</strong></a> ${t.written ? '<span class="badge badge-success">written</span>' : ''}<br><span class="muted small">Reach for it when you see: ${e(t.when)}</span></li>`).join('')}</ul></section>`;
}

export async function renderTool(ctx, id) {
  const {api, escape: e, inline, markdown} = ctx;
  const root = ctx.root, alive = () => ctx.root === root;
  let tool = await api('/tool/' + encodeURIComponent(id));
  if (!alive()) return;
  const reference = () => tool.reference ? `<section class="surface"><h2>A reference version</h2><p class="muted small">Yours is accepted, so here is one clean way to write it. Compare the loop structure and the edge cases with your own.</p><pre class="tool-code">${e(tool.reference)}</pre></section>` : '<p class="muted small">A reference version appears here once your own program is accepted.</p>';
  root.innerHTML = `<header class="page-head"><div><p class="eyebrow"><a href="#/tools">Toolbox</a></p><h1>${e(tool.title)}</h1></div></header>
    <section class="surface reading"><h2>Reach for it when you see</h2><ul>${tool.when.map(w => `<li>${inline(w)}</li>`).join('')}</ul>
      <h2>The idea</h2>${markdown(tool.idea)}
      <h2>Traps</h2><ul>${tool.traps.map(w => `<li>${inline(w)}</li>`).join('')}</ul></section>
    <h2 class="tool-write">Now write it</h2><div data-task></div><div data-reference>${reference()}</div>`;
  await mountTask(ctx, root.querySelector('[data-task]'), tool.task, {heading: false, onAccepted: async () => { tool = await api('/tool/' + encodeURIComponent(id)); if (alive()) root.querySelector('[data-reference]').innerHTML = reference(); }});
}
