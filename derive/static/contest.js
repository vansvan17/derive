/* Contest mode: a real Codeforces round, or a mixed set drawn for the team, against the clock
   and scored the ICPC way. While the clock runs there is no help anywhere in the app.
   Afterwards comes the debrief: what the judge's record shows, a label on every wrong
   submission, what stalled the team on each unsolved problem, and one lesson. */

const clock = seconds => `${Math.floor(seconds / 3600)}:${String(Math.floor(seconds % 3600 / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;

export async function renderContest(ctx) {
  const {api, post, escape: e, toast, dialog} = ctx;
  const root = ctx.root, alive = () => ctx.root === root;
  let page = await api('/contests');
  if (!alive()) return;
  let tick = null, poll = null, left = 0, kind = 'mixed', lessonDraft = null;
  ctx.onCleanup(() => { clearInterval(tick); clearInterval(poll); });

  const board = (run, labelling) => `<div class="table-scroll"><table class="table"><thead><tr><th>#</th><th>Problem</th><th>Result</th><th>Minute</th>${run.handles.length > 1 ? '<th>By</th>' : ''}<th>Wrong tries</th>${labelling ? '<th>If unsolved: what stalled you</th>' : ''}</tr></thead><tbody>
    ${run.rows.map(r => `<tr><td>${e(r.index)}</td><td><a href="${e(r.url)}" target="_blank" rel="noopener noreferrer">${e(r.name)}</a>${run.ended && r.rating ? ` <span class="muted small">· ${r.rating}</span>` : ''}</td>
      <td>${r.solved ? '<span class="badge badge-success">Accepted</span>' : r.upsolved ? '<span class="badge badge-primary">Upsolved</span>' : r.wrong.length ? '<span class="badge">Tried</span>' : '<span class="muted">·</span>'}</td>
      <td>${r.minute ?? ''}</td>${run.handles.length > 1 ? `<td>${e(r.by || '')}</td>` : ''}
      <td>${r.wrong.length ? (labelling ? r.wrong.map(w => `<label class="mistake"><span class="muted small">min ${w.minute} · ${e(String(w.verdict).replaceAll('_', ' ').toLowerCase())}</span><select data-label="${e(w.id)}" data-run="${run.id}"><option value="">what went wrong?</option>${page.mistakes.map(m => `<option value="${m.id}" ${w.label === m.id ? 'selected' : ''}>${e(m.label)}</option>`).join('')}</select></label>`).join('') : r.wrong.length) : ''}</td>${labelling ? `<td>${r.solved ? '' : `${r.reach ? `<span class="reach reach-${r.reach.kind}">${reach(r, run.handles.length === 1)}</span>` : ''}<select data-stall="${e(r.index)}" data-run="${run.id}" aria-label="What stalled you on ${e(r.index)}"><option value="">choose</option>${page.stalls.map(m => `<option value="${m.id}" ${r.stall === m.id ? 'selected' : ''}>${e(m.label)}</option>`).join('')}</select>`}</td>` : ''}</tr>`).join('')}
    </tbody></table></div>`;

  // Was an unsolved problem within reach? Judged against each teammate's own Codeforces rating.
  const names = who => who.length > 1 ? who.slice(0, -1).map(e).join(', ') + ' and ' + e(who.at(-1)) : e(who[0] || '');
  const reach = (r, solo) => !r.reach ? '' : r.reach.kind === 'should' ? `<strong>${solo ? 'You' : names(r.reach.who)} should have been able to solve it.</strong>` : r.reach.kind === 'fair' ? `About ${solo ? 'your' : names(r.reach.who) + "'s"} level: a fair fight.` : `Above ${solo ? 'your' : "the team's"} level for now. It's okay.`;

  // What the judge's record says about the run. Every line is computed; none of it is typed in.
  const debrief = run => { const d = run.debrief; if (!d) return ''; const team = run.handles.length > 1; const lines = [];
    lines.push(d.first == null ? 'Nothing was accepted.' : `First accept at minute ${d.first}, last at minute ${d.last}.`);
    if (d.first != null) lines.push(`Longest stretch with no accept: <strong>${d.dry.minutes} minutes</strong> (minute ${d.dry.from} to ${d.dry.to}).`);
    if (d.first != null) lines.push(d.final_third ? `${d.final_third} accepted in the final third of the time.` : '<strong>Nothing accepted in the final third of the time.</strong>');
    const owed = run.rows.filter(r => r.reach?.kind === 'should');
    if (owed.length) lines.push(`Within reach and unsolved: ${owed.map(r => `${e(r.index)} (${r.rating}${team ? ', ' + names(r.reach.who) : ''})`).join('; ')}. These are the ones that cost you; upsolve them first.`);
    else if (run.rows.some(r => r.reach)) lines.push('Every unsolved problem was at or above your level. Nothing was thrown away.');
    if (Object.keys(run.levels || {}).length) lines.push(`<span class="muted small">Judged against Codeforces ratings: ${Object.entries(run.levels).map(([h, x]) => `${e(h)} ${x}`).join(', ')}. "Should have" means the problem is rated at least 100 below that person.</span>`);
    if (d.left.length) lines.push(`Left on the table: ${d.left.map(l => `${e(l.index)} (${l.rating})`).join(', ')}, rated below a problem you did solve.`);
    if (d.late.length) lines.push(`Found late: ${d.late.map(l => `${e(l.index)} (${l.rating}, minute ${l.minute})`).join(', ')}, accepted at least half an hour after a clearly harder problem.`);
    if (team) lines.push(d.people.map(p => `${e(p.handle)}: ${p.accepted} accepted, ${p.wrong} wrong`).join(' · ') + '. <span class="muted small">This shows whose account submitted, which on one computer may be whoever was logged in.</span>');
    return `<h3>What the record shows</h3><ul class="debrief">${lines.map(l => `<li>${l}</li>`).join('')}</ul>`; };

  function paint() {
    clearInterval(tick); clearInterval(poll);
    const run = page.current;
    const handle = ctx.boot.settings.cf_handle || '';
    const last = page.runs.find(r => r.ended);
    const totalMistakes = page.mistakes.reduce((a, m) => a + m.count, 0), totalStalls = page.stalls.reduce((a, m) => a + m.count, 0);
    const ended = page.runs.filter(r => r.ended);
    root.innerHTML = `<header class="page-head"><div><p class="eyebrow">Against the clock</p><h1>Contest</h1><p class="muted">For you alone or for the whole team at one computer. A mixed set of recent problems, or a real past Codeforces round, timed and scored the ICPC way: problems solved, then minutes plus ${page.wrong_cost ?? 20} for every wrong submission. No nudges, tutor or editorials while it runs. Afterwards, a debrief.</p></div></header>
    ${run ? `<section class="surface contest-live"><p class="eyebrow">${e(run.title)} · ${e(run.handles.join(', '))}</p><p class="contest-clock" data-clock aria-live="off">${clock(run.seconds_left)}</p>
        <p><strong>${run.solved}</strong> solved · penalty <strong>${run.penalty}</strong> <span class="muted small">· last read from the judge ${run.checked_at ? new Date(run.checked_at).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'}) : 'not yet'}</span></p>
        ${board(run, false)}
        <div class="step-actions">${run.url ? `<a class="btn btn-primary" href="${e(run.url)}" target="_blank" rel="noopener noreferrer">Open the round on Codeforces</a>` : ''}<button class="btn btn-secondary" type="button" data-refresh>Read my submissions now</button><button class="btn btn-ghost" type="button" data-end>End the contest</button></div>
        <p class="muted small">Submit on Codeforces as usual. The score here is read from your public submissions and updates every minute.${run.mixed ? ' The problems are in no particular order: reading all of them and finding the easy ones is part of the contest. Each page on Codeforces shows the problem\'s real letter in its round, which hints at its difficulty; try not to look.' : ''}</p></section>`
      : `<section class="surface"><h2>Start a contest</h2><form data-start novalidate>
          <div class="choices-row" role="radiogroup" aria-label="What to sit"><label><input type="radio" name="kind" value="mixed" ${kind === 'mixed' ? 'checked' : ''}> A mixed set drawn for you</label><label><input type="radio" name="kind" value="round" ${kind === 'round' ? 'checked' : ''}> One past round</label></div>
          <div class="form-grid">
          ${kind === 'mixed' ? `<label class="field">Problems<input type="text" name="count" inputmode="numeric" value="11"></label>
          <label class="field">Easiest rating<input type="text" name="low" inputmode="numeric" value="1000"></label>
          <label class="field">Hardest rating<input type="text" name="high" inputmode="numeric" value="2600"></label>` : `<label class="field">Codeforces round number<input type="text" name="contest" inputmode="numeric" autocomplete="off" placeholder="e.g. 2061" required></label>`}
          <label class="field">Length in minutes<input type="text" name="minutes" inputmode="numeric" value="300"></label>
          <label class="field">Handles (you, or your whole team: up to three, separated by spaces)<input type="text" name="handles" autocomplete="off" spellcheck="false" value="${e(handle)}"></label></div>
          <p class="muted small">${kind === 'mixed' ? 'The set is drawn from Codeforces rounds since January 2025, with ratings spread evenly between the two you give, then shuffled and lettered from A. Nothing that any of the handles has ever submitted is used, and nothing the Solve page is keeping for you. A regional set has more problems than a team is expected to finish, so set the hardest rating well above what you can do.' : 'The round number is the one in its address: codeforces.com/contest/<strong>2061</strong>. Pick a round none of you has seen. Gym contests cannot be read without a login, so only regular rounds work.'} Give every teammate's handle, so that whoever submits is counted.</p>
          <div class="step-actions"><button class="btn btn-primary" type="submit">Start the clock</button></div></form></section>`}
    ${last ? `<section class="surface"><h2>Debrief: ${e(last.title.toLowerCase())}</h2><p><strong>${last.solved}</strong> solved · penalty <strong>${last.penalty}</strong> · ${last.minutes} minutes · ${e(last.handles.join(', '))}</p>
        ${last.rows.some(r => r.wrong.length) ? '<p class="muted small">Each wrong submission cost 20 minutes. Say what each one was; the pattern is on the right.</p>' : ''}${board(last, true)}
        ${debrief(last)}
        <form data-lesson="${last.id}" novalidate><label class="field">One thing to do differently next time, in your own words<textarea name="lesson" rows="2" maxlength="600" placeholder="e.g. Nobody read H until minute 200. Next time all eleven are read in the first 40 minutes.">${e(lessonDraft ?? last.lesson)}</textarea></label>
        <div class="step-actions"><button class="btn btn-primary btn-sm" type="submit">Save the lesson</button><button class="btn btn-secondary btn-sm" type="button" data-recheck="${last.id}">Read my submissions again (for upsolves)</button></div></form></section>` : ''}
    <div class="start-grid">
      <section class="surface"><h2>To upsolve</h2>${page.upsolve.length ? `<ul class="plain-list">${page.upsolve.map(u => `<li><a href="${e(u.url)}" target="_blank" rel="noopener noreferrer">${e(u.label)} · ${e(u.name)}</a>${u.rating ? ` <span class="muted small">· ${u.rating}</span>` : ''}</li>`).join('')}</ul><p class="muted small">A problem leaves this list when the judge shows an accepted submission from one of the run's handles.</p>` : '<p class="muted">Nothing. Problems you did not solve in a contest wait here until you get them accepted.</p>'}</section>
      <section class="surface"><h2>What costs you penalties</h2>${totalMistakes ? `<ul class="bars">${page.mistakes.filter(m => m.count).sort((a, b) => b.count - a.count).map(m => `<li><span>${e(m.label)}</span><span class="bar"><span style="width:${Math.round(100 * m.count / totalMistakes)}%"></span></span><strong>${m.count}</strong></li>`).join('')}</ul>` : '<p class="muted">Counted from the wrong submissions you label after each contest.</p>'}${page.unlabelled ? `<p class="muted small">${page.unlabelled} wrong submission${page.unlabelled === 1 ? '' : 's'} not labelled yet.</p>` : ''}</section>
      <section class="surface"><h2>What stalls you</h2>${totalStalls ? `<ul class="bars">${page.stalls.filter(m => m.count).sort((a, b) => b.count - a.count).map(m => `<li><span>${e(m.label)}</span><span class="bar"><span style="width:${Math.round(100 * m.count / totalStalls)}%"></span></span><strong>${m.count}</strong></li>`).join('')}</ul>` : '<p class="muted">Counted from the unsolved problems you label in each debrief.</p>'}</section>
      <section class="surface"><h2>Lessons so far</h2>${page.lessons.length ? `<ul class="plain-list lessons">${page.lessons.map(l => `<li>${e(l.lesson)} <span class="muted small">· ${e(l.title)}, ${new Date(l.date).toLocaleDateString([], {day: 'numeric', month: 'short'})}</span></li>`).join('')}</ul><p class="muted small">Read these aloud before the next contest starts.</p>` : '<p class="muted">One sentence after each contest. Read them before the next one starts.</p>'}</section>
    </div>
    ${ended.length > 1 ? `<section class="surface"><h2>Earlier contests</h2><div class="table-scroll"><table class="table"><thead><tr><th>Set</th><th>Date</th><th>Solved</th><th>Penalty</th><th>Wrong tries</th><th>Longest dry spell</th><th>Last accept</th><th>Team</th></tr></thead><tbody>${ended.map(r => `<tr><td>${r.url ? `<a href="${e(r.url)}" target="_blank" rel="noopener noreferrer">${e(r.title)}</a>` : e(r.title)}</td><td>${new Date(r.started_at).toLocaleDateString([], {day: 'numeric', month: 'short'})}</td><td>${r.solved} of ${r.rows.length}</td><td>${r.penalty}</td><td>${r.debrief.wrong}</td><td>${r.debrief.dry.minutes} min</td><td>${r.debrief.last == null ? '' : 'min ' + r.debrief.last}</td><td>${e(r.handles.join(', '))}</td></tr>`).join('')}</tbody></table></div></section>` : ''}`;

    const reload = async () => { page = await api('/contests'); if (alive()) { paint(); ctx.sync(); } };
    const act = async (path, body, quiet) => { try { await post(path, body); await reload(); return true; } catch (error) { if (!quiet) toast(error.message, 'error'); return false; } };

    root.querySelector('[data-start]')?.addEventListener('submit', async event => {
      event.preventDefault();
      const f = new FormData(event.target);
      const handles = String(f.get('handles')).split(/[\s,]+/).filter(Boolean);
      const what = kind === 'mixed' ? `A mixed set of ${f.get('count')} problems` : `Round ${f.get('contest')}`;
      if (!await dialog({title: 'Start the clock?', body: `${what}, ${f.get('minutes')} minutes, for ${handles.join(', ') || 'nobody yet'}. Help is locked everywhere in the app until it ends.`, confirm: 'Start'})) return;
      const body = kind === 'mixed' ? {mixed: {count: Number(f.get('count')), low: Number(f.get('low')), high: Number(f.get('high'))}} : {contest: Number(f.get('contest'))};
      await act('/contest/start', {...body, minutes: Number(f.get('minutes')), handles});
    });
    root.querySelector('[data-refresh]')?.addEventListener('click', () => act('/contest/refresh', {run: run.id}));
    root.querySelector('[data-recheck]')?.addEventListener('click', event => act('/contest/refresh', {run: Number(event.target.dataset.recheck)}));
    root.querySelector('[data-end]')?.addEventListener('click', async () => {
      if (await dialog({title: 'End the contest now?', body: 'The score is fixed at this moment. Unsolved problems go to your upsolve list.', confirm: 'End it', danger: true})) await act('/contest/end', {run: run.id});
    });
    root.querySelectorAll('[name=kind]').forEach(radio => radio.addEventListener('change', () => { kind = radio.value; paint(); }));
    root.querySelectorAll('[data-stall]').forEach(select => select.addEventListener('change', () => { if (select.value) act('/contest/stall', {run: Number(select.dataset.run), problem: select.dataset.stall, label: select.value}); }));
    const lessonForm = root.querySelector('[data-lesson]');
    lessonForm?.elements.lesson.addEventListener('input', event => { lessonDraft = event.target.value; });
    lessonForm?.addEventListener('submit', async event => { event.preventDefault(); if (await act('/contest/lesson', {run: Number(lessonForm.dataset.lesson), lesson: lessonForm.elements.lesson.value})) { lessonDraft = null; toast('Saved.'); } });
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
