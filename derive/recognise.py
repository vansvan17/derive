"""Recognise: read a real statement, say what cracks it, then compare. No coding.

Showing what cracks a problem spoils it as a cold solve, so the cards are drawn
only from problems where nothing is lost:

    parked    real problems that were read and tagged for this course but sit below the
              working level, so they are never handed out under Solve
    finished  problems from the Solve set she has already had accepted or given up on,
              as a later check that the idea stayed

A problem still waiting under Solve is never a card. The rating she gives herself
(saw it, part of it, missed it) is her own word, so it is kept in its own table
and never counted as evidence on the record page.
"""
from __future__ import annotations

from .store import now

RATINGS = {'saw': 'Saw it', 'part': 'Part of it', 'missed': 'Missed it'}
TARGET_SECONDS = 180


def pool(content, store):
    """Every card that may be shown now, as {id: (problem, source)}."""
    cards = {p['id']: (p, 'parked') for p in content.parked.values()}
    for row in store.all('SELECT problem FROM attempts WHERE solved_at IS NOT NULL OR gave_up_at IS NOT NULL'):
        if row['problem'] in content.problems:
            cards[row['problem']] = (content.problems[row['problem']], 'finished')
    return cards


def history(store):
    """The latest finished round per problem: {problem: row}."""
    return {r['problem']: r for r in store.all('SELECT * FROM recognitions WHERE rating IS NOT NULL ORDER BY id')}


def choose(content, store):
    """The next card: one waiting for its rating, else one never drilled (parked first, easiest first),
    else the one missed or half-seen longest ago. Problems she saw are not repeated."""
    cards = pool(content, store)
    waiting = store.one('SELECT problem FROM recognitions WHERE rating IS NULL ORDER BY id DESC LIMIT 1')
    if waiting and waiting['problem'] in cards:
        return waiting['problem']
    seen = history(store)
    fresh = [c for c in cards if c not in seen]
    if fresh:
        return min(fresh, key=lambda c: (cards[c][1] != 'parked', cards[c][0]['rating'], c))
    again = [c for c in cards if seen[c]['rating'] != 'saw']
    return min(again, key=lambda c: seen[c]['id']) if again else None


def card(content, store, derived, problem_id):
    problem, source = pool(content, store)[problem_id]
    open_row = store.one('SELECT * FROM recognitions WHERE problem=? AND rating IS NULL ORDER BY id DESC LIMIT 1', (problem_id,))
    out = {'id': problem['id'], 'title': problem['title'], 'site': problem['site'], 'url': problem['url'], 'rating': problem['rating'], 'source': source,
           'times_before': store.one('SELECT COUNT(*) FROM recognitions WHERE problem=? AND rating IS NOT NULL', (problem_id,))[0], 'revealed': bool(open_row)}
    if open_row:                          # she has said what she thinks: now what cracks it may be shown
        out.update({'guess': open_row['guess'], 'seconds': open_row['seconds'], 'observations': problem['observations'], 'editorial': problem.get('editorial'),
                    'ideas': [{'id': i, 'derived': i in derived, 'name': content.ideas[i]['name'] if i in derived else None, 'has_chain': i in content.chains} for i in problem['ideas']]})
    return out


def overview(content, store, derived):
    cards = pool(content, store)
    seen = history(store)
    counts = {k: sum(1 for r in seen.values() if r['rating'] == k and r['problem'] in cards) for k in RATINGS}
    next_id = choose(content, store)
    return {'card': card(content, store, derived, next_id) if next_id else None, 'target': TARGET_SECONDS,
            'pool': len(cards), 'parked': sum(1 for _, s in cards.values() if s == 'parked'), 'drilled': sum(1 for c in cards if c in seen),
            'counts': [{'id': k, 'label': v, 'count': counts[k]} for k, v in RATINGS.items()]}


def reveal(content, store, data, ApiError):
    cards = pool(content, store)
    if data.get('id') not in cards or data.get('id') != choose(content, store):
        raise ApiError('That is not the card in front of you.', 409)
    guess = data.get('guess') if isinstance(data.get('guess'), str) else ''
    if len(guess.strip()) < 8:
        raise ApiError('Say what you think cracks it first, even if you are unsure. One sentence is enough.')
    seconds = data.get('seconds') if type(data.get('seconds')) is int and 0 <= data['seconds'] <= 86400 else 0
    if not store.one('SELECT 1 FROM recognitions WHERE problem=? AND rating IS NULL', (data['id'],)):
        store.run('INSERT INTO recognitions(at,problem,guess,seconds) VALUES(?,?,?,?)', (now(), data['id'], guess[:4000], seconds))


def rate(content, store, data, ApiError):
    row = store.one('SELECT * FROM recognitions WHERE problem=? AND rating IS NULL ORDER BY id DESC LIMIT 1', (data.get('id'),)) if isinstance(data.get('id'), str) else None
    if not row or data.get('rating') not in RATINGS:
        raise ApiError('Compare your answer with what cracks it, then pick one of the three.')
    store.run('UPDATE recognitions SET rating=?, rated_at=? WHERE id=?', (data['rating'], now(), row['id']))


def faults(content):
    out = []
    for p in content.parked.values():
        tag = f'parked problem {p.get("id")}'
        if not (p.get('title') and p.get('observations') and p.get('checked') and str(p.get('url', '')).startswith('https://') and isinstance(p.get('rating'), int)):
            out.append(f'{tag}: needs a title, a link, a rating, observations and the date it was read')
        if not p.get('ideas') or any(i not in content.ideas for i in p.get('ideas', [])):
            out.append(f'{tag}: names an idea that is not on the map')
        if p.get('id') in content.problems:
            out.append(f'{tag}: is also in the Solve set, where showing what cracks it would spoil it')
    return out
