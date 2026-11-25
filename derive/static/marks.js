/* Two marks, used on the map and in the toolbox.
   Standard: a named technique or result everyone at a regional is assumed to know, so not knowing it costs a problem.
   Common: it turns up often in recent rounds. Something can carry both. The marks are the author's judgement. */
export const MARKS = {
  standard: {symbol: '★', label: 'Standard', cls: 'mark-standard', meaning: 'everyone at a regional is assumed to know it'},
  common: {symbol: '◆', label: 'Common', cls: 'mark-common', meaning: 'turns up often in recent rounds'},
};
export const marks = (list, e) => (list || []).filter(m => MARKS[m]).map(m => `<span class="mark ${MARKS[m].cls}" title="${e(MARKS[m].label + ': ' + MARKS[m].meaning)}"><span aria-hidden="true">${MARKS[m].symbol}</span> ${MARKS[m].label}</span>`).join(' ');
export const symbols = list => (list || []).filter(m => MARKS[m]).map(m => `<span class="sym-${m}">${MARKS[m].symbol}</span>`).join('');
export const legend = e => `<p class="mark-legend">${Object.keys(MARKS).map(k => `<span>${marks([k], e)} <span class="muted small">${e(MARKS[k].meaning)}</span></span>`).join('')}</p>`;
