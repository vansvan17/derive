"""A tutor on request: prompts for ChatGPT, and optionally Codex run from the app.

The app itself only asks questions and checks answers. Wherever the learner is,
she can ask for a tutor. One prompt is built here for that exact spot, and it
goes out in one of two ways:

  - copied to the clipboard, to paste into ChatGPT (always available);
  - run through the `codex` command on this Mac, with the reply shown in the app
    (only when switched on in Settings).

Two modes, and the difference matters:

  SOCRATIC  the step or problem is not finished. The prompt never contains the
            stored answer, the name of the result, or the observations, because
            the learner can read whatever is on her clipboard. The tutor is told
            to lead with questions and not to give the answer away.
  EXPLAIN   the chain is derived, or the problem is solved or given up. Now the
            name, the statement and the observations are included, and the
            tutor is asked to teach it in full.
"""
from __future__ import annotations
import shutil
import subprocess
import tempfile
from pathlib import Path
import json
import threading
import time

TIMEOUT = 240

SOCRATIC = '''You are tutoring one student in competitive programming. She is working through a guided derivation and learns best by producing each step herself.

Rules for this conversation:
- Do NOT state the answer to the question she is on, in any form (not as a number, a formula, a choice, or "it turns out that...").
- Do NOT name the theorem, technique or algorithm this is leading to, even if you recognise it. She is meant to discover it before she hears its name.
- Find out what she understands first: ask her to explain what the question is asking, or to try the smallest case.
- Then lead with one small question at a time. Wait for her reply before the next one.
- If she is missing background (a definition, a notation, how to do a small computation), teach that background plainly with a different example from the one in the question.
- If she proposes an answer, do not just say right or wrong: ask her to justify it, and let her find a mistake herself. The app will check the final answer.
- Be warm and brief. No lectures.'''

SOCRATIC_PROBLEM = '''You are tutoring one student in competitive programming. She is solving a real contest problem; if she wrote down an approach, it is below. She learns from finding the key observations herself.

Rules for this conversation:
- Do NOT give the solution, the key observation, or the name of the technique. Do not write code for the solution.
- Start from HER approach: say what is sound in it, then ask a question that exposes the first gap or the first case it gets wrong. If she wrote none, first ask what she has tried.
- Suggest concrete small inputs for her to work by hand when that would show her something.
- One question at a time; wait for her reply.
- If she is missing background knowledge, teach that background plainly on a different example.
- If she reaches a complete correct idea, tell her so and help her check edge cases and complexity, then let her implement it herself.
- If the statement is not included below and you cannot open the link, your first message should ask her to paste the statement. Do not guess it.'''

EXPLAIN = '''You are tutoring one student in competitive programming. She has just finished the material below by herself, so nothing needs to be hidden any more. Teach it properly:

1. The intuition in plain words, then the precise statement.
2. Why it is true: a complete, careful proof or argument, with a small worked example.
3. How to recognise it in a contest problem: the phrases and structures that should make her think of it.
4. The usual mistakes and edge cases, and the complexity.
5. Two or three follow-up exercises of increasing difficulty, without solutions, and offer to check her answers.

Write like a good teacher talking to one student, not like a reference page. Ask her a question at the end of each part to check she is with you, and adapt to her replies.'''


def _steps_so_far(done_steps):
    lines = []
    for number, (prompt, answer, showed) in enumerate(done_steps, 1):
        lines.append(f'{number}. Q: {prompt}\n   Her answer: {answer}\n   What that showed: {showed}')
    return '\n'.join(lines) if lines else '(none yet: this is the first question)'


def chain_step(opening, done_steps, step, options, nudges_seen, question):
    """Socratic prompt for the step she is on. Holds nothing she has not already been shown."""
    parts = [SOCRATIC, '', 'THE DERIVATION SO FAR', f'Opening: {opening}', _steps_so_far(done_steps), '',
             'THE QUESTION SHE IS ON NOW', step['prompt']]
    if options:
        parts += ['Options: ' + ' | '.join(options)]
    if nudges_seen:
        parts += ['', 'Smaller questions the app has already asked her:'] + [f'- {n}' for n in nudges_seen]
    parts += ['', 'WHAT SHE SAYS', question or '(She did not say what is confusing. Start by asking her.)']
    return '\n'.join(parts)


def chain_full(name, statement, remark, steps):
    """Explain prompt for a chain she has finished."""
    walked = '\n'.join(f'{i}. {s["prompt"]}\n   -> {s["showed"]}' for i, s in enumerate(steps, 1))
    return '\n'.join([EXPLAIN, '', 'WHAT SHE DERIVED', f'Name: {name}', f'Statement: {statement}', f'Remark: {remark}' if remark else '',
                      '', 'THE QUESTIONS THAT LED HER THERE', walked])


def problem_stuck(problem, approach, cue, nudges_seen, question):
    """Socratic prompt for a problem in progress. No observations, no idea names."""
    parts = [SOCRATIC_PROBLEM, '', 'THE PROBLEM', f'{problem["title"]} ({problem["site"]}, rated {problem["rating"]})', problem['url'], '',
             'HER APPROACH, written before any help', approach or '(she did not write one down)', '', 'What in the statement suggested it to her', cue or '(not said)']
    if nudges_seen:
        parts += ['', 'Smaller questions the app has already asked her:'] + [f'- {n}' for n in nudges_seen]
    parts += ['', 'WHAT SHE SAYS', question or '(She did not say where she is stuck. Start by asking her.)']
    return '\n'.join(parts)


SOCRATIC_TASK = '''You are tutoring one student in competitive programming. She is writing a program for the task below and it is not accepted yet. She learns from finding the idea and the bug herself.

Rules for this conversation:
- Do NOT give the solution, the key observation, or the name of the technique. Do NOT write or rewrite her code.
- Read her code and what the judge said. If the idea is wrong, ask a question about a small input where it fails; let her run it by hand. If the idea is right and the code is wrong, point at the region to look at with a question, not at the fix.
- If she has no idea yet, ask her to work the two smallest cases by hand and tell you the answers.
- One question at a time; wait for her reply. Be warm and brief.
- If she is missing background knowledge, teach that background plainly on a different example.'''


def task_stuck(task, code, verdicts, hints_seen, question):
    """Socratic prompt for a task in progress: the statement, her code and what the judge said. No hints she has not opened."""
    parts = [SOCRATIC_TASK, '', 'THE TASK', task['title'], task['statement'], '', 'Example input and output:']
    parts += [f'{s[0].rstrip()}\n->\n{s[1].rstrip()}' for s in task['samples'][:2]]
    parts += ['', 'HER CODE RIGHT NOW', code.strip() or '(nothing written yet)', '', 'WHAT THE JUDGE HAS SAID, oldest first', ', '.join(verdicts) or '(nothing judged yet)']
    if hints_seen:
        parts += ['', 'Hints the app has already shown her:'] + [f'- {h}' for h in hints_seen]
    parts += ['', 'WHAT SHE SAYS', question or '(She did not say where she is stuck. Start by asking her.)']
    return '\n'.join(parts)


def task_full(task, code):
    """Explain prompt for a task she has had accepted."""
    return '\n'.join([EXPLAIN.replace('She has just finished the material below by herself', 'Her program for the task below has just been accepted'),
                      '', 'THE TASK', task['title'], task['statement'], '', 'THE HINTS THE APP HOLDS FOR IT'] + [f'- {h}' for h in task['hints']]
                     + ['', 'HER ACCEPTED CODE', code.strip(), '', 'Also review her code: what is good, what a cleaner version would look like, and what habit would have got her there faster.'])


def problem_full(problem, approach, observations, idea_names, solved):
    """Explain prompt for a problem that is solved or given up."""
    parts = [EXPLAIN.replace('She has just finished the material below by herself', 'She has just ' + ('solved' if solved else 'given up on') + ' the problem below'),
             '', 'THE PROBLEM', f'{problem["title"]} ({problem["site"]}, rated {problem["rating"]})', problem['url'],
             'Editorial: ' + problem['editorial'] if problem.get('editorial') else '', '',
             'HER FIRST APPROACH', approach or '(none)', '', 'THE OBSERVATIONS THAT CRACK IT'] + [f'- {o}' for o in observations]
    if idea_names:
        parts += ['', 'General ideas behind it that she already knows by name: ' + ', '.join(idea_names)]
    parts += ['', 'Also compare her first approach with the real solution: what she had right, and the exact point where it needed something more.',
              'If you can open the links, read the statement there; otherwise ask her to paste it.']
    return '\n'.join(parts)


def with_thread(prompt, turns):
    """Add the conversation so far (pairs of is_tutor, text). Each Codex call is separate, so the history is resent."""
    if not turns:
        return prompt
    lines = ['', 'THE CONVERSATION SO FAR (continue it; reply only with your next message to her)']
    lines += [('You said: ' if is_tutor else 'She said: ') + said for is_tutor, said in turns]
    return prompt + '\n' + '\n'.join(lines)


def available():
    return shutil.which('codex') is not None


def teach(prompt, run=subprocess.run, effort=None):
    """Run Codex once on the prompt. Returns {'status': 'ok', 'reply': ...} or {'status': 'unavailable', 'reason': ...}.

    Codex can run commands, so it is started in an empty temporary folder with a
    read-only sandbox, and its session is not kept.
    """
    if not available():
        return {'status': 'unavailable', 'reason': 'The codex command is not installed on this computer.'}
    with tempfile.TemporaryDirectory(prefix='derive-tutor-') as empty:
        out = Path(empty) / 'reply.txt'
        # A conversation wants a quick reply more than a deep one, so it asks for less thinking than the user's own setting.
        quick = ['-c', f'model_reasoning_effort="{effort}"'] if effort else []
        command = ['codex', 'exec', '--skip-git-repo-check', '--sandbox', 'read-only', '--ephemeral', '--color', 'never', *quick,
                   '-C', empty, '-o', str(out), '-']
        try:
            done = run(command, input=prompt, capture_output=True, text=True, timeout=TIMEOUT, cwd=empty)
        except subprocess.TimeoutExpired:
            return {'status': 'unavailable', 'reason': 'The tutor took too long. The prompt can still be copied into ChatGPT.'}
        except OSError as exc:
            return {'status': 'unavailable', 'reason': f'Could not start Codex: {exc}.'}
        reply = out.read_text().strip() if out.exists() else ''
    if done.returncode != 0 or not reply:
        tail = (done.stderr or done.stdout or '').strip().splitlines()[-1:] or ['']
        hint = ' It may have reached its usage limit.' if 'limit' in ' '.join(tail).lower() else ''
        return {'status': 'unavailable', 'reason': f'Codex did not answer.{hint} The prompt can still be copied into ChatGPT.'}
    return {'status': 'ok', 'reply': reply[:20000]}


class Stream:
    """One Codex process kept running for the conversation of a sitting, so that a reply starts at once and can be
    shown while it is being written.

    It speaks the app-server protocol (`codex app-server`, JSON lines on its standard input and output): a thread is
    started for each message, in an empty temporary folder, read-only, with nothing ever approved, and not kept.
    Anything that goes wrong (the command is missing, the protocol changed, it stops answering) makes `teach` fall
    back to the plain one-shot call above, so the tutor still answers, only later and all at once.
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.process = None
        self.folder = None
        self.count = 0

    def _send(self, method, params=None, note=False):
        message = {'method': method}
        if params is not None:
            message['params'] = params
        if not note:
            self.count += 1
            message['id'] = self.count
        self.process.stdin.write(json.dumps(message) + '\n')
        self.process.stdin.flush()
        return self.count

    def _read(self, deadline):
        """The next message from Codex, or None at the deadline or if it has gone away."""
        while time.time() < deadline:
            line = self.process.stdout.readline()
            if not line:
                return None
            try:
                return json.loads(line)
            except ValueError:
                continue
        return None

    def _answer(self, wanted, deadline):
        while True:
            message = self._read(deadline)
            if message is None or (message.get('id') == wanted and 'method' not in message):
                return message

    def _start(self):
        self.folder = tempfile.TemporaryDirectory(prefix='derive-tutor-')
        self.process = subprocess.Popen(['codex', 'app-server'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                        text=True, cwd=self.folder.name)
        self.count = 0
        ready = self._answer(self._send('initialize', {'clientInfo': {'name': 'derive', 'title': 'derive', 'version': '1'}, 'capabilities': None}), time.time() + 30)
        if not ready or ready.get('error'):
            raise OSError('Codex did not start.')
        self._send('initialized', note=True)

    def close(self):
        with self.lock:
            self._stop()

    def _stop(self):
        if self.process:
            try:
                self.process.terminate()
            except OSError:
                pass
        if self.folder:
            self.folder.cleanup()
        self.process = self.folder = None

    def teach(self, prompt, on_piece=None):
        """Like teach(): {'status': 'ok', 'reply': ...} or unavailable. `on_piece(text so far)` is called as the reply grows."""
        if not available():
            return {'status': 'unavailable', 'reason': 'The codex command is not installed on this computer.'}
        with self.lock:
            try:
                if not self.process or self.process.poll() is not None:
                    self._stop()
                    self._start()
                deadline = time.time() + TIMEOUT
                made = self._answer(self._send('thread/start', {'cwd': self.folder.name, 'approvalPolicy': 'never', 'sandbox': 'read-only', 'ephemeral': True}), deadline)
                thread = made['result']['thread']['id']
                turn = self._send('turn/start', {'threadId': thread, 'input': [{'type': 'text', 'text': prompt, 'text_elements': []}]})
                reply, final = '', None
                while True:
                    message = self._read(deadline)
                    if message is None:
                        raise OSError('Codex stopped answering.')
                    if message.get('id') == turn and message.get('error'):
                        raise OSError(str(message['error'].get('message', 'Codex refused the message.')))
                    if 'id' in message and 'method' in message:          # it asks for something (an approval): the answer is always no
                        self.process.stdin.write(json.dumps({'id': message['id'], 'error': {'code': -32601, 'message': 'not available'}}) + '\n')
                        self.process.stdin.flush()
                        continue
                    params = message.get('params') or {}
                    if params.get('threadId') not in (None, thread):
                        continue
                    if message.get('method') == 'item/agentMessage/delta':
                        reply += params.get('delta', '')
                        if on_piece:
                            on_piece(reply)
                    elif message.get('method') == 'item/completed' and (params.get('item') or {}).get('type') == 'agentMessage':
                        final = params['item'].get('text') or final
                    elif message.get('method') == 'turn/completed':
                        break
                reply = (final or reply).strip()
                if reply:
                    return {'status': 'ok', 'reply': reply[:20000]}
            except (OSError, KeyError, TypeError, ValueError):
                self._stop()
        return teach(prompt)                                             # the slow, sure way
