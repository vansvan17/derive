/* The team notebook: the code you wrote yourself for the Toolbox pages, laid out to print.
   Only your own accepted code goes in. "Print" opens the browser's print box, where "Save as PDF" makes the file. */
import {marks} from './marks.js';

const KEY = 'derive-notebook';
const load = () => { try { return JSON.parse(localStorage.getItem(KEY)) || {}; } catch { return {}; } };
const keep = value => { try { localStorage.setItem(KEY, JSON.stringify(value)); } catch { /* the choices just do not persist */ } };

export async function renderNotebook(ctx) {
  const {api, post, escape: e, toast} = ctx;
  const root = ctx.root;
  const page = await api('/notebook');
  if (ctx.root !== root) return;
  const opt = {when: true, traps: false, compact: true, columns: 2, size: 8, skip: [], ...load()};
  const ready = page.entries.filter(x => x.code), missing = page.entries.filter(x => !x.code);
  let title = page.title, extra = page.extra, timer = null;
  const included = () => ready.filter(x => !opt.skip.includes(x.id));
  // Paper is narrow: optionally drop the two lines every C++ file starts with and halve the indentation, so fewer lines wrap.
  const shown = code => {
    let lines = code.replace(/\s+$/, '').split('\n');
    if (opt.compact) {
      lines = lines.filter(l => !/^\s*(#include\s*<bits\/stdc\+\+\.h>|using namespace std;)\s*$/.test(l)).map(l => l.replace(/^( +)/, m => ' '.repeat(Math.ceil(m.length / 2))).replace(/^\t+/, m => '  '.repeat(m.length)).replace(/ {3,}\/\//, '  //'));
      while (lines.length && !lines[0].trim()) lines.shift();
    }
    return lines.join('\n');
  };

  const sheet = () => `<div class="notebook-sheet" style="--nb-columns:${opt.columns};--nb-size:${opt.size}pt">
      <h1 class="nb-title">${e(title || 'Team notebook')}</h1>
      ${included().map(x => `<section class="nb-entry"><h2>${e(x.title)}</h2>
        ${opt.when ? `<p class="nb-note"><strong>When:</strong> ${e(x.when.join('; '))}</p>` : ''}
        ${opt.traps ? `<p class="nb-note"><strong>Traps:</strong> ${e(x.traps.join(' '))}</p>` : ''}
        <pre>${e(shown(x.code))}</pre></section>`).join('')}
      ${extra.trim() ? `<section class="nb-entry"><h2>Notes</h2><pre>${e(extra.replace(/\s+$/, ''))}</pre></section>` : ''}</div>`;

  function paint() {
    const lines = included().reduce((a, x) => a + x.code.split('\n').length, 0);
    root.innerHTML = `<div class="notebook-controls"><header class="page-head"><div><p class="eyebrow"><a href="#/tools">Toolbox</a></p><h1>Team notebook</h1>
        <p class="muted">The code you wrote yourself for the Toolbox pages, laid out for paper. Only your own accepted code goes in: ${ready.length} of ${page.entries.length} pages are written. Check your contest's rules for how many pages a team may bring.</p></div>
        <div><button class="btn btn-primary" type="button" data-print ${included().length || extra.trim() ? '' : 'disabled'}>Print or save as PDF</button></div></header>
      <section class="surface"><div class="form-grid">
          <label class="field">Title on the first page<input type="text" data-title maxlength="120" value="${e(title)}" placeholder="Team notebook"></label>
          <label class="field">Columns<select data-columns>${[1, 2, 3].map(n => `<option ${opt.columns === n ? 'selected' : ''}>${n}</option>`).join('')}</select></label>
          <label class="field">Code size (points)<select data-size>${[6, 7, 8, 9, 10].map(n => `<option ${opt.size === n ? 'selected' : ''}>${n}</option>`).join('')}</select></label></div>
        <p class="nb-options"><label class="choice-inline"><input type="checkbox" data-when ${opt.when ? 'checked' : ''}> the "reach for it when" line</label> <label class="choice-inline"><input type="checkbox" data-traps ${opt.traps ? 'checked' : ''}> the traps</label> <label class="choice-inline"><input type="checkbox" data-compact ${opt.compact ? 'checked' : ''}> save width: half indentation, no include lines</label></p>
        <h2>What goes in</h2>
        ${ready.length ? `<ul class="nb-pick">${ready.map(x => `<li><label><input type="checkbox" data-pick="${e(x.id)}" ${opt.skip.includes(x.id) ? '' : 'checked'}> ${e(x.title)}</label> ${marks(x.marks, e)} <span class="muted small">${x.language === 'python' ? 'Python' : 'C++'} · ${x.code.split('\n').length} lines${x.judged ? '' : ' · accepted earlier; this is the code now saved in the editor, not re-judged'}</span></li>`).join('')}</ul>` : '<p class="muted">Nothing yet. A page goes in once your own program for it is accepted.</p>'}
        ${missing.length ? `<details><summary class="muted small">${missing.length} Toolbox page${missing.length === 1 ? '' : 's'} not written yet</summary><ul class="nb-pick">${missing.map(x => `<li><a href="#/tool/${e(x.id)}">${e(x.title)}</a> ${marks(x.marks, e)}</li>`).join('')}</ul></details>` : ''}
        <label class="field">Your own notes, printed at the end (formulas, reminders, compile command)<textarea data-extra rows="5" spellcheck="false">${e(extra)}</textarea></label>
        <p class="muted small" data-saved role="status">${included().length} pages chosen · about ${lines} lines of code.</p></section>
      <h2 class="nb-preview-head">As it will print</h2></div>
      <div data-sheet>${sheet()}</div>`;
    const $ = s => root.querySelector(s);
    const again = () => { keep(opt); paint(); };
    $('[data-print]').addEventListener('click', () => window.print());
    $('[data-columns]').addEventListener('change', event => { opt.columns = Number(event.target.value); again(); });
    $('[data-size]').addEventListener('change', event => { opt.size = Number(event.target.value); again(); });
    $('[data-when]').addEventListener('change', event => { opt.when = event.target.checked; again(); });
    $('[data-traps]').addEventListener('change', event => { opt.traps = event.target.checked; again(); });
    $('[data-compact]').addEventListener('change', event => { opt.compact = event.target.checked; again(); });
    root.querySelectorAll('[data-pick]').forEach(box => box.addEventListener('change', () => { opt.skip = box.checked ? opt.skip.filter(id => id !== box.dataset.pick) : [...opt.skip, box.dataset.pick]; again(); }));
    // The title and the notes are saved with the record (not just in this browser), a moment after typing stops.
    const typed = () => {
      title = $('[data-title]').value; extra = $('[data-extra]').value;
      $('[data-sheet]').innerHTML = sheet();
      $('[data-print]').disabled = !(included().length || extra.trim());
      clearTimeout(timer);
      timer = setTimeout(async () => { try { await post('/notebook', {title, extra}); } catch (error) { toast('Not saved: ' + error.message, 'error'); } }, 700);
    };
    $('[data-title]').addEventListener('input', typed);
    $('[data-extra]').addEventListener('input', typed);
  }
  ctx.onCleanup(() => { if (timer) { clearTimeout(timer); post('/notebook', {title, extra}).catch(() => {}); } });
  paint();
}
