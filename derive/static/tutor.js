/* Ask a tutor from wherever you are. The server builds one prompt for this exact spot.
   It is copied for ChatGPT, or, when the in-app tutor is on in Settings, sent to Codex
   and the reply is shown here. While a step or problem is unfinished the tutor is told
   to lead with questions and not to give the answer. */

/* where: {scope: 'chain', idea, step?} or {scope: 'problem', id}
   options.unfinished: the step or problem is still open (the tutor will only ask questions)
   options.warn: a sentence to confirm first, when asking has a consequence */
export async function askTutor(ctx, where, {unfinished = false, warn = ''} = {}) {
  const {post, waitFor, escape: e, markdown, toast, dialog} = ctx;
  const inApp = ctx.boot.settings.tutor === 'codex';
  let question = '';
  if (unfinished) {
    const typed = await dialog({
      title: 'Ask a tutor', wide: true,
      body: (warn ? warn + ' ' : '') + 'The tutor sees what you have done so far and will lead you with questions. It is told not to give the answer.',
      input: {label: where.scope === 'problem' && inApp ? 'Where are you stuck? (You can paste the statement too, in case the tutor cannot open the link.)' : 'What is confusing you? (optional)', placeholder: 'I do not see why…', rows: where.scope === 'problem' && inApp ? 5 : 3},
      confirm: inApp ? 'Ask Codex' : 'Get the prompt for ChatGPT',
    });
    if (typed === false) return false;
    question = typed === true ? '' : typed;
  }
  const body = {...where, question};
  try {
    if (inApp) {
      // A conversation: every Codex call is separate, so the turns so far are sent back each time.
      const thread = [];
      let result = null;
      for (;;) {
        toast('Asking the tutor. This can take a minute.', 'info');
        const {job} = await post('/tutor/ask', {...body, thread});
        result = (await waitFor(job))?.result;
        if (result?.status !== 'ok') break;
        thread.push({who: 'tutor', text: result.reply});
        const history = thread.map(t => `<div class="tutor-turn ${t.who === 'tutor' ? 'is-tutor' : 'is-me'}"><p class="eyebrow">${t.who === 'tutor' ? 'Tutor' : 'You'}</p>${markdown(t.text)}</div>`).join('');
        const reply = await dialog({title: 'The tutor', wide: true, html: `<div class="tutor-thread">${history}</div>`, input: {label: 'Your reply', placeholder: 'Answer the tutor, or ask something else…', rows: 3}, confirm: 'Reply', cancel: 'Close'});
        if (reply === false || reply === true) return true;
        thread.push({who: 'me', text: reply});
      }
      toast(result?.reason || result?.error || 'The tutor did not answer.', 'error');
      if (result?.status === 'withheld' || thread.length) return true;
      // Codex could not answer at all: fall through to the prompt for ChatGPT.
    }
    const {prompt} = await post('/tutor/prompt', body);
    let copied = false;
    try { await navigator.clipboard.writeText(prompt); copied = true; } catch { /* shown below instead */ }
    await dialog({
      title: copied ? 'Prompt copied' : 'Copy this prompt', wide: true,
      body: copied ? 'Paste it into ChatGPT (or any assistant) and carry on the conversation there.' : 'Select the text below, copy it, and paste it into ChatGPT.',
      html: `<p><a href="https://chatgpt.com/" target="_blank" rel="noopener noreferrer">Open ChatGPT</a></p><details ${copied ? '' : 'open'}><summary class="muted">Show the prompt</summary><pre class="tutor-prompt">${e(prompt)}</pre></details>`,
      confirm: 'Done', cancel: '',
    });
    return true;
  } catch (error) { toast(error.message, 'error'); return false; }
}
