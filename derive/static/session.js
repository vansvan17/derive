/* A sitting with the tutor: a timed session that says what to do next, watches how it goes and calls the breaks.
   The rules live on the server (derive/session.py) and read the record the app already keeps. This file is the
   strip that stays at the top of every page while a sitting runs, and the page where one is started and reviewed.
   Nothing is locked while a sitting runs; the strip only points. */
const BEAT = 15000, FAST = 3000;      // how often the page reports in; faster while the tutor is writing                       // how often the page reports in, in milliseconds
let hooks = null, status = null, timer = null, beat = null, active = true, tickAt = 0, lastStage = '';
let dockOpen = false, shownChat = -1, unread = 0;
try { dockOpen = localStorage.getItem('derive-tutor-dock') === 'open'; } catch { /* the dock just starts closed */ }

const clock = seconds => { const s = Math.max(0, Math.round(seconds)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`; };
const mins = seconds => Math.max(1, Math.round(seconds / 60));
const bar = () => document.querySelector('[data-sitting]');

function paint() {
  const host = bar();
  if (!host) return;
  const {escape: e} = hooks;
  if (!status?.running) { if (!host.hidden) { host.hidden = true; host.innerHTML = ''; window.dispatchEvent(new Event('resize')); } return; }
  const s = status, stage = s.stage, here = stage && location.hash === stage.href;
  const offer = !s.on_break && s.offer_break;
  host.className = `sitting tone-${offer ? 'break' : s.tone}`;
  host.innerHTML = `<div class="sitting-top">
      <a class="sitting-clock" href="#/session" title="The sitting: what has been done so far"><span class="sitting-dot${s.on_break ? ' is-paused' : ''}"></span><span data-sitting-clock>${s.on_break ? 'paused' : s.over ? 'time is up' : clock(s.left) + ' left'}</span></a>
      ${stage ? `<span class="sitting-stage"><span class="sitting-label">${e(stage.label)}</span> ${e(stage.title)}</span>` : ''}
      <span class="sitting-actions">
        ${s.on_break ? '<button class="btn btn-primary btn-sm" type="button" data-sit="back">I am back</button>'
          : `${stage && !here ? `<a class="btn btn-primary btn-sm" href="${e(stage.href)}">Go to it →</a>` : ''}
             <button class="btn ${s.tone === 'stuck' || unread ? 'btn-secondary' : 'btn-ghost'} btn-sm" type="button" data-sit="talk" title="Open the conversation with the tutor">Talk to the tutor${unread ? ` <span class="sitting-unread">${unread}</span>` : ''}</button>
             ${offer ? '' : '<button class="btn btn-ghost btn-sm" type="button" data-sit="break">Take a break</button>'}
             ${stage ? '<button class="btn btn-ghost btn-sm" type="button" data-sit="next" title="Leave this one for now. It stays where it is.">Move on</button>' : ''}`}
        <button class="btn ${s.over ? 'btn-primary' : 'btn-ghost'} btn-sm" type="button" data-sit="end">End</button>
      </span></div>
    <div class="sitting-say" role="status"><span class="sitting-who">Tutor</span><span>${e(offer || s.say)}</span>${offer ? '<span class="sitting-offer"><button class="btn btn-primary btn-sm" type="button" data-sit="break">Take the break</button><button class="btn btn-ghost btn-sm" type="button" data-sit="keep">Keep going</button></span>' : ''}</div>`;
  if (host.hidden) { host.hidden = false; }
  window.dispatchEvent(new Event('resize'));              // pages with the editor re-fit themselves under the strip
}

function tick() {
  const node = document.querySelector('[data-sitting-clock]');
  if (!node || !status?.running || status.on_break || status.over) return;
  const left = status.left - (Date.now() - tickAt) / 1000;
  node.textContent = left > 0 ? clock(left) + ' left' : 'time is up';
}

function take(next, {announce = true} = {}) {
  const was = status;
  status = next; tickAt = Date.now();
  if (hooks.state.boot) hooks.state.boot.session = next;
  const key = next?.stage ? next.stage.href : '';
  if (announce && next?.running && was?.running && key && key !== lastStage) hooks.toast(`Next: ${next.stage.title}. Press "Go to it" when you are ready.`, 'success');
  lastStage = key;
  const chat = next?.running ? next.chat || [] : [];
  if (shownChat >= 0 && chat.length > shownChat && chat[chat.length - 1].who === 'tutor' && !dockOpen) { unread += chat.length - shownChat; hooks.toast('The tutor said something. Press "Talk to the tutor".', 'info'); }
  paint(); paintDock();
  clearInterval(timer); clearInterval(beat);
  if (next?.running) { timer = setInterval(tick, 1000); beat = setInterval(report, next.thinking ? FAST : BEAT); }
  document.dispatchEvent(new CustomEvent('derive-sitting'));
}

async function report() {
  if (!status?.running || document.hidden) return;
  const was = active; active = false;
  try { take(await hooks.api('/session/seen', {method: 'POST', body: {route: location.hash, active: was}})); } catch { active = active || was; }
}

/* Called by the shell once it is built, and again whenever the address changes or something was sent to the server. */
export function sittingStart(given) {
  hooks = given;
  for (const name of ['keydown', 'pointerdown']) document.addEventListener(name, () => { active = true; }, {capture: true, passive: true});
  document.addEventListener('click', async event => {
    const button = event.target.closest?.('[data-sit]');
    if (!button) return;
    const what = button.dataset.sit;
    if (what === 'talk') { setDock(!dockOpen); return; }
    if (what === 'dock-close') { setDock(false); return; }
    if (what === 'end' && !(await hooks.dialog({title: 'End the sitting?', body: status?.over ? 'You get a short account of how it went.' : 'There is time left on the clock. You get a short account of how it went, and nothing you did is lost.', confirm: 'End it', cancel: 'Not yet'}))) return;
    if (what === 'next' && !(await hooks.dialog({title: 'Move on from this one?', body: 'It stays exactly where you left it and you can come back to it any time. The tutor will hand you something else.', confirm: 'Move on', cancel: 'Stay'}))) return;
    button.disabled = true;
    try {
      take(await hooks.api('/session/' + what, {method: 'POST', body: {}}), {announce: what !== 'next'});
      if (what === 'end') hooks.navigate('#/session');
      else if (what === 'next' && status.stage) hooks.navigate(status.stage.href);
    } catch (error) { hooks.toast(error.message, 'error'); button.disabled = false; }
  });
  take(hooks.state.boot?.session || null, {announce: false});
}
/* After the page did something (an answer, a judged program), ask the tutor again shortly, so it reacts at once. */
let soon = null;
export function sittingPoke() { if (!status?.running) return; clearTimeout(soon); soon = setTimeout(report, 500); }
export function sittingRepaint() { if (status?.running) paint(); }
/* The page has just re-read everything from the server (after an accept, say): take the sitting from that, so the strip reacts at once. */
export function sittingAdopt(next) { if (hooks && next && (next.running || status?.running)) take(next); }

/* ---------- the conversation: a panel docked at the bottom right, open on any page ---------- */
function setDock(open) {
  dockOpen = open; if (open) unread = 0;
  try { localStorage.setItem('derive-tutor-dock', open ? 'open' : 'closed'); } catch { /* fine */ }
  paint(); paintDock(true);
  if (open) document.querySelector('[data-dock-input]')?.focus();
}
function paintDock(force = false) {
  let dock = document.querySelector('[data-sitting-dock]');
  if (!status?.running || !dockOpen) { dock?.remove(); shownChat = status?.running ? (status.chat || []).length : -1; return; }
  const {escape: e} = hooks, md = hooks.ctx.markdown, chat = status.chat || [];
  if (!dock) {
    dock = document.createElement('aside');
    dock.className = 'tutor-dock'; dock.dataset.sittingDock = ''; dock.setAttribute('aria-label', 'Conversation with the tutor');
    dock.innerHTML = `<header><strong>Tutor</strong><span class="muted small" data-dock-note></span><button class="btn btn-ghost btn-sm" type="button" data-sit="dock-close" aria-label="Close the conversation">Close</button></header>
      <div class="tutor-dock-log" data-dock-log></div>
      <form data-dock-form><textarea data-dock-input rows="2" placeholder="Ask, answer, or say what you are thinking…" aria-label="Your message"></textarea><button class="btn btn-primary btn-sm" type="submit">Send</button></form>`;
    document.body.append(dock);
    const input = dock.querySelector('[data-dock-input]');
    input.addEventListener('keydown', event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); dock.querySelector('form').requestSubmit(); } });
    dock.querySelector('form').addEventListener('submit', async event => {
      event.preventDefault();
      const said = input.value.trim();
      if (!said || status?.thinking) return;
      input.value = '';
      try { take(await hooks.api('/session/say', {method: 'POST', body: {text: said}})); }
      catch (error) { hooks.toast(error.message, 'error'); input.value = said; }
    });
    force = true;
  }
  const voice = hooks.state.boot?.voice;
  dock.querySelector('[data-dock-note]').textContent = voice ? 'sees what you are on and what the app has watched' : 'switched off';
  if (force || chat.length !== shownChat || dock.dataset.thinking !== String(!!status.thinking)) {
    const log = dock.querySelector('[data-dock-log]');
    log.innerHTML = (chat.length ? chat.map(m => `<div class="tutor-msg ${m.who === 'tutor' ? 'is-tutor' : 'is-me'}">${m.who === 'tutor' ? md(m.text) : `<p>${e(m.text)}</p>`}</div>`).join('')
        : `<p class="muted small">${voice ? 'Nothing said yet. Tell the tutor what you are thinking, ask it to teach you something, or ask where to look. It is told what you are on, your wrong answers and how long you have been at it.' : 'The talking tutor is switched off, so only the strip at the top speaks. Turn it on under Settings → In-app tutor (it uses the Codex command on this Mac).'}</p>`)
      + (status.thinking ? '<div class="tutor-msg is-tutor is-thinking"><span class="spinner"></span> thinking… this can take up to a minute</div>' : '');
    log.scrollTop = log.scrollHeight;
    dock.dataset.thinking = String(!!status.thinking);
    shownChat = chat.length;
  }
  dock.querySelector('button[type=submit]').disabled = !!status.thinking || !voice;
}

/* ---------- the page ---------- */
function recapHtml(r, e, first) {
  const when = new Date(r.at).toLocaleString([], {weekday: 'short', day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit'});
  const outcome = {done: '<span class="badge badge-success">done</span>', 'moved on': '<span class="badge">moved on</span>', unfinished: '<span class="badge badge-primary">in progress</span>'};
  return `<section class="surface recap">${first ? '<p class="eyebrow">How it went</p>' : ''}<h2>${e(when)}</h2>
    <p class="muted small">Set for ${r.minutes} min · worked ${mins(r.worked)} min${r.breaks ? ` · ${r.breaks} ${r.breaks === 1 ? 'break' : 'breaks'} (${mins(r.break_seconds)} min)` : ' · no breaks'}</p>
    <dl class="evidence big"><div><dt>Questions right</dt><dd>${r.right}</dd></div><div><dt>Misses on the way</dt><dd>${r.wrong}</dd></div><div><dt>Programs accepted</dt><dd>${r.accepted}<small> · ${r.rejected} rejected</small></dd></div><div><dt>Help opened</dt><dd>${r.helped}</dd></div></dl>
    ${r.stages.length ? `<ol class="rows">${r.stages.map((st, k) => `<li class="row"><span class="row-mark${st.outcome === 'done' ? ' is-done' : ''}">${st.outcome === 'done' ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>' : k + 1}</span><a class="row-title" href="${e(st.href)}">${e(st.title)}</a><span class="row-note">${e(st.label)} · ${mins(st.seconds)} min ${outcome[st.outcome] || ''}</span></li>`).join('')}</ol>` : ''}
    ${r.hardest ? `<p><strong>Where it was hardest:</strong> question ${r.hardest.question} of <a href="${e(r.hardest.href)}">${e(r.hardest.title)}</a>, ${r.hardest.misses} misses. Worth one more look while it is fresh.</p>` : ''}
    ${r.next ? `<p><strong>Next time, start with:</strong> <a href="${e(r.next.href)}">${e(r.next.title)}</a>.</p>` : ''}</section>`;
}

export async function renderSession(ctx) {
  const {api, post, escape: e, toast} = ctx;
  const root = ctx.root;
  const draw = async () => {
    const s = await api('/session');
    if (ctx.root !== root) return;
    const head = `<header class="page-head"><div><p class="eyebrow">Someone to sit with you</p><h1>Sit with a tutor</h1><p class="muted">A timed sitting. The tutor hands you one thing at a time, watches how it goes, tells you when to change tack, and calls the breaks.</p></div></header>`;
    if (s.running) {
      root.innerHTML = head + `<section class="surface"><h2>${s.on_break ? 'On a break' : s.over ? 'Time is up' : 'A sitting is running'}</h2>
        <p class="muted">Set for ${s.minutes} min · ${mins(s.worked)} min worked${s.over ? '' : ` · ${mins(s.left)} min left`}. The strip at the top of every page is the tutor; use it from wherever you are.</p>
        ${s.goal ? `<p><strong>What you asked for:</strong> ${e(s.goal)}</p>` : ''}
        ${s.stage ? `<p><strong>Now:</strong> ${e(s.stage.label)} · <a href="${e(s.stage.href)}">${e(s.stage.title)}</a></p>` : ''}
        ${s.plan?.length ? `<p><strong>Still planned:</strong> ${s.plan.map(p => e(p.title)).join(' · ')}</p>` : ''}
        ${s.done.length ? `<h3>So far</h3><ol class="rows">${s.done.map((d, k) => `<li class="row"><span class="row-mark${d.outcome === 'done' ? ' is-done' : ''}">${d.outcome === 'done' ? '✓' : k + 1}</span><span class="row-title">${e(d.title)}</span><span class="row-note">${e(d.label)} · ${e(d.outcome)}</span></li>`).join('')}</ol>` : ''}</section>`;
      return;
    }
    const voice = ctx.boot.voice;
    root.innerHTML = head + `<section class="surface"><h2>Start a sitting</h2>
        <form data-plan-form>
          <label class="field">What do you want to do today?<textarea name="goal" rows="3" placeholder="${voice ? 'e.g. finish Derive for Numbers and remainders today. Or: I keep failing counting problems, teach me to count properly and make me code two.' : 'With the talking tutor off, only the name of an area of the map is understood, e.g. finish Numbers and remainders. Anything else gets the usual plan.'}"></textarea></label>
          <p class="sit-length">How long do you have? ${s.lengths.map(m => `<label class="sit-pill"><input type="radio" name="minutes" value="${m}" ${m === 60 ? 'checked' : ''}> ${m} min</label>`).join('')}</p>
          <div class="step-actions"><button class="btn btn-primary" type="submit">${voice ? 'Plan my sitting' : 'Start'}</button></div>
        </form>
        <div data-plan aria-live="polite"></div>
        ${voice ? '' : `<aside class="basis-note" role="note"><p><strong>The talking tutor is off.</strong> With it on, you say what you want, it plans the sitting from that, and you can talk to it the whole time. It runs through the Codex command on this Mac with your own login. What gets sent to it: the question or task you are on, your answers and code, what the app has timed, and your messages. <button class="link-btn" type="button" data-voice-on>Turn it on</button></p></aside>`}
        <h3 class="sit-how">What happens</h3>
        <ul class="sit-list"><li><strong>You say what you want.</strong> The tutor builds the sitting out of what the app has: chains that teach an idea by questions, Toolbox pages, tasks you code and get judged.</li><li><strong>It teaches and you work.</strong> One thing at a time. Talk to it whenever you like; ask it to explain, or tell it what you are thinking.</li><li><strong>It watches.</strong> Every answer, every judged program, every hint, and how long you have been on one thing. When you miss several times or sit too long it tells you how to change tack, and speaks up on its own when you are stuck.</li><li><strong>It calls the breaks</strong> just after you finish something, once you have worked long enough or the misses pile up. The clock stops during a break.</li><li><strong>At the end</strong> it tells you how the sitting went and where to start next time.</li></ul>
        <p class="muted small">Honest notes. The watching is done by rules on this computer reading your record; the talking is Codex, which takes up to a minute per reply and can be wrong. While something is unfinished it is told not to give the answer or name what you are deriving. Talking to it about an unfinished chain or task counts as help, the same as the "Ask a tutor" button. Nothing is locked while a sitting runs, and you can move on or end it at any moment.</p></section>
      ${s.past.map((r, k) => recapHtml(r, e, k === 0)).join('')}`;
    const form = root.querySelector('[data-plan-form]'), box = root.querySelector('[data-plan]');
    const begin = async (minutes, goal, plan, say) => {
      const next = await post('/session/start', {minutes, goal, plan: plan.map(p => ({kind: p.kind, id: p.id})), say});
      take(next, {announce: false}); if (say) setDock(true);
      if (next.stage) ctx.navigate(next.stage.href); else draw();
    };
    root.querySelector('[data-voice-on]')?.addEventListener('click', async () => {
      try { await post('/settings', {tutor: 'codex'}); await ctx.sync(); toast('The talking tutor is on.', 'success'); draw(); } catch (error) { toast(error.message, 'error'); }
    });
    form.addEventListener('submit', async event => {
      event.preventDefault();
      const minutes = Number(new FormData(form).get('minutes')), goal = form.elements.goal.value.trim(), button = form.querySelector('button[type=submit]');
      button.disabled = true;
      try {
        let made = await post('/session/plan', {minutes, goal});
        if (made.job) {
          box.innerHTML = '<p class="sit-wait"><span class="spinner"></span> The tutor is reading what you wrote and choosing from what the app has. This can take a minute.</p>';
          made = (await ctx.waitFor(made.job, () => ctx.root === root))?.result;
          if (!made || ctx.root !== root) return;
          if (made.error) throw new Error(made.error);
        }
        if (made.voice === false) { await begin(minutes, goal, made.plan, ''); return; }
        box.innerHTML = `<div class="sit-plan">${made.status === 'fallback' ? `<p class="inline-error">${e(made.reason)}</p>` : ''}${made.say ? `<div class="tutor-msg is-tutor">${ctx.markdown(made.say)}</div>` : ''}
          <ol class="rows">${made.plan.map((p, k) => `<li class="row"><span class="row-mark">${k + 1}</span><span class="row-main"><span class="row-title">${e(p.title)}</span><span class="row-when">${e(p.why || '')}</span></span><span class="row-note">${e(p.label)}</span></li>`).join('')}</ol>
          <div class="step-actions"><button class="btn btn-primary" type="button" data-begin>Start</button><span class="muted small">Not what you meant? Change what you wrote above and plan again.</span></div></div>`;
        box.querySelector('[data-begin]').addEventListener('click', async ev => { ev.target.disabled = true; try { await begin(minutes, goal, made.plan, made.say); } catch (error) { toast(error.message, 'error'); ev.target.disabled = false; } });
        button.textContent = 'Plan again';
      } catch (error) { toast(error.message, 'error'); box.innerHTML = ''; }
      finally { button.disabled = false; }
    });
  };
  const again = () => { if (ctx.root === root) draw(); };
  document.addEventListener('derive-sitting', again);
  ctx.onCleanup(() => document.removeEventListener('derive-sitting', again));
  await draw();
}
