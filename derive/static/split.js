/* Split view: the text (statement, questions, help) and the editor, side by side or stacked.
   Where the editor goes (left, right, or below the text) is the reader's choice, remembered in this browser,
   and so is how much room it gets: drag the bar between the panes, or the grip under the editor when it is below. */
const KEY = 'derive-editor-side';
const SIDES = [['left', 'Left'], ['right', 'Right'], ['below', 'Below']];
export function editorSide() { try { const v = localStorage.getItem(KEY); return SIDES.some(s => s[0] === v) ? v : 'right'; } catch { return 'right'; } }
export const sideButton = () => `<span class="side-switch" role="group" aria-label="Where the editor goes" data-side>${SIDES.map(([k, label]) => `<button type="button" data-side-set="${k}" title="Editor ${k === 'below' ? 'below the text' : 'on the ' + k}">${label}</button>`).join('')}</span>`;

/* Side by side, the split fills the window from where it starts to the bottom, so both panes end level.
   If it starts far down the page (a coding step at the end of a chain) it takes a full window height instead. */
function fit(split) {
  if (split.classList.contains('editor-below')) { split.style.removeProperty('--split-height'); return; }
  const top = split.getBoundingClientRect().top + window.scrollY, view = window.innerHeight;
  const room = top < view * 0.45 ? view - top - 24 : view - 32;
  split.style.setProperty('--split-height', Math.max(480, Math.round(room)) + 'px');
}
/* How wide the code pane is (side by side) and how tall the editor is (below the text): dragged, remembered in this browser. */
const SHARE = 'derive-code-share', HEIGHT = 'derive-editor-height';
const LIMITS = {[SHARE]: [25, 78, 50], [HEIGHT]: [12, 90, 28]};
const clamp = (key, v) => Math.min(LIMITS[key][1], Math.max(LIMITS[key][0], v));
function read(key) { try { const v = Number(localStorage.getItem(key)); return v ? clamp(key, v) : LIMITS[key][2]; } catch { return LIMITS[key][2]; } }
function keep(key, v) { try { v == null ? localStorage.removeItem(key) : localStorage.setItem(key, String(Math.round(v * 10) / 10)); } catch { /* the size just does not persist */ } }
function size(split, share = read(SHARE), height = read(HEIGHT)) {
  split.style.setProperty('--code-fr', share + 'fr');
  split.style.setProperty('--text-fr', (100 - share) + 'fr');
  split.style.setProperty('--handle-at', String((split.classList.contains('editor-left') ? share : 100 - share) / 100));
  split.style.setProperty('--editor-height', height + 'rem');
}
const sizeAll = (share, height) => document.querySelectorAll('.split').forEach(s => size(s, share, height));
/* A handle that follows the pointer while it is held, calls done() on release, and resets on a double click. */
function draggable(handle, move, done, reset) {
  handle.addEventListener('pointerdown', event => {
    event.preventDefault(); handle.setPointerCapture(event.pointerId); handle.classList.add('is-dragging');
    const onMove = e => move(e);
    const stop = () => { handle.removeEventListener('pointermove', onMove); handle.classList.remove('is-dragging'); done(); window.dispatchEvent(new Event('resize')); };
    handle.addEventListener('pointermove', onMove);
    handle.addEventListener('pointerup', stop, {once: true});
    handle.addEventListener('pointercancel', stop, {once: true});
  });
  handle.addEventListener('dblclick', () => { reset(); window.dispatchEvent(new Event('resize')); });
  handle.addEventListener('keydown', event => { const d = {ArrowLeft: -1, ArrowUp: -1, ArrowRight: 1, ArrowDown: 1}[event.key]; if (d) { event.preventDefault(); handle.dispatchEvent(new CustomEvent('nudge', {detail: d})); } });
}
function addHandles(split) {
  if (split.querySelector(':scope > .split-handle')) return;
  const bar = document.createElement('div');
  bar.className = 'split-handle'; bar.tabIndex = 0; bar.setAttribute('role', 'separator'); bar.setAttribute('aria-orientation', 'vertical');
  bar.title = 'Drag to make the code wider or narrower. Double-click to reset.'; bar.setAttribute('aria-label', 'Width of the code pane');
  split.append(bar);
  let share = read(SHARE);
  const set = v => { share = clamp(SHARE, v); sizeAll(share, undefined); };
  draggable(bar, e => { const r = split.getBoundingClientRect(), f = (e.clientX - r.left) / r.width * 100; set(split.classList.contains('editor-left') ? f : 100 - f); },
    () => keep(SHARE, share), () => { keep(SHARE, null); share = LIMITS[SHARE][2]; sizeAll(); });
  bar.addEventListener('nudge', e => { share = read(SHARE); set(share + (split.classList.contains('editor-left') ? 2 : -2) * e.detail); keep(SHARE, share); });
  const host = split.querySelector('.split-code .editor-host');
  if (!host) return;
  const grip = document.createElement('div');
  grip.className = 'editor-grip'; grip.tabIndex = 0; grip.setAttribute('role', 'separator'); grip.setAttribute('aria-orientation', 'horizontal');
  grip.title = 'Drag to make the editor taller or shorter. Double-click to reset.'; grip.setAttribute('aria-label', 'Height of the editor');
  host.after(grip);
  const rem = () => parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
  let height = read(HEIGHT);
  const setH = v => { height = clamp(HEIGHT, v); sizeAll(undefined, height); };
  draggable(grip, e => setH((e.clientY - host.getBoundingClientRect().top) / rem()), () => keep(HEIGHT, height), () => { keep(HEIGHT, null); height = LIMITS[HEIGHT][2]; sizeAll(); });
  grip.addEventListener('nudge', e => { height = read(HEIGHT); setH(height + 2 * e.detail); keep(HEIGHT, height); });
}
function apply(split) {
  const side = editorSide();
  split.classList.toggle('editor-left', side === 'left');
  split.classList.toggle('editor-below', side === 'below');
  size(split);
  split.querySelectorAll('[data-side-set]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.sideSet === side)));
  fit(split);
}
let listening = false;
/* Applies the remembered position to a .split element and wires its switch. */
export function wireSplit(split) {
  if (!split) return;
  addHandles(split);
  apply(split);
  requestAnimationFrame(() => fit(split));                   // once more after the page above it has laid out
  split.querySelectorAll('[data-side-set]').forEach(b => b.addEventListener('click', () => {
    try { localStorage.setItem(KEY, b.dataset.sideSet); } catch { /* the choice just does not persist */ }
    document.querySelectorAll('.split').forEach(apply);
  }));
  if (!listening) { listening = true; window.addEventListener('resize', () => document.querySelectorAll('.split').forEach(fit)); }
}
