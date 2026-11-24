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

SOCRATIC_PROBLEM = '''You are tutoring one student in competitive programming. She is solving a real contest problem and has written down her own approach. She learns from finding the key observations herself.

Rules for this conversation:
- Do NOT give the solution, the key observation, or the name of the technique. Do not write code for the solution.
- Start from HER approach: say what is sound in it, then ask a question that exposes the first gap or the first case it gets wrong.
- Suggest concrete small inputs for her to work by hand when that would show her something.
- One question at a time; wait for her reply.
- If she is missing background knowledge, teach that background plainly on a different example.
- If she reaches a complete correct idea, tell her so and help her check edge cases and complexity, then let her implement it herself.
- If you can open the link, read the statement there. If you cannot, ask her to paste it. Do not guess the statement.'''

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
             'HER APPROACH, written before any help', approach or '(none)', '', 'What in the statement suggested it to her', cue or '(not said)']
    if nudges_seen:
        parts += ['', 'Smaller questions the app has already asked her:'] + [f'- {n}' for n in nudges_seen]
    parts += ['', 'WHAT SHE SAYS', question or '(She did not say where she is stuck. Start by asking her.)']
    return '\n'.join(parts)


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


def available():
    return shutil.which('codex') is not None


def teach(prompt, run=subprocess.run):
    """Run Codex once on the prompt. Returns {'status': 'ok', 'reply': ...} or {'status': 'unavailable', 'reason': ...}.

    Codex can run commands, so it is started in an empty temporary folder with a
    read-only sandbox, and its session is not kept.
    """
    if not available():
        return {'status': 'unavailable', 'reason': 'The codex command is not installed on this computer.'}
    with tempfile.TemporaryDirectory(prefix='derive-tutor-') as empty:
        out = Path(empty) / 'reply.txt'
        command = ['codex', 'exec', '--skip-git-repo-check', '--sandbox', 'read-only', '--ephemeral', '--color', 'never',
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
