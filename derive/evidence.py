"""What the record says the learner can do, and what to give them next.

Four separate kinds of evidence per idea; they are never blended into one score:
  derived     finished the idea's chain
  applied     a real judge accepted a problem that needs the idea
  recognised  the same, cold: approach committed first, no nudge, no editorial,
              and the accept was read from the judge rather than self-reported
  combined    a cold accept on a problem that needs two or more ideas
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone

from .store import now

START_BAND = 1600   # below this is theory only: chains, no problems
TOP_BAND = 2500
RETURN_DAYS = (3, 7, 21)     # an idea that needed help comes back after 3 days, then 7, then 21
CAUSES = {
    'unknown-fact': 'I did not know the fact it rests on',
    'unrecognised': 'I knew the idea but did not see that it applied',
    'wrong-conjecture': 'I believed something false',
    'no-proof': 'I had the idea but could not prove it',
    'implementation': 'The idea was right; the code was wrong',
}

# The moves that produce an observation when no known technique fits. After a problem is finished she names
# the one that cracks it and says whether she made it herself; the record then shows which moves she keeps missing.
MOVES = {
    'small-cases': 'Work small cases by hand and look for the pattern',
    'brute-pattern': 'Write a brute force, print small answers, guess and test',
    'invariant': 'Ask what never changes (parity, a sum, a count, an order)',
    'bound': 'Find an obvious bound on the answer, then show it can be reached',
    'simplify': 'Solve an easier version first (sorted, all equal, a path, n = 2)',
    'reverse': 'Go backwards or flip the viewpoint (per element, fix the answer)',
    'extremes': 'Look at the extreme: the largest, the leftmost, the first move',
    'technique': 'None of these: it was recognising a known technique',
}


def attempts(store):
    return {r['problem']: r for r in store.all('SELECT * FROM attempts')}


def is_cold(row):
    return bool(row and row['solved_at'] and row['cold'])


def idea_evidence(content, store):
    derived = {r['idea']: r['at'] for r in store.all('SELECT * FROM discoveries')}
    rows = attempts(store)
    out = {}
    for idea in content.order:
        linked = content.problems_for(idea)
        solved = [p for p in linked if rows.get(p['id']) and rows[p['id']]['solved_at']]
        cold = [p for p in solved if is_cold(rows[p['id']])]
        out[idea] = {
            'derived': idea in derived,
            'applied': len(solved),
            'recognised': len(cold),
            'combined': sum(1 for p in cold if len(p['ideas']) >= 2),
            'problems': len(linked),
        }
    return out


def pair_evidence(content, store):
    """Cold accepts on problems that needed both ideas of a pair: knowing each alone is not this."""
    rows = attempts(store)
    pairs = {}
    for problem in content.problems.values():
        ideas = sorted(problem['ideas'])
        for i, a in enumerate(ideas):
            for b in ideas[i + 1:]:
                entry = pairs.setdefault((a, b), {'problems': 0, 'applied': 0, 'recognised': 0})
                entry['problems'] += 1
                row = rows.get(problem['id'])
                if row and row['solved_at']:
                    entry['applied'] += 1
                    entry['recognised'] += int(is_cold(row))
    return pairs


def band(content, store):
    """The rating the learner is working at. It rises only on cold accepts: 7 of the last 10 at this level."""
    current = store.get('band', START_BAND)
    since = store.get('band_raised_at', '')          # after a rise the count starts again
    finished = [r for r in store.all('SELECT * FROM attempts WHERE solved_at IS NOT NULL OR gave_up_at IS NOT NULL ORDER BY COALESCE(solved_at, gave_up_at) DESC')
                if r['problem'] in content.problems and content.problems[r['problem']]['rating'] >= current - 100
                and (r['solved_at'] or r['gave_up_at']) > since]
    recent = finished[:10]
    return {'band': current, 'recent': len(recent), 'cold': sum(1 for r in recent if is_cold(r))}


def raise_band(content, store):
    state = band(content, store)
    if state['recent'] >= 10 and state['cold'] >= 7 and state['band'] < TOP_BAND:
        store.set('band', state['band'] + 100)
        # The count starts again at the new level.
        store.set('band_raised_at', now())
        return state['band'] + 100
    return None


def schedule_returns(content, store, problem, reason):
    """After help or a give-up, each idea of the problem is owed a cold reappearance."""
    for idea in problem['ideas']:
        earlier = store.one('SELECT COUNT(*) FROM returns WHERE idea=?', (idea,))[0]
        days = RETURN_DAYS[min(earlier, len(RETURN_DAYS) - 1)]
        due = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
        store.run('INSERT INTO returns(idea,due,reason,created) VALUES(?,?,?,?)', (idea, due, reason, now()))


def settle_returns(store, problem):
    """A cold accept pays off every return owed for the ideas it needed."""
    for idea in problem['ideas']:
        store.run('UPDATE returns SET done_at=?, done_by=? WHERE idea=? AND done_at IS NULL', (now(), problem['id'], idea))


def due_returns(store):
    return [r['idea'] for r in store.all('SELECT DISTINCT idea FROM returns WHERE done_at IS NULL AND due<=? ORDER BY due', (now(),))]


def open_problem(store):
    row = store.one('SELECT problem FROM attempts WHERE solved_at IS NULL AND gave_up_at IS NULL ORDER BY opened_at DESC LIMIT 1')
    return row['problem'] if row else None


def next_problem(content, store):
    """Choose the next real problem. Returns (problem id or None, why).

    Order of preference: the one already open; an idea owed a return, inside a
    problem not seen before; otherwise something new at the working level,
    from a different area than the last one so the topic cannot be guessed.
    """
    unfinished = open_problem(store)
    if unfinished in content.problems:
        return unfinished, 'open'
    seen = set(attempts(store))
    fresh = [p for p in content.problems.values() if p['id'] not in seen]
    if not fresh:
        return None, 'none'
    level = store.get('band', START_BAND)
    for idea in due_returns(store):
        options = [p for p in fresh if idea in p['ideas']]
        if options:
            choice = min(options, key=lambda p: (abs(p['rating'] - level), p['id']))
            return choice['id'], 'return:' + idea
    last = store.one('SELECT problem FROM attempts ORDER BY opened_at DESC LIMIT 1')
    last_areas = {content.ideas[i]['area'] for i in content.problems[last['problem']]['ideas']} if last and last['problem'] in content.problems else set()

    derived = {r['idea'] for r in store.all('SELECT idea FROM discoveries')}

    def cost(problem):
        areas = {content.ideas[i]['area'] for i in problem['ideas']}
        # nearest to the working level; slightly below is preferred to far above
        gap = problem['rating'] - level
        # Deriving feeds solving: a problem resting only on ideas already derived is preferred to one that is not,
        # as long as it is within about a level of where she is working.
        unknown = 0 if all(i in derived for i in problem['ideas']) else 120
        return (abs(gap) + (60 if gap > 100 else 0) + (40 if areas & last_areas else 0) + unknown, problem['id'])
    return min(fresh, key=cost)['id'], 'new'
