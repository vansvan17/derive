/* Split view: the text (statement, questions, help) and the editor, side by side or stacked.
   Where the editor goes (left, right, or below the text) is the reader's choice, remembered in this browser. */
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
function apply(split) {
  const side = editorSide();
  split.classList.toggle('editor-left', side === 'left');
  split.classList.toggle('editor-below', side === 'below');
  split.querySelectorAll('[data-side-set]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.sideSet === side)));
  fit(split);
}
let listening = false;
/* Applies the remembered position to a .split element and wires its switch. */
export function wireSplit(split) {
  if (!split) return;
  apply(split);
  requestAnimationFrame(() => fit(split));                   // once more after the page above it has laid out
  split.querySelectorAll('[data-side-set]').forEach(b => b.addEventListener('click', () => {
    try { localStorage.setItem(KEY, b.dataset.sideSet); } catch { /* the choice just does not persist */ }
    document.querySelectorAll('.split').forEach(apply);
  }));
  if (!listening) { listening = true; window.addEventListener('resize', () => document.querySelectorAll('.split').forEach(fit)); }
}
