"""Stars: anything worth coming back to, kept as a card for revision.

A star is only a reference (a kind and an id), never a copy, so a card always shows the current
wording. What can be starred: a chain question, a puzzle, a real problem, a Code task, a Toolbox
page, and the notes written on a chain or on a problem.

A card has a front and, sometimes, a back. The back is built here, on the server, and only from
what the learner has already earned: her answer and what the step showed once the step is done,
a puzzle's reason once it is finished, a problem's observations once it is solved or given up,
her own accepted code for a task. An unfinished item is a front and a link, nothing more.
A star can carry a note to yourself, written when you star it and editable afterwards; the note is
shown on the front of the card. Starring is not help: it writes nothing but the star and its note.
There are no due dates and no scores.
"""
from __future__ import annotations
from datetime import datetime, timezone

KINDS = {'step': 'Chain question', 'puzzle': 'Puzzle', 'problem': 'Problem', 'task': 'Code task', 'tool': 'Toolbox page',
         'chain-notes': 'Your notes on a chain', 'problem-notes': 'Your notes on a problem'}


def _chain_title(service, idea, derived):
    info = service.content.ideas[idea]
    area = next((a['title'] for a in service.content.areas if a['id'] == info['area']), '')
    return info['name'] if idea in derived else f'A chain in {area}' if area else 'A chain'       # a name is shown only once it is derived


def _step(service, store, ref):
    idea, _, step_id = ref.partition('/')
    chain = service.content.chains.get(idea)
    if not chain or idea not in service.content.ideas:
        return None, None, None, None
    done = service.done_steps(store, idea)
    for step in chain['steps']:
        if step['id'] == step_id:
            return idea, step, done.get(step_id), True
        if step['id'] not in done:
            break                                   # steps beyond the current one have not been seen
    return idea, None, None, None


def card(service, store, kind, ref, derived, locked=False):
    """One card, or None when the star points at something that no longer exists or was never reached."""
    content = service.content
    if kind == 'step':
        idea, step, done, _ = _step(service, store, ref)
        if not step:
            return None
        out = {'title': _chain_title(service, idea, derived), 'front': step['prompt'], 'options': step.get('options') if step['kind'] == 'choice' else None,
               'link': f'#/chain/{idea}', 'finished': bool(done), 'back': None}
        if done and not locked:
            back = []
            if step['kind'] == 'proof':
                back.append({'label': 'Why it is true', 'list': step.get('claims', [])})
            elif step['kind'] != 'code':
                answer = done['answer']
                if step['kind'] == 'choice' and str(answer).isdigit() and int(answer) < len(step['options']):
                    answer = step['options'][int(answer)]
                back.append({'label': 'Your answer', 'text': str(answer)})
            back.append({'label': 'What it showed', 'text': step['showed']})
            out['back'] = back
        return out
    if kind == 'puzzle':
        puzzle = next((p for p in content.puzzles['puzzles'] if p['id'] == ref), None)
        if not puzzle:
            return None
        title = next((s['title'] for s in content.puzzles['sets'] if s['id'] == puzzle['set']), 'Puzzles')
        done = store.one('SELECT * FROM puzzles_done WHERE puzzle=?', (ref,))
        out = {'title': title, 'front': puzzle['prompt'], 'options': puzzle.get('options') if puzzle['kind'] == 'choice' else None,
               'link': f'#/puzzles/{puzzle["set"]}', 'finished': bool(done), 'back': None}
        if done and not locked:
            last = store.one('SELECT answer FROM puzzle_tries WHERE puzzle=? AND correct=1 ORDER BY id DESC LIMIT 1', (ref,))
            back = []
            if last:
                answer = last['answer']
                if puzzle['kind'] == 'choice' and str(answer).isdigit() and int(answer) < len(puzzle.get('options') or []):
                    answer = puzzle['options'][int(answer)]
                back.append({'label': 'Your answer', 'text': str(answer)})
            back.append({'label': 'The reason', 'text': puzzle['showed']})
            out['back'] = back
        return out
    if kind in ('problem', 'problem-notes'):
        problem = content.problems.get(ref)
        row = store.one('SELECT * FROM attempts WHERE problem=?', (ref,)) if problem else None
        if not row:
            return None
        finished = bool(row['solved_at'] or row['gave_up_at'])
        about = f'{problem["site"]} · rated {problem["rating"]}'
        if kind == 'problem-notes':
            return {'title': problem['title'], 'front': '', 'note': row['notes'], 'link': f'#/problem/{ref}', 'finished': True, 'back': None, 'options': None}
        # the statement is never copied: the front is the title and the way to it
        out = {'title': problem['title'], 'front': f'{about}. Read the statement, then say what cracks it.', 'url': problem['url'], 'site': problem['site'],
               'link': f'#/problem/{ref}', 'finished': finished, 'back': None, 'options': None}
        if finished and not locked:
            back = [{'label': 'What cracks it', 'list': problem['observations']}]
            if row['lesson']:
                back.append({'label': 'Your lesson', 'plain': row['lesson']})
            out['back'] = back
        return out
    if kind == 'task':
        task = content.tasks.get(ref)
        if not task:
            return None
        done = store.one('SELECT 1 FROM tasks_done WHERE task=?', (ref,))
        out = {'title': task['title'], 'front': task['statement'], 'link': f'#/task/{ref}', 'finished': bool(done), 'back': None, 'options': None}
        kept = store.one('SELECT * FROM accepted_code WHERE task=? ORDER BY at DESC LIMIT 1', (ref,)) if done else None
        if kept and not locked:
            out['back'] = [{'label': 'Your accepted code', 'code': kept['code']}]
        return out
    if kind == 'tool':
        tool = content.tools.get(ref)
        if not tool:
            return None
        back = None if locked else [{'label': 'Reach for it when', 'list': tool['when']}, {'label': 'Traps', 'list': tool['traps']}]
        return {'title': tool['title'], 'front': 'When do you reach for it, and what are its traps?', 'link': f'#/tool/{ref}', 'finished': True, 'back': back, 'options': None}
    if kind == 'chain-notes':
        if ref not in content.chains or ref not in content.ideas:
            return None
        return {'title': _chain_title(service, ref, derived), 'front': '', 'note': store.get('chain_notes', {}).get(ref, ''), 'link': f'#/chain/{ref}',
                'finished': True, 'back': None, 'options': None}
    return None


def keys(store):
    """Every star as "kind:ref", with the note it carries."""
    return {f'{r["kind"]}:{r["ref"]}': r['note'] for r in store.all('SELECT kind, ref, note FROM stars ORDER BY at')}


def toggle(service, store, data, ApiError):
    kind, ref = data.get('kind'), data.get('ref')
    if kind not in KINDS or not isinstance(ref, str) or not 0 < len(ref) <= 200:
        raise ApiError('That cannot be starred.')
    have = store.one('SELECT 1 FROM stars WHERE kind=? AND ref=?', (kind, ref))
    want = data.get('on') if isinstance(data.get('on'), bool) else not have       # without "on" it simply flips
    note = data.get('note', '')
    if not isinstance(note, str) or len(note) > 4000:
        raise ApiError('Keep the note under 4000 characters.')
    if not want:
        store.run('DELETE FROM stars WHERE kind=? AND ref=?', (kind, ref))
        return {'on': False, 'stars': keys(store)}
    if have:                                                                      # already starred: this is an edit of its note
        store.run('UPDATE stars SET note=? WHERE kind=? AND ref=?', (note.strip(), kind, ref))
        return {'on': True, 'stars': keys(store)}
    if not card(service, store, kind, ref, service.derived(store)):
        raise ApiError('That cannot be starred yet.', 404)
    store.run('INSERT INTO stars(kind,ref,at,note) VALUES(?,?,?,?)', (kind, ref, datetime.now(timezone.utc).isoformat(), note.strip()))
    return {'on': True, 'stars': keys(store)}


def cards(service, store, locked):
    """Everything starred, newest first. While a contest runs the backs are withheld: reasons and observations are help."""
    derived = service.derived(store)
    out = []
    for r in store.all('SELECT * FROM stars ORDER BY at DESC'):
        try:
            built = card(service, store, r['kind'], r['ref'], derived, locked)
        except Exception:
            built = None                             # a star must never take the page down
        if built:
            out.append({'kind': r['kind'], 'ref': r['ref'], 'label': KINDS[r['kind']], 'at': r['at'], 'my_note': r['note'], **built})
    return {'cards': out, 'locked': locked, 'kinds': [{'id': k, 'label': v, 'count': sum(1 for c in out if c['kind'] == k)} for k, v in KINDS.items()]}
