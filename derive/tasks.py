"""Implement tasks: write real code, judged on this computer.

A task is a plain statement with no hint about technique, sized so that the
obvious loop is too slow. Its tests are not stored: each task carries a little
Python that defines

    gen(rng, size)   an input, for size 'small', 'medium' or 'large'
    solve(text)      the intended solution (fast), giving the expected output
    brute(text)      the obvious solution (slow), used only to check solve
    check(text, out, expected)   optional, for tasks with many right outputs: returns ''
                     when the output is acceptable for that input, otherwise what is wrong
                     with it; expected is solve(text), so the optimum need not be recomputed

The judge generates the same tests every time (fixed seed), runs the learner's
program on each with the task's time limit, and stops at the first failure.
The task code is part of the course content, written by the course author; it
is never the learner's code.
"""
from __future__ import annotations
import random
import tempfile
from pathlib import Path

from .runner import Executable, JudgeError, same_output

SIZES = ['small'] * 12 + ['medium'] * 4 + ['large'] * 4
SEED = 20261126
PYTHON_FACTOR = 5          # a Python solution gets this many times the C++ limit


def load(task):
    """Run a task's code and hand back its three functions."""
    scope = {}
    exec(task['code'], scope)
    return scope['gen'], scope['solve'], scope['brute']


_CACHE = {}


def checker(task):
    """The task's own checker, or None when outputs are simply compared with the expected one.

    It is wrapped so that output it cannot even read counts as wrong, never as a crash of the judge."""
    scope = {}
    exec(task['code'], scope)
    check = scope.get('check')
    if not check:
        return None
    def safe(text, output, expected):
        try:
            return check(text, output, expected) or ''
        except Exception:
            return 'The output is not in the required format.'
    return safe


def tests(task):
    if task['id'] not in _CACHE:
        _CACHE[task['id']] = _build(task)
    return _CACHE[task['id']]


def _build(task):
    gen, solve, _ = load(task)
    rng = random.Random(SEED)
    out = [(sample[0], sample[1]) for sample in task.get('samples', [])]
    for size in SIZES:
        text = gen(rng, size)
        out.append((text, solve(text)))
    return out


def public(task, store):
    done = store.one('SELECT * FROM tasks_done WHERE task=?', (task['id'],))
    tries = store.one('SELECT COUNT(*) FROM task_tries WHERE task=?', (task['id'],))[0]
    last = store.one('SELECT verdict FROM task_tries WHERE task=? ORDER BY id DESC LIMIT 1', (task['id'],))
    return {'id': task['id'], 'title': task['title'], 'track': task.get('track', 'core'), 'solved': bool(done), 'tries': tries, 'last': last['verdict'] if last else None}


def judge(task, language, source):
    """Run the learner's program on every test. Returns the verdict and, for a small failing test, what went wrong."""
    cases = tests(task)
    check = checker(task)
    seconds = task.get('seconds', 1.0) * (PYTHON_FACTOR if language == 'python' else 1)
    with tempfile.TemporaryDirectory(prefix='derive-task-') as folder:
        path = Path(folder) / ('main.py' if language == 'python' else 'main.cpp')
        path.write_text(source)
        try:
            program = Executable(path, seconds, 512)
        except JudgeError as exc:
            return {'verdict': 'CE', 'detail': 'Your code did not compile.\n' + str(exc)[:4000], 'passed': 0, 'of': len(cases)}
        with program:
            slowest = 0.0
            for number, (text, expected) in enumerate(cases, 1):
                got = program.run(text)
                slowest = max(slowest, got.seconds)
                reason = ''
                if got.verdict == 'OK':
                    reason = check(text, got.output, expected) if check else ('' if same_output(got.output, expected) else 'differs')
                wrong = bool(reason)
                if got.verdict != 'OK' or wrong:
                    verdict = 'WA' if wrong else got.verdict
                    out = {'verdict': verdict, 'passed': number - 1, 'of': len(cases), 'test': number, 'seconds': round(got.seconds, 2), 'limit': seconds,
                           'detail': {'WA': 'Wrong answer', 'TLE': f'Too slow: over {seconds:g} s', 'RE': 'Your program crashed', 'MLE': 'Too much memory'}.get(verdict, verdict) + f' on test {number} of {len(cases)}.'}
                    if len(text) <= 600:                     # a small failing test is shown in full; a large one would not help
                        out.update({'input': text, 'expected': expected[:2000], 'output': got.output[:2000]})
                    if check and wrong:
                        out['detail'] += ' ' + reason + ' (Any correct output is accepted; the one shown as expected is just one of them.)'
                    else:
                        out['detail'] += ' The test is a large one, so it is not shown: try your own large input, or stress against a brute force.'
                    return out
    return {'verdict': 'AC', 'passed': len(cases), 'of': len(cases), 'seconds': round(slowest, 2), 'limit': seconds, 'detail': f'All {len(cases)} tests passed; the slowest took {slowest:.2f} s of {seconds:g} s.'}
