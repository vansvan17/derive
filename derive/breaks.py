"""Break it: a wrong solution is shown, and the learner must find an input on which it fails.

Each item names an existing task (its statement, and its solve and brute as the
truth) and carries

    wrong     the C++ source shown on the page; exactly this source is compiled and run
    limits    the small limits an input must respect here, in words
    valid     Python defining valid(text): '' for an acceptable input, otherwise what is wrong
    witness   one input that breaks it (used only to check the content; never sent to the page)
    why       shown once it is broken: why the idea fails
    nudges    smaller questions, opened one at a time

An input counts only if it is valid, so a malformed input that confuses the
program is not a break. The wrong program runs in the same sandbox as the
learner's own code.
"""
from __future__ import annotations
import json
import tempfile
from pathlib import Path

from . import tasks
from .runner import Executable, same_output
from .store import now

INPUT_LIMIT = 2000
SECONDS = 2.0


def validator(item):
    scope = {}
    exec(item['valid'], scope)
    return scope['valid']


def invalid(item, text):
    """Why this input may not be used, or ''."""
    if not text.strip():
        return 'Type an input first.'
    if len(text) > INPUT_LIMIT:
        return 'That input is too long: keep it small.'
    try:
        return validator(item)(text) or ''
    except Exception:
        return 'The input is not in the format the statement describes.'


def attempt(item, task, text):
    """Run the wrong program on one valid input and compare with the truth."""
    _, solve, brute = tasks.load(task)
    check = tasks.checker(task)
    expected = solve(text)
    if not same_output(expected, brute(text)) and not (check and not check(text, brute(text), expected)):
        return {'verdict': 'UNSURE', 'detail': 'The two reference solutions of this app disagree on that input, so it cannot be judged. That is a fault in the app, not in your input.'}
    with tempfile.TemporaryDirectory(prefix='derive-break-') as folder:
        path = Path(folder) / 'main.cpp'
        path.write_text(item['wrong'])
        with Executable(path, SECONDS, 256) as program:
            got = program.run(text)
    if got.verdict != 'OK':
        return {'verdict': 'BROKEN', 'output': got.output[:2000], 'expected': expected[:2000],
                'detail': {'TLE': 'The program did not finish in time on your input.', 'RE': 'The program crashed on your input.'}.get(got.verdict, f'The program stopped with {got.verdict} on your input.')}
    wrong = bool(check(text, got.output, expected)) if check else not same_output(got.output, expected)
    return {'verdict': 'BROKEN' if wrong else 'SAME', 'output': got.output[:2000], 'expected': expected[:2000],
            'detail': 'The program prints a wrong answer on your input.' if wrong else 'On this input the program is right.'}


def state(store, item):
    done = store.one('SELECT * FROM breaks_done WHERE item=?', (item['id'],))
    tries = store.one('SELECT COUNT(*) FROM break_tries WHERE item=?', (item['id'],))[0]
    return done, tries


def listing(content, store):
    out = []
    for item in content.breaks.values():
        done, tries = state(store, item)
        out.append({'id': item['id'], 'title': item['title'], 'broken': bool(done), 'tries': tries})
    return out


def page(content, store, item):
    task = content.tasks[item['task']]
    done, tries = state(store, item)
    last = store.one('SELECT input FROM break_tries WHERE item=? ORDER BY id DESC LIMIT 1', (item['id'],))
    opened = store.one("SELECT COUNT(*) FROM nudges WHERE scope='break' AND owner=?", (item['id'],))[0]
    return {'id': item['id'], 'title': item['title'], 'statement': task['statement'], 'samples': task['samples'], 'wrong': item['wrong'], 'limits': item['limits'],
            'broken': bool(done), 'tries': tries, 'input': done['input'] if done else (last['input'] if last else ''),
            'nudges': item['nudges'][:opened], 'nudges_left': len(item['nudges']) - opened,
            # why the idea fails is the answer, so it is sent only once she has broken it herself
            'why': item['why'] if done else None}


def record(store, item, text, result):
    broken = result['verdict'] == 'BROKEN'
    if result['verdict'] != 'UNSURE':
        store.run('INSERT INTO break_tries(at,item,input,broken) VALUES(?,?,?,?)', (now(), item['id'], text, int(broken)))
    if broken:
        tries = store.one('SELECT COUNT(*) FROM break_tries WHERE item=?', (item['id'],))[0]
        nudges = store.one("SELECT COUNT(*) FROM nudges WHERE scope='break' AND owner=?", (item['id'],))[0]
        store.run('INSERT OR IGNORE INTO breaks_done VALUES(?,?,?,?,?)', (item['id'], now(), tries, nudges, text))
    return result


def faults(content):
    """Content checks: every item compiles, looks right on the samples, has a real witness and a validator that refuses rubbish."""
    out = []
    for item in content.breaks.values():
        tag = f'break {item.get("id")}'
        missing = [k for k in ('title', 'task', 'wrong', 'limits', 'valid', 'witness', 'why', 'nudges') if not item.get(k)]
        if missing or item.get('task') not in content.tasks:
            out.append(f'{tag}: missing {", ".join(missing) or "an existing task"}')
            continue
        if any(not n.rstrip().endswith('?') for n in item['nudges']):
            out.append(f'{tag}: a nudge must be a question')
        task = content.tasks[item['task']]
        try:
            for rubbish in ('', 'hello', '1 2 3 4 5 6 7 8 9 ' * 40, '-1', '999999'):
                if not invalid(item, rubbish):
                    out.append(f'{tag}: the validator accepts {rubbish[:20]!r}')
            if invalid(item, item['witness']):
                out.append(f'{tag}: the validator refuses the stored witness')
            elif attempt(item, task, item['witness'])['verdict'] != 'BROKEN':
                out.append(f'{tag}: the stored witness does not break the program')
            for text, _ in task['samples']:
                if not invalid(item, text) and attempt(item, task, text)['verdict'] != 'SAME':
                    out.append(f'{tag}: the program is already wrong on a sample, so it is not a plausible solution')
        except Exception as exc:
            out.append(f'{tag}: checking crashed: {exc!r}')
    return out
