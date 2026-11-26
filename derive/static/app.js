/* Shell: start-up, navigation, and the helpers every page uses.
   Every number on screen comes from the local API. */
import katex from './vendor/math.js';
import {renderMap} from './map.js';
import {renderChain} from './chain.js';
import {renderSolve, renderProblem} from './problem.js';
import {renderMastery, renderSettings} from './record.js';
import {renderContest} from './contest.js';
import {renderPuzzles} from './puzzles.js';
import {renderTasks, renderTask} from './tasks.js';
import {renderTools, renderTool} from './tools.js';
import {renderCses} from './cses.js';
import {renderBreaks, renderBreak} from './breaks.js';
import {renderNotebook} from './notebook.js';
import {renderRecognise} from './recognise.js';
import {renderRevise} from './revise.js';

const state = {boot: null, token: 0, cleanups: [], root: null};

export const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));

const ICONS = {
  map: '<circle cx="6" cy="7" r="2.2"/><circle cx="18" cy="6" r="2.2"/><circle cx="12" cy="17" r="2.2"/><path d="M8 7.5l8-1M7 9l4 6M17 8l-4 7"/>',
  chain: '<path d="M10 14a4 4 0 005.7 0l3-3a4 4 0 00-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 00-5.7 0l-3 3a4 4 0 005.7 5.7l1-1"/>',
  target: '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="4"/><circle cx="12" cy="12" r=".6" fill="currentColor"/>',
  chart: '<path d="M4 20V5M4 20h16"/><path d="M8 16l4-5 3 3 4-6"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1"/>',
  menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
  check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
  play: '<path d="M8 5l11 7-11 7z"/>',
  external: '<path d="M14 5h5v5M19 5l-8 8"/><path d="M11 6H6a1 1 0 00-1 1v11a1 1 0 001 1h11a1 1 0 001-1v-5"/>',
  star: '<path d="M12 3.6l2.6 5.3 5.8.8-4.2 4.1 1 5.8-5.2-2.7-5.2 2.7 1-5.8-4.2-4.1 5.8-.8z"/>',
  lock: '<rect x="6" y="11" width="12" height="9" rx="2"/><path d="M9 11V8a3 3 0 016 0v3"/>',
};
export const icon = name => ICONS[name] ? `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${ICONS[name]}</svg>` : '';
const EMBLEM = '<svg viewBox="0 0 40 40" fill="none" aria-hidden="true"><rect width="40" height="40" rx="10" fill="#22365a"/><path d="M11 27c4-14 8-14 9-7s5 7 9-7" stroke="#dce7fc" stroke-width="2.2" stroke-linecap="round"/><circle cx="11" cy="27" r="2" fill="#8fb0ff"/><circle cx="29" cy="13" r="2" fill="#8fb0ff"/></svg>';

/* ---------- Text with maths ----------
   A small escaped Markdown renderer. $...$ and $$...$$ are typeset by the bundled KaTeX. */
const tex = (source, display) => { try { return katex.renderToString(source, {throwOnError: false, displayMode: display}); } catch { return escape(source); } };
export function inline(source) {
  const held = [];
  const hold = html => { held.push(html); return `\u0000${held.length - 1}\u0000`; };
  let s = String(source ?? '').replace(/\$\$([\s\S]+?)\$\$/g, (_, m) => hold(tex(m, true))).replace(/\$([^$\n]+?)\$/g, (_, m) => hold(tex(m, false)));
  s = escape(s).replace(/`([^`]+)`/g, (_, c) => hold(`<code>${c}</code>`));
  s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>').replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  return s.replace(/\u0000(\d+)\u0000/g, (_, n) => held[n]);
}
export function markdown(source) {
  const blocks = String(source ?? '').replace(/\r\n?/g, '\n').split(/\n{2,}/).filter(b => b.trim());
  return `<div class="prose">${blocks.map(block => {
    const lines = block.split('\n');
    if (lines.every(l => /^\s*[-*]\s+/.test(l))) return `<ul>${lines.map(l => `<li>${inline(l.replace(/^\s*[-*]\s+/, ''))}</li>`).join('')}</ul>`;
    return `<p>${inline(lines.join(' '))}</p>`;
  }).join('')}</div>`;
}

/* ---------- API ---------- */
async function request(path, {method = 'GET', body} = {}) {
  const headers = {Accept: 'application/json'};
  const init = {method, headers, cache: 'no-store'};
  if (method !== 'GET') {
    headers['Content-Type'] = 'application/json';
    headers['X-Derive-Token'] = state.boot?.csrf || '';
    init.body = JSON.stringify(body ?? {});
  }
  let response;
  try { response = await fetch('/api' + path, init); }
  catch { throw new Error('The app is not responding. Check that ./launch.sh is still running.'); }
  let data = null;
  try { data = await response.json(); } catch { /* handled below */ }
  return {response, data};
}
export async function api(path, options = {}) {
  let {response, data} = await request(path, options);
  // The write token changes when the app restarts; fetch the new one once and retry.
  if (response.status === 403 && options.method === 'POST' && !options.retried) {
    const fresh = await request('/bootstrap');
    if (fresh.response.ok && fresh.data.csrf !== state.boot?.csrf) { state.boot = fresh.data; return api(path, {...options, retried: true}); }
  }
  if (!response.ok) { const error = new Error(data?.error || `The request failed (${response.status}).`); error.status = response.status; throw error; }
  return data;
}
export const post = (path, body) => api(path, {method: 'POST', body});

/* Background work (running code, grading a proof): poll until it is finished. */
export async function waitFor(job, alive = () => true) {
  for (;;) {
    const j = await api('/jobs/' + job);
    if (j.status === 'done' || j.status === 'error') return j;
    await new Promise(resolve => setTimeout(resolve, 400));
    if (!alive()) return null;
  }
}

/* ---------- Toasts and dialogs ---------- */
export function toast(message, type = 'info') {
  const node = document.createElement('div');
  node.className = `toast toast-${type === 'success' || type === 'error' ? type : 'info'}`;
  node.setAttribute('role', type === 'error' ? 'alert' : 'status');
  node.textContent = String(message || '').trim().slice(0, 400);
  document.getElementById('toasts').append(node);
  setTimeout(() => node.remove(), type === 'error' ? 8000 : 4500);
}
/* Resolves false on cancel; true, or the typed text when an input was asked for. */
export function dialog({title, body = '', html = '', confirm = 'Continue', cancel = 'Cancel', danger = false, input = null, wide = false}) {
  return new Promise(resolve => {
    const node = document.createElement('dialog');
    node.className = 'modal' + (wide ? ' modal-wide' : '');
    node.setAttribute('aria-labelledby', 'modal-title');
    node.innerHTML = `<form method="dialog"><div class="modal-body"><h2 id="modal-title">${escape(title)}</h2>${body ? `<p class="muted">${escape(body)}</p>` : ''}${html}${input ? `<label class="field">${escape(input.label)}<textarea name="value" rows="${input.rows || 3}" placeholder="${escape(input.placeholder || '')}"></textarea></label>` : ''}</div><div class="modal-actions">${cancel ? `<button type="button" class="btn btn-secondary" data-cancel>${escape(cancel)}</button>` : ''}<button type="submit" class="btn ${danger ? 'btn-danger' : 'btn-primary'}">${escape(confirm)}</button></div></form>`;
    document.body.append(node);
    let result = false;
    node.querySelector('form').addEventListener('submit', () => { result = input ? node.querySelector('textarea').value.trim() || true : true; });
    node.querySelector('[data-cancel]')?.addEventListener('click', () => node.close());
    node.addEventListener('close', () => { node.remove(); resolve(result); });
    node.showModal();
  });
}

/* ---------- Shell ---------- */
export const MOD = /Mac|iPhone|iPad/.test(navigator.platform) ? '⌘' : 'Ctrl+';
const NAV = [['', 'map', 'The map'], ['derive', 'chain', 'Derive'], ['solve', 'target', 'Solve'], ['puzzles', 'chain', 'Puzzles'], ['tools', 'settings', 'Toolbox'], ['cses', 'chain', 'CSES DP'], ['code', 'play', 'Code'], ['break', 'target', 'Break it'], ['recognise', 'target', 'Recognise'], ['contest', 'target', 'Contest'], ['revise', 'star', 'Revise'], ['mastery', 'chart', 'What you can do'], ['settings', 'settings', 'Settings']];
const section = () => { const name = location.hash.replace(/^#\/?/, '').split('/')[0] || ''; return name === 'chain' ? 'derive' : name === 'problem' ? 'solve' : name === 'task' ? 'code' : name === 'tool' || name === 'notebook' ? 'tools' : name; };
function paintNav() {
  const host = document.querySelector('[data-nav-host]');
  if (!host) return;
  const here = section(), c = state.boot?.counts;
  host.innerHTML = NAV.map(([name, glyph, label]) => `<a class="nav-link" href="#/${name}" ${name === here ? 'aria-current="page"' : ''}>${icon(glyph)}<span>${label}${name === 'revise' && state.boot?.stars?.length ? ` · ${state.boot.stars.length}` : ''}</span></a>`).join('')
    + (c ? `<p class="sidebar-count">${c.derived} of ${c.chains} chains derived<br>${c.cold} cold solves · working at ${state.boot.band.band}</p>` : '');
}
export function applyTheme(theme) {
  const actual = theme === 'system' || !theme ? (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light') : theme;
  document.documentElement.dataset.theme = actual;
  // The switch says what a click will do, so it reads "Dark mode" while the page is light.
  document.querySelectorAll('[data-theme-toggle]').forEach(b => { b.textContent = actual === 'dark' ? '☀ Light mode' : '☾ Dark mode'; b.setAttribute('aria-label', actual === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'); });
}
/* One click, from any page: flip between light and dark and remember it. */
async function toggleTheme() {
  const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
  applyTheme(next);
  if (state.boot) state.boot.settings.theme = next;
  try { await post('/settings', {theme: next}); } catch (error) { toast('The theme was switched but could not be saved: ' + error.message, 'error'); }
}
function buildShell() {
  const app = document.getElementById('app');
  app.innerHTML = `<div class="shell">
    <header class="topbar"><button class="menu-btn" type="button" data-menu aria-label="Open navigation" aria-expanded="false" aria-controls="sidebar">${icon('menu')}</button><a class="brand" href="#/">${EMBLEM}<span class="brand-name">derive</span></a><span class="spacer"></span><button class="theme-toggle theme-toggle-top" type="button" data-theme-toggle></button></header>
    <aside class="sidebar" id="sidebar" aria-label="Navigation">
      <button class="side-toggle" type="button" data-side-toggle></button>
      <a class="brand" href="#/">${EMBLEM}<span><span class="brand-name">derive</span><span class="brand-sub">nothing is told, only asked</span></span></a>
      <nav data-nav-host aria-label="Sections"></nav>
      <div class="sidebar-foot"><button class="theme-toggle" type="button" data-theme-toggle></button><p>Runs only on this computer.</p></div>
    </aside>
    <div class="scrim" data-scrim></div>
    <main class="main" id="main-content" tabindex="-1"><div class="main-inner" data-root></div></main>
  </div>`;
  const shell = app.querySelector('.shell'), menu = app.querySelector('[data-menu]');
  app.querySelectorAll('[data-theme-toggle]').forEach(b => b.addEventListener('click', toggleTheme));
  applyTheme(document.documentElement.dataset.theme || state.boot?.settings?.theme);       // gives the switch its label
  // The sidebar can be folded down to a thin strip to give the page the full width; remembered in this browser.
  const SIDE = 'derive-sidebar-hidden', fold = app.querySelector('[data-side-toggle]');
  const setHidden = (hidden, keep = true) => {
    shell.classList.toggle('side-hidden', hidden);
    fold.textContent = hidden ? '»' : '«';
    fold.title = `${hidden ? 'Show' : 'Hide'} the sidebar (${MOD}\\)`; fold.setAttribute('aria-label', hidden ? 'Show the sidebar' : 'Hide the sidebar'); fold.setAttribute('aria-expanded', String(!hidden));
    if (keep) { try { localStorage.setItem(SIDE, hidden ? '1' : '0'); } catch { /* the choice just does not persist */ } window.dispatchEvent(new Event('resize')); }
  };
  let hiddenAtStart = false; try { hiddenAtStart = localStorage.getItem(SIDE) === '1'; } catch { /* shown */ }
  setHidden(hiddenAtStart, false);
  fold.addEventListener('click', () => setHidden(!shell.classList.contains('side-hidden')));
  document.addEventListener('keydown', event => { if ((event.metaKey || event.ctrlKey) && !event.altKey && event.key === '\\') { event.preventDefault(); setHidden(!shell.classList.contains('side-hidden')); } });
  const setOpen = open => { shell.classList.toggle('nav-open', open); menu.setAttribute('aria-expanded', String(open)); };
  menu.addEventListener('click', () => setOpen(!shell.classList.contains('nav-open')));
  app.querySelector('[data-scrim]').addEventListener('click', () => setOpen(false));
  app.querySelector('.sidebar').addEventListener('click', event => { if (event.target.closest('a')) setOpen(false); });
  document.addEventListener('keydown', event => { if (event.key === 'Escape') setOpen(false); });
}

/* ---------- What every page is handed ---------- */
async function sync() { state.boot = await api('/bootstrap'); paintNav(); return state.boot; }
function navigate(hash) { const target = hash.startsWith('#') ? hash : '#' + hash; if (location.hash === target) route(); else location.hash = target; }
/* ---------- Stars ----------
   Any page can drop in star(kind, ref). Pages rebuild their HTML often, so one listener on the document serves every button. */
export const star = (kind, ref) => { const key = kind + ':' + ref, on = state.boot?.stars?.includes(key);
  return `<button class="star-btn ${on ? 'is-on' : ''}" type="button" data-star="${escape(key)}" aria-pressed="${on ? 'true' : 'false'}" title="${on ? 'Starred for revision: click to remove' : 'Star for revision'}" aria-label="Star for revision">${icon('star')}</button>`; };
document.addEventListener('click', async event => {
  const button = event.target.closest?.('[data-star]');
  if (!button) return;
  event.preventDefault();                          // a star inside a fold-out heading must not fold it
  const key = button.dataset.star, cut = key.indexOf(':');
  try {
    const r = await post('/star', {kind: key.slice(0, cut), ref: key.slice(cut + 1)});
    if (state.boot) state.boot.stars = r.stars;
    document.querySelectorAll('[data-star]').forEach(b => { if (b.dataset.star !== key) return; b.classList.toggle('is-on', r.on); b.setAttribute('aria-pressed', r.on ? 'true' : 'false'); b.title = r.on ? 'Starred for revision: click to remove' : 'Star for revision'; });
    paintNav();
    toast(r.on ? 'Starred. It is on the Revise page.' : 'Star removed.');
    document.dispatchEvent(new CustomEvent('derive-star'));
  } catch (error) { toast(error.message, 'error'); }
});

const ctx = {
  get root() { return state.root; },
  get boot() { return state.boot; },
  api, post, waitFor, escape, icon, inline, markdown, toast, dialog, navigate, sync, star,
  onCleanup: fn => state.cleanups.push(fn),
};

async function route() {
  const token = ++state.token;
  for (const fn of state.cleanups.splice(0)) { try { fn(); } catch { /* a page's cleanup must never block navigation */ } }
  const [name = '', ...rest] = location.hash.replace(/^#\/?/, '').split('/').map(part => { try { return decodeURIComponent(part); } catch { return part; } });
  // Each visit paints into a fresh node, so a slow earlier page cannot overwrite this one.
  const root = document.createElement('div');
  root.className = 'main-inner';
  root.setAttribute('data-root', '');
  root.innerHTML = '<div class="loading-block" role="status"><span class="spinner"></span>Opening…</div>';
  document.querySelector('[data-root]').replaceWith(root);
  state.root = root;
  paintNav();
  window.scrollTo(0, 0);
  try {
    await sync();
    if (token !== state.token) return;
    if (name === '') await renderMap(ctx);
    else if (name === 'derive') {
      // "Derive" goes to the chain in progress, or the next one that is open.
      if (state.boot.next_chain) return navigate('#/chain/' + state.boot.next_chain);
      await renderMap(ctx, {notice: 'Every chain written so far is derived. More are on the way; the problems are waiting.'});
    }
    else if (name === 'chain' && rest[0]) await renderChain(ctx, rest[0]);
    else if (name === 'solve') await renderSolve(ctx);
    else if (name === 'problem' && rest[0]) await renderProblem(ctx, rest[0]);
    else if (name === 'puzzles') await renderPuzzles(ctx, rest[0] || '');
    else if (name === 'tools') await renderTools(ctx);
    else if (name === 'notebook') await renderNotebook(ctx);
    else if (name === 'recognise') await renderRecognise(ctx);
    else if (name === 'cses') await renderCses(ctx);
    else if (name === 'tool' && rest[0]) await renderTool(ctx, rest[0]);
    else if (name === 'code') await renderTasks(ctx);
    else if (name === 'task' && rest[0]) await renderTask(ctx, rest[0]);
    else if (name === 'break') await (rest[0] ? renderBreak(ctx, rest[0]) : renderBreaks(ctx));
    else if (name === 'contest') await renderContest(ctx);
    else if (name === 'revise') await renderRevise(ctx);
    else if (name === 'mastery') await renderMastery(ctx);
    else if (name === 'settings') await renderSettings(ctx);
    else root.innerHTML = '<section class="surface empty-state"><h1>Nothing lives at this address</h1><a class="btn btn-primary" href="#/">Back to the map</a></section>';
  } catch (error) {
    if (token !== state.token) return;
    root.innerHTML = `<section class="surface"><h1>This page needs another try</h1><p class="inline-error" role="alert">${escape(error.message)}</p><p style="margin-top:1rem"><button class="btn btn-primary" data-retry>Try again</button> <a class="btn btn-secondary" href="#/">The map</a></p></section>`;
    root.querySelector('[data-retry]').addEventListener('click', route);
  }
  if (token === state.token) document.title = (root.querySelector('h1')?.textContent?.trim() || 'The map') + ' · derive';
}

async function boot() {
  try { state.boot = await api('/bootstrap'); }
  catch (error) {
    document.getElementById('app').innerHTML = `<div class="boot-state"><p class="inline-error" role="alert">${escape(error.message)}</p><button class="btn btn-primary" data-reload>Reload</button></div>`;
    document.querySelector('[data-reload]').addEventListener('click', () => location.reload());
    return;
  }
  applyTheme(state.boot.settings.theme);
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => applyTheme(state.boot.settings.theme));
  buildShell();
  document.querySelector('.skip-link')?.addEventListener('click', event => { event.preventDefault(); document.getElementById('main-content')?.focus(); });
  window.addEventListener('hashchange', route);
  await route();
}
boot();
