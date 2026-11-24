/* Contest mode: a real Codeforces round against the clock, scored the ICPC way.
   While the clock runs there is no help anywhere in the app. Afterwards: label every
   wrong submission, and upsolve what was left. */

const clock = seconds => `${Math.floor(seconds / 3600)}:${String(Math.floor(seconds % 3600 / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;

export async function renderContest(ctx) {
  const {api, post, escape: e, toast, dialog} = ctx;
  const root = ctx.root, alive = () => ctx.root === root;
  let page = await api('/contests');
  if (!alive()) return;
  let tick = null, poll = null, left = 0;
  ctx.onCleanup(() => { clearInterval(tick); clearInterval(poll); });

  const board = (run, labelling) => `<div class="table-scroll"><table class="table"><thead><tr><th>#</th><th>Problem</th><th>Result</th><th>Minute</th><th>Wrong tries</th></tr></thead><tbody>
    ${run.rows.map(r => `<tr><td>${e(r.index)}</td><td><a href="${e(run.url)}/problem/${e(r.index)}" target="_blank" rel="noopener noreferrer">${e(r.name)}</a>${run.ended && r.rating ? ` <span class="muted small">· ${r.rating}</span>` : ''}</td>
      <td>${r.solved ? '<span class="badge badge-success">Accepted</span>' : r.upsolved ? '<span class="badge badge-primary">Upsolved</span>' : r.wrong.length ? '<span class="badge">Tried</span>' : '<span class="muted">·</span>'}</td>
      <td>${r.minute ?? ''}</td>
      <td>${r.wrong.length ? (labelling ? r.wrong.map(w => `<label class="mistake"><span class="muted small">min ${w.minute} · ${e(String(w.verdict).replaceAll('_', ' ').toLowerCase())}</span><select data-label="${e(w.id)}" data-run="${run.id}"><option value="">what went wrong?</option>${page.mistakes.map(m => `<option value="${m.id}" ${w.label === m.id ? 'selected' : ''}>${e(m.label)}</option>`).join('')}</select></label>`).join('') : r.wrong.length) : ''}</td></tr>`).join('')}
    </tbody></table></div>`;

  function paint() {
    clearInterval(tick); clearInterval(poll);
    const run = page.current;
    const handle = ctx.boot.settings.cf_handle || '';
    const last = page.runs.find(r => r.ended);
    const totalMistakes = page.mistakes.reduce((a, m) => a + m.count, 0);
    root.innerHTML = `<header class="page-head"><div><p class="eyebrow">Against the clock</p><h1>Contest</h1><p class="muted">A real past Codeforces round, timed, scored the ICPC way: problems solved, then minutes plus ${page.wrong_cost ?? 20} for every wrong submission. No nudges, tutor or editorials while it runs.</p></div></header>
    ${run ? `<section class="surface contest-live"><p class="eyebrow">Round ${run.contest} · ${e(run.handles.join(', '))}</p><p class="contest-clock" data-clock aria-live="off">${clock(run.seconds_left)}</p>
        <p><strong>${run.solved}</strong> solved · penalty <strong>${run.penalty}</strong> <span class="muted small">· last read from the judge ${run.checked_at ? new Date(run.checked_at).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'}) : 'not yet'}</span></p>
        ${board(run, false)}
        <div class="step-actions"><a class="btn btn-primary" href="${e(run.url)}" target="_blank" rel="noopener noreferrer">Open the round on Codeforces</a><button class="btn btn-secondary" type="button" data-refresh>Read my submissions now</button><button class="btn btn-ghost" type="button" data-end>End the contest</button></div>
        <p class="muted small">Submit on Codeforces as usual (practice or virtual participation). The score here is read from your public submissions and updates every minute.</p></section>`
      : `<section class="surface"><h2>Start a contest</h2><form data-start novalidate><div class="form-grid">
          <label class="field">Codeforces round number<input type="text" name="contest" inputmode="numeric" autocomplete="off" placeholder="e.g. 2061" required></label>
          <label class="field">Length in minutes<input type="text" name="minutes" inputmode="numeric" value="300"></label>
          <label class="field">Handles (you, or your whole team: up to three, separated by spaces)<input type="text" name="handles" autocomplete="off" spellcheck="false" value="${e(handle)}"></label></div>
          <p class="muted small">The round number is the one in its address: codeforces.com/contest/<strong>2061</strong>. Pick a round none of you has seen. Gym contests cannot be read without a login, so only regular rounds work. ICPC regionals run five hours; a Div. 1 + Div. 2 round done as a team in five hours is a fair rehearsal.</p>
          <div class="step-actions"><button class="btn btn-primary" type="submit">Start the clock</button></div></form></section>`}
    ${last ? `<section class="surface"><h2>Last contest: round ${last.contest}</h2><p><strong>${last.solved}</strong> solved · penalty <strong>${last.penalty}</strong> · ${last.minutes} minutes · ${e(last.handles.join(', '))}</p>
        ${last.rows.some(r => r.wrong.length) ? '<p class="muted small">Each wrong submission cost 20 minutes. Say what each one was; the pattern is on the right.</p>' : ''}${board(last, true)}
        <div class="step-actions"><button class="btn btn-secondary btn-sm" type="button" data-recheck="${last.id}">Read my submissions again (for upsolves)</button></div></section>` : ''}
    <div class="start-grid">
      <section class="surface"><h2>To upsolve</h2>${page.upsolve.length ? `<ul class="plain-list">${page.upsolve.map(u => `<li><a href="${e(u.url)}" target="_blank" rel="noopener noreferrer">${e(u.contest + u.index)} · ${e(u.name)}</a>${u.rating ? ` <span class="muted small">· ${u.rating}</span>` : ''}</li>`).join('')}</ul><p class="muted small">A problem leaves this list when the judge shows an accepted submission from one of the run's handles.</p>` : '<p class="muted">Nothing. Problems you did not solve in a contest wait here until you get them accepted.</p>'}</section>
      <section class="surface"><h2>What costs you penalties</h2>${totalMistakes ? `<ul class="bars">${page.mistakes.filter(m => m.count).sort((a, b) => b.count - a.count).map(m => `<li><span>${e(m.label)}</span><span class="bar"><span style="width:${Math.round(100 * m.count / totalMistakes)}%"></span></span><strong>${m.count}</strong></li>`).join('')}</ul>` : '<p class="muted">Counted from the wrong submissions you label after each contest.</p>'}${page.unlabelled ? `<p class="muted small">${page.unlabelled} wrong submission${page.unlabelled === 1 ? '' : 's'} not labelled yet.</p>` : ''}</section>
    </div>
    ${page.runs.filter(r => r.ended).length > 1 ? `<section class="surface"><h2>Earlier contests</h2><div class="table-scroll"><table class="table"><thead><tr><th>Round</th><th>Date</th><th>Solved</th><th>Penalty</th><th>Team</th></tr></thead><tbody>${page.runs.filter(r => r.ended).map(r => `<tr><td><a href="${e(r.url)}" target="_blank" rel="noopener noreferrer">${r.contest}</a></td><td>${new Date(r.started_at).toLocaleDateString([], {day: 'numeric', month: 'short'})}</td><td>${r.solved} of ${r.rows.length}</td><td>${r.penalty}</td><td>${e(r.handles.join(', '))}</td></tr>`).join('')}</tbody></table></div></section>` : ''}`;

    const reload = async () => { page = await api('/contests'); if (alive()) { paint(); ctx.sync(); } };
    const act = async (path, body, quiet) => { try { await post(path, body); await reload(); } catch (error) { if (!quiet) toast(error.message, 'error'); } };

    root.querySelector('[data-start]')?.addEventListener('submit', async event => {
      event.preventDefault();
      const f = new FormData(event.target);
      const handles = String(f.get('handles')).split(/[\s,]+/).filter(Boolean);
      if (!await dialog({title: 'Start the clock?', body: `Round ${f.get('contest')}, ${f.get('minutes')} minutes, for ${handles.join(', ') || 'nobody yet'}. Help is locked everywhere in the app until it ends.`, confirm: 'Start'})) return;
      await act('/contest/start', {contest: Number(f.get('contest')), minutes: Number(f.get('minutes')), handles});
    });
    root.querySelector('[data-refresh]')?.addEventListener('click', () => act('/contest/refresh', {run: run.id}));
    root.querySelector('[data-recheck]')?.addEventListener('click', event => act('/contest/refresh', {run: Number(event.target.dataset.recheck)}));
    root.querySelector('[data-end]')?.addEventListener('click', async () => {
      if (await dialog({title: 'End the contest now?', body: 'The score is fixed at this moment. Unsolved problems go to your upsolve list.', confirm: 'End it', danger: true})) await act('/contest/end', {run: run.id});
    });
    root.querySelectorAll('[data-label]').forEach(select => select.addEventListener('change', () => { if (select.value) act('/contest/label', {run: Number(select.dataset.run), submission: select.dataset.label, label: select.value}); }));

    if (run) {
      left = run.seconds_left;
      tick = setInterval(() => {
        left = Math.max(0, left - 1);
        const node = root.querySelector('[data-clock]');
        if (node) node.textContent = clock(left);
        if (left === 0) { clearInterval(tick); act('/contest/end', {run: run.id}, true); }
      }, 1000);
      poll = setInterval(() => act('/contest/refresh', {run: run.id}, true), 60000);
    }
  }
  paint();
}
