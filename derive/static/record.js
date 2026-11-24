/* What the record shows (never one blended percentage), and the settings. */
import {applyTheme} from './app.js';

export async function renderMastery(ctx) {
  const {api, escape: e} = ctx;
  const root = ctx.root;
  const m = await api('/mastery');
  if (ctx.root !== root) return;
  const name = (n, id) => n ? e(n) : '<span class="muted">not yet derived</span>';
  const tick = on => on ? '<span class="badge badge-success">yes</span>' : '<span class="muted">no</span>';
  const when = iso => new Date(iso).toLocaleDateString([], {day: 'numeric', month: 'short'});
  const total = m.causes.reduce((a, c) => a + c.count, 0);
  root.innerHTML = `<header class="page-head"><div><p class="eyebrow">The record</p><h1>What you can do</h1><p class="muted">Four different kinds of evidence, kept apart. Reading or being shown something is not on this page at all.</p></div></header>
    <div class="start-grid">
      <section class="surface"><p class="eyebrow">Working level</p><h2>${m.band.band}</h2><p class="muted">${m.band.cold} of your last ${m.band.recent} problems at this level were solved cold. Seven of ten moves you up by 100.</p><div class="meter" role="img" aria-label="${m.band.cold} of 7 cold solves"><span style="width:${Math.min(100, Math.round(100 * m.band.cold / 7))}%"></span></div></section>
      <section class="surface"><dl class="evidence big"><div><dt>Chains derived</dt><dd>${m.counts.derived}<small> of ${m.counts.chains}</small></dd></div><div><dt>Problems accepted</dt><dd>${m.counts.solved}<small> of ${m.counts.problems}</small></dd></div><div><dt>Of those, cold</dt><dd>${m.counts.cold}</dd></div><div><dt>Ideas owed a return</dt><dd>${new Set(m.returns.map(r => r.idea)).size}</dd></div></dl></section>
    </div>
    <section class="surface"><h2>By idea</h2><p class="muted small"><strong>Derived</strong>: finished its chain. <strong>Applied</strong>: a real judge accepted a problem that needs it. <strong>Recognised</strong>: accepted with no help and no topic given. <strong>Combined</strong>: recognised in a problem needing two or more ideas.</p>
      <div class="table-scroll"><table class="table"><thead><tr><th>Idea</th><th>Derived</th><th>Applied</th><th>Recognised</th><th>Combined</th><th>Problems in set</th></tr></thead><tbody>
      ${m.areas.map(area => `<tr class="table-group"><th colspan="6">${e(area.title)}</th></tr>` + m.ideas.filter(i => i.area === area.id).map(i => `<tr><td>${name(i.name)}${i.has_chain ? '' : ' <span class="muted small">· chain not written</span>'}</td><td>${tick(i.derived)}</td><td>${i.applied}</td><td>${i.recognised}</td><td>${i.combined}</td><td>${i.problems}</td></tr>`).join('')).join('')}
      </tbody></table></div></section>
    <section class="surface"><h2>Connections</h2><p class="muted small">Knowing two ideas separately is not the same as seeing them together. Only pairs you have derived both ends of are listed.</p>
      ${m.pairs.length ? `<div class="table-scroll"><table class="table"><thead><tr><th>Pair</th><th>Applied together</th><th>Recognised together</th><th>Problems in set</th></tr></thead><tbody>${m.pairs.map(p => `<tr><td>${e(p.a_name)} + ${e(p.b_name)}</td><td>${p.applied}</td><td>${p.recognised}</td><td>${p.problems}</td></tr>`).join('')}</tbody></table></div>` : '<p class="muted">Nothing yet: no problem in the set joins two ideas you have derived.</p>'}</section>
    <div class="start-grid">
      <section class="surface"><h2>What got in the way</h2>${total ? `<ul class="bars">${m.causes.map(c => `<li><span>${e(c.label)}</span><span class="bar"><span style="width:${Math.round(100 * c.count / total)}%"></span></span><strong>${c.count}</strong></li>`).join('')}</ul>` : '<p class="muted">Recorded after each problem. Different causes need different practice, so they are counted separately.</p>'}</section>
      <section class="surface"><h2>Owed a return</h2>${m.returns.length ? `<ul class="plain-list">${m.returns.map(r => `<li>${name(r.name)} <span class="muted small">· ${e(r.reason)} · due ${when(r.due)}</span></li>`).join('')}</ul>` : '<p class="muted">Nothing. An idea lands here when you needed help with it, and leaves when you solve a different problem on it cold.</p>'}</section>
    </div>`;
}

export async function renderSettings(ctx) {
  const {post, escape: e, toast} = ctx;
  const root = ctx.root, s = ctx.boot.settings;
  root.innerHTML = `<div class="reading"><header class="page-head"><div><p class="eyebrow">This computer only</p><h1>Settings</h1></div></header>
    <form data-settings novalidate>
    <section class="surface"><h2>Your handles</h2><p class="muted small">Used only to read your public submission lists, so that a solve is the judge's word. No password is involved; nothing else is sent anywhere.</p>
      <div class="form-grid"><label class="field">Codeforces handle<input type="text" name="cf_handle" maxlength="40" autocomplete="off" spellcheck="false" value="${e(s.cf_handle)}"></label>
      <label class="field">AtCoder handle<input type="text" name="atcoder_handle" maxlength="40" autocomplete="off" spellcheck="false" value="${e(s.atcoder_handle)}"></label></div></section>
    <section class="surface"><h2>Proof grading</h2><p class="muted small">Written proofs cannot be checked by this app. When this is on, the app runs the Claude Code command installed on this Mac, once per proof, with all tools off, and asks only for pass or fail and one question back. It uses whichever Claude account Claude Code is signed into here.</p>
      <label class="choice"><input type="radio" name="grader" value="off" ${s.grader === 'off' ? 'checked' : ''}><span><strong>Off.</strong> Proofs are saved as "waiting for a grade"; you can grade each by hand by pasting a prompt into Claude.</span></label>
      <label class="choice"><input type="radio" name="grader" value="claude" ${s.grader === 'claude' ? 'checked' : ''} ${ctx.boot.grader_available ? '' : 'disabled'}><span><strong>On.</strong> Graded in about 10 to 30 seconds; the next step opens only on a pass.${ctx.boot.grader_available ? '' : ' (The claude command was not found on this computer.)'}</span></label></section>
    <section class="surface"><h2>Editor</h2><div class="form-grid"><label class="field">Language<select name="language"><option value="cpp" ${s.language === 'cpp' ? 'selected' : ''}>C++20</option><option value="python" ${s.language === 'python' ? 'selected' : ''}>Python</option></select></label>
      <label class="field">Font size<select name="font_size">${[12, 13, 14, 15, 16, 18, 20].map(n => `<option ${s.font_size === n ? 'selected' : ''}>${n}</option>`).join('')}</select></label>
      <label class="field">Theme<select name="theme">${['light', 'dark', 'system'].map(t => `<option value="${t}" ${s.theme === t ? 'selected' : ''}>${t[0].toUpperCase() + t.slice(1)}</option>`).join('')}</select></label></div></section>
    <div class="step-actions"><button class="btn btn-primary" type="submit">Save</button></div></form></div>`;
  root.querySelector('[data-settings]').addEventListener('submit', async event => {
    event.preventDefault();
    const f = new FormData(event.target);
    try {
      const saved = await post('/settings', {cf_handle: f.get('cf_handle').trim(), atcoder_handle: f.get('atcoder_handle').trim(), grader: f.get('grader') || 'off', language: f.get('language'), font_size: Number(f.get('font_size')), theme: f.get('theme')});
      applyTheme(saved.settings.theme);
      await ctx.sync();
      toast('Saved.', 'success');
    } catch (error) { toast(error.message, 'error'); }
  });
}
