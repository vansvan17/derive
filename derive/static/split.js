/* Split view: the text (statement, questions, help) on one side and the editor on the other, each
   scrolling on its own. Which side the editor is on is the reader's choice, remembered in this browser. */
const KEY = 'derive-editor-side';
export function editorSide() { try { return localStorage.getItem(KEY) === 'left' ? 'left' : 'right'; } catch { return 'right'; } }
export const sideButton = () => `<button class="btn btn-ghost btn-sm side-btn" type="button" data-side title="Move the editor to the other side"></button>`;
/* Applies the remembered side to a .split element and makes its [data-side] button swap it. */
export function wireSplit(split) {
  if (!split) return;
  const button = split.querySelector('[data-side]');
  const paint = () => {
    const side = editorSide();
    split.classList.toggle('editor-left', side === 'left');
    if (button) button.textContent = side === 'left' ? 'Editor → right' : 'Editor ← left';
  };
  paint();
  button?.addEventListener('click', () => {
    try { localStorage.setItem(KEY, editorSide() === 'left' ? 'right' : 'left'); } catch { /* the choice just does not persist */ }
    document.querySelectorAll('.split').forEach(s => s.classList.toggle('editor-left', editorSide() === 'left'));
    paint();
  });
}
