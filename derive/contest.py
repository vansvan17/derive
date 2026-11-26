"""Contest mode: a real Codeforces round against the clock, scored the ICPC way.

The learner (or her team, up to three handles) picks a past Codeforces round and
a length. From that moment nudges, the tutor and editorials are locked. The
score is read from the judge: for every problem, the first accepted submission
made after the start by any of the handles, and the wrong submissions before it.

    solved   number of problems accepted inside the time
    penalty  for each solved problem: minutes from the start to the accept,
             plus 20 for every wrong submission before it (compile errors are free)

When the run ends, each wrong submission can be labelled with what went wrong,
and every unsolved problem goes on an upsolve list until the judge shows an accept.

Instead of one round, the run can be a mixed set drawn for the team: problems
from many recent rounds, spread over a range of ratings, shuffled and relabelled
A, B, C..., none of which any of the handles has ever submitted. Unlike a round,
it does not tell you which problem is the easy one.

After a run comes the debrief: who solved what, the dry spells, the problem left
on the table, and for every unsolved problem what stalled the team, plus one
lesson in the team's own words. These add up across runs.

Only three public, read-only Codeforces calls are used: the problem list
(problemset.problems), the list of rounds with their dates (contest.list, for a
mixed set only) and each handle's submissions (user.status). Gym contests
cannot be read without logging in, so only regular rounds are supported.
"""
from __future__ import annotations
from datetime import datetime, timezone
import json
import random
import urllib.parse

from .sync import HANDLE, SyncError

WRONG_COST = 20
FREE = {'COMPILATION_ERROR', 'TESTING', 'SKIPPED', 'SUBMITTED', None}
MISTAKES = {
    'idea': 'Wrong idea: the approach itself was not correct',
    'misread': 'Misread the statement or a constraint',
    'edge': 'Missed a special case (n = 1, zero, equal values, empty)',
    'overflow': 'Overflow or a wrong data type',
    'reset': 'State not cleared between test cases',
    'offbyone': 'Off by one, or a wrong index or bound',
    'slow': 'Too slow: wrong complexity, or a heavy constant',
    'typo': 'A slip while typing the code',
    'unknown': 'Still do not know',
}
STALLS = {
    'unread': 'Nobody read it',
    'no-idea': 'Read it, and no idea came',
    'wrong-idea': 'Coded an idea that was wrong',
    'bug': 'Right idea, coded, and the bug was never found',
    'keyboard': 'Ready to code, but the keyboard was busy',
    'late': 'Had the idea too late to code it',
    'reach': 'Out of reach for now',
}
SINCE = datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp()      # a mixed set uses rounds from this date on: older ratings run easier
API = 'https://codeforces.com/api/'


def _now():
    return datetime.now(timezone.utc)


def all_problems(fetch, cache):
    if 'all' not in cache:
        data = fetch(API + 'problemset.problems')
        if data.get('status') != 'OK':
            raise SyncError('Codeforces did not return its problem list.')
        cache['all'] = data['result']['problems']
    return cache['all']


def problems_of(contest_id, fetch, cache):
    """The problems of one round, from the public problem list (kept in memory after the first call)."""
    all_problems(fetch, cache)
    found = [{'index': p['index'], 'name': p['name'], 'rating': p.get('rating')} for p in cache['all'] if p.get('contestId') == contest_id]
    return sorted(found, key=lambda p: (len(p['index']), p['index']))


def score(problems, submissions, start, end):
    """ICPC scoring. submissions: dicts with index, verdict, at (seconds since epoch), id, handle.

    Returns rows per problem plus the totals. Submissions before the start are
    ignored; submissions after the end count only towards upsolving.
    """
    rows, solved, penalty = [], 0, 0
    for p in problems:
        mine = sorted((s for s in submissions if s['index'] == p['index'] and s['at'] >= start), key=lambda s: s['at'])
        wrong, accept, late = [], None, None
        for s in mine:
            if s['verdict'] == 'OK':
                if s['at'] <= end:
                    accept = s
                else:
                    late = s
                break
            if s['verdict'] not in FREE and s['at'] <= end:
                wrong.append({'id': s['id'], 'verdict': s['verdict'], 'minute': int((s['at'] - start) // 60), 'handle': s['handle']})
        row = {**p, 'solved': bool(accept), 'minute': int((accept['at'] - start) // 60) if accept else None,
               'wrong': wrong, 'upsolved': bool(late), 'by': accept['handle'] if accept else None}
        if accept:
            solved += 1
            penalty += row['minute'] + WRONG_COST * len(wrong)
        rows.append(row)
    return {'rows': rows, 'solved': solved, 'penalty': penalty}


def read_submissions(handles, contest_id, fetch, rows=()):
    """The handles' recent submissions to this run's problems, under the letters the run uses.

    A round is matched by its number. A mixed set is matched problem by problem: each of its rows
    remembers the round and letter the problem really has on Codeforces."""
    mixed = {(r['contest'], r['cf_index']): r['index'] for r in rows if r.get('contest')}
    out = []
    for handle in handles:
        data = fetch(API + 'user.status?' + urllib.parse.urlencode({'handle': handle, 'from': 1, 'count': 300}))
        if data.get('status') != 'OK':
            raise SyncError(f'Codeforces did not recognise the handle {handle}.')
        for sub in data['result']:
            p = sub.get('problem', {})
            index = mixed.get((p.get('contestId'), p.get('index'))) if mixed else p.get('index') if p.get('contestId') == contest_id else None
            if index:
                out.append({'index': index, 'verdict': sub.get('verdict'), 'at': sub['creationTimeSeconds'], 'id': str(sub['id']), 'handle': handle})
    return out


def draw_mixed(handles, count, low, high, fetch, cache, avoid=(), rng=None, avoid_names=()):
    """A mixed set: `count` recent problems with ratings spread evenly from `low` to `high`, shuffled, lettered from A.

    Left out: anything one of the handles has ever submitted (by round and letter, and by name, since a problem shared by
    two divisions has two numbers), anything in `avoid` (the problems this app already uses elsewhere), and special rounds."""
    rng = rng or random.Random()
    if 'dates' not in cache:
        data = fetch(API + 'contest.list?gym=false')
        if data.get('status') != 'OK':
            raise SyncError('Codeforces did not return its list of rounds.')
        cache['dates'] = {c['id']: c.get('startTimeSeconds', 0) for c in data['result'] if c.get('phase') == 'FINISHED'}
    recent = {cid for cid, at in cache['dates'].items() if at >= SINCE}
    seen, names = set(avoid), set(avoid_names)
    for handle in handles:
        data = fetch(API + 'user.status?' + urllib.parse.urlencode({'handle': handle}))            # the whole history, not just the last few
        if data.get('status') != 'OK':
            raise SyncError(f'Codeforces did not recognise the handle {handle}.')
        for sub in data['result']:
            p = sub.get('problem', {})
            seen.add((p.get('contestId'), p.get('index'))); names.add(p.get('name'))
    pool = {}
    for p in all_problems(fetch, cache):
        if p.get('contestId') in recent and p.get('rating') and (p['contestId'], p['index']) not in seen and p.get('name') not in names and '*special' not in p.get('tags', []):
            pool.setdefault(p['rating'], []).append(p)
    wanted = [round((low + (high - low) * i / max(1, count - 1)) / 100) * 100 for i in range(count)]
    chosen, used = [], set()
    for rating in wanted:
        for near in sorted(pool, key=lambda r: (abs(r - rating), r)):                              # the wanted rating, else the nearest one that has a problem left
            free = [p for p in pool[near] if p['name'] not in used and p['contestId'] not in used]       # one problem per round: no easy and hard version of the same task
            if free and abs(near - rating) <= 300:
                pick = rng.choice(free); used.update((pick['name'], pick['contestId'])); chosen.append(pick); break
    if len(chosen) < count:
        raise SyncError('Not enough unseen recent problems in that rating range. Widen the range or ask for fewer.')
    rng.shuffle(chosen)
    return [{'index': chr(65 + i), 'name': p['name'], 'rating': p['rating'], 'contest': p['contestId'], 'cf_index': p['index']} for i, p in enumerate(chosen)]


def levels_of(handles, fetch):
    """Each handle's current Codeforces rating (one public call). A handle with no rating yet is left out; if the call fails, so is everyone."""
    try:
        data = fetch(API + 'user.info?' + urllib.parse.urlencode({'handles': ';'.join(handles)}))
    except SyncError:
        return {}
    found = {u['handle'].lower(): u['rating'] for u in data.get('result', []) if isinstance(u, dict) and isinstance(u.get('handle'), str) and type(u.get('rating')) is int}
    return {h: found[h.lower()] for h in handles if h.lower() in found}


def reach(rating, levels):
    """Was an unsolved problem one the team should have had? Judged against each member's own rating.

    A Codeforces rating is the level at which that person solves a problem about half the time, alone and in a short round.
    So a problem at least 100 below someone is one they should get; up to 200 above the strongest is a fair fight; beyond that it is above the team."""
    if not rating or not levels:
        return None
    should = sorted((h for h, own in levels.items() if rating <= own - 100), key=lambda h: -levels[h])
    if should:
        return {'kind': 'should', 'who': should}
    best = max(levels, key=levels.get)
    return {'kind': 'fair', 'who': [best]} if rating <= levels[best] + 200 else {'kind': 'above', 'who': []}


def link(contest_id, row):
    return f'https://codeforces.com/problemset/problem/{row["contest"]}/{row["cf_index"]}' if row.get('contest') else f'https://codeforces.com/contest/{contest_id}/problem/{row["index"]}'


def debrief(board, handles, minutes):
    """What the judge's record says about how the run went. Nothing here is typed in by anyone.

    `minutes` is the time actually sat: a clock ended early is not counted as a dry spell."""
    rows = board.get('rows', [])
    solved = sorted((r for r in rows if r['solved']), key=lambda r: r['minute'])
    marks = [0] + [r['minute'] for r in solved] + [minutes]
    gaps = [(b - a, a, b) for a, b in zip(marks, marks[1:])]
    dry = max(gaps) if gaps else (minutes, 0, minutes)
    people = [{'handle': h, 'accepted': sum(1 for r in solved if r.get('by') == h), 'wrong': sum(1 for r in rows for w in r['wrong'] if w.get('handle') == h)} for h in handles]
    hardest = max((r['rating'] or 0 for r in solved), default=0)
    table = sorted((r for r in rows if not r['solved'] and r['rating'] and r['rating'] < hardest), key=lambda r: r['rating'])
    # an easier problem that fell at least half an hour after a harder one: it was found late
    late = [{'index': r['index'], 'minute': r['minute'], 'rating': r['rating']} for r in solved
            if r['rating'] and any(o['rating'] and o['rating'] >= r['rating'] + 200 and o['minute'] <= r['minute'] - 30 for o in solved)]
    third = minutes - minutes // 3
    return {'first': solved[0]['minute'] if solved else None, 'last': solved[-1]['minute'] if solved else None,
            'dry': {'minutes': dry[0], 'from': dry[1], 'to': dry[2]}, 'final_third': sum(1 for r in solved if r['minute'] >= third),
            'wrong': sum(len(r['wrong']) for r in rows), 'people': people,
            'left': [{'index': r['index'], 'name': r['name'], 'rating': r['rating']} for r in table[:3]], 'late': late}


def view(store, row):
    """What the page needs about one run."""
    if not row:
        return None
    start = datetime.fromisoformat(row['started_at']).timestamp()
    end = start + row['minutes'] * 60
    over = bool(row['ended_at']) or _now().timestamp() >= end
    labels = {r['submission']: r['label'] for r in store.all('SELECT * FROM contest_mistakes WHERE run=?', (row['id'],))}
    stalls = {r['problem']: r['label'] for r in store.all('SELECT * FROM contest_stalls WHERE run=?', (row['id'],))}
    note = store.one('SELECT lesson FROM contest_notes WHERE run=?', (row['id'],))
    board = json.loads(row['board'])
    handles = json.loads(row['handles'])
    levels = board.get('levels') or {}
    for r in board.get('rows', []):
        r['url'] = link(row['contest'], r)
        r['reach'] = reach(r['rating'], levels) if over and not r['solved'] else None
        r['stall'] = stalls.get(r['index'])
        if not over:
            r.pop('contest', None); r.pop('cf_index', None)        # the round a problem came from hints at how hard it is
        for w in r['wrong']:
            w['label'] = labels.get(w['id'])
    mixed = not row['contest']
    sat = min(row['minutes'], max(1, int((datetime.fromisoformat(row['ended_at']).timestamp() - start) // 60))) if row['ended_at'] else row['minutes']
    return {'id': row['id'], 'contest': row['contest'], 'mixed': mixed, 'title': 'Mixed set' if mixed else f'Round {row["contest"]}',
            'url': None if mixed else f'https://codeforces.com/contest/{row["contest"]}', 'handles': handles,
            'minutes': row['minutes'], 'started_at': row['started_at'], 'ended': over, 'closed': bool(row['ended_at']),
            'seconds_left': max(0, int(end - _now().timestamp())) if not over else 0, 'checked_at': row['checked_at'],
            'debrief': debrief(board, handles, sat) if over else None, 'lesson': note['lesson'] if note else '', **board}


def active(store):
    """The run whose clock is still going, if any. While there is one, help is locked."""
    row = store.one('SELECT * FROM contests WHERE ended_at IS NULL ORDER BY id DESC LIMIT 1')
    if not row:
        return None
    end = datetime.fromisoformat(row['started_at']).timestamp() + row['minutes'] * 60
    return row if _now().timestamp() < end else None


def start(service, store, data, ApiError):
    if active(store):
        raise ApiError('A contest is already running. End it first.', 409)
    contest_id, minutes, handles, mixed = data.get('contest'), data.get('minutes', 300), data.get('handles'), data.get('mixed')
    if mixed is not None:
        if not isinstance(mixed, dict) or any(type(mixed.get(k)) is not int for k in ('count', 'low', 'high')) or not 3 <= mixed['count'] <= 15 \
                or not 800 <= mixed['low'] <= mixed['high'] <= 3500:
            raise ApiError('A mixed set has 3 to 15 problems, with ratings from 800 to 3500, easiest first.')
        contest_id = 0
    elif type(contest_id) is not int or not 1 <= contest_id < 100000:
        raise ApiError('Give the number of a regular Codeforces round (the number in its address). Gym contests cannot be read without a login.')
    if type(minutes) is not int or not 30 <= minutes <= 600:
        raise ApiError('Choose a length between 30 and 600 minutes.')
    if not isinstance(handles, list) or not 1 <= len(handles) <= 3 or not all(isinstance(h, str) and HANDLE.fullmatch(h) for h in handles):
        raise ApiError('Give one to three Codeforces handles.')
    try:
        if mixed:
            used = [*service.content.problems.values(), *service.content.parked.values()]          # never spend a problem the Solve page is keeping
            avoid = {(p.get('contest'), p.get('index')) for p in used if p.get('site') == 'Codeforces'}
            problems = draw_mixed(handles, mixed['count'], mixed['low'], mixed['high'], service.fetch, service.cf_cache, avoid, getattr(service, 'rng', None), {p.get('title') for p in used})
        else:
            problems = problems_of(contest_id, service.fetch, service.cf_cache)
    except SyncError as exc:
        raise ApiError(str(exc), 502) from exc
    if not problems:
        raise ApiError('Codeforces lists no problems for that round. Check the number.')
    board = score(problems, [], 0, 0)
    board['levels'] = levels_of(handles, service.fetch)
    store.run('INSERT INTO contests(contest,started_at,minutes,handles,board) VALUES(?,?,?,?,?)',
              (contest_id, _now().isoformat(), minutes, json.dumps(handles), json.dumps(board)))
    return view(store, store.one('SELECT * FROM contests ORDER BY id DESC LIMIT 1'))


def refresh(service, store, data, ApiError):
    row = store.one('SELECT * FROM contests WHERE id=?', (data.get('run'),)) if type(data.get('run')) is int else None
    if not row:
        raise ApiError('No such contest run.', 404)
    problems = [{k: r[k] for k in ('index', 'name', 'rating', 'contest', 'cf_index') if k in r} for r in json.loads(row['board'])['rows']]
    try:
        subs = read_submissions(json.loads(row['handles']), row['contest'], service.fetch, problems)
    except SyncError as exc:
        raise ApiError(str(exc), 502) from exc
    start_at = datetime.fromisoformat(row['started_at']).timestamp()
    stop = datetime.fromisoformat(row['ended_at']).timestamp() if row['ended_at'] else start_at + row['minutes'] * 60
    board = score(problems, subs, start_at, min(stop, start_at + row['minutes'] * 60))
    # the ratings the team had when the run started; a run from before these were kept gets today's
    board['levels'] = json.loads(row['board']).get('levels') or levels_of(json.loads(row['handles']), service.fetch)
    store.run('UPDATE contests SET board=?, checked_at=? WHERE id=?', (json.dumps(board), _now().isoformat(), row['id']))
    return view(store, store.one('SELECT * FROM contests WHERE id=?', (row['id'],)))


def end(service, store, data, ApiError):
    row = store.one('SELECT * FROM contests WHERE id=?', (data.get('run'),)) if type(data.get('run')) is int else None
    if not row:
        raise ApiError('No such contest run.', 404)
    if not row['ended_at']:
        finish = min(_now().timestamp(), datetime.fromisoformat(row['started_at']).timestamp() + row['minutes'] * 60)
        store.run('UPDATE contests SET ended_at=? WHERE id=?', (datetime.fromtimestamp(finish, timezone.utc).isoformat(), row['id']))
    try:
        return refresh(service, store, data, ApiError)
    except ApiError:
        return view(store, store.one('SELECT * FROM contests WHERE id=?', (row['id'],)))   # ended even if the judge cannot be reached now


def label(service, store, data, ApiError):
    row = store.one('SELECT * FROM contests WHERE id=?', (data.get('run'),)) if type(data.get('run')) is int else None
    if not row or active(store) and active(store)['id'] == row['id']:
        raise ApiError('Mistakes are labelled after the contest has ended.', 409)
    known = {w['id'] for r in json.loads(row['board'])['rows'] for w in r['wrong']}
    if data.get('submission') not in known or data.get('label') not in MISTAKES:
        raise ApiError('Pick a wrong submission of this run and one of the listed causes.')
    store.run('INSERT OR REPLACE INTO contest_mistakes VALUES(?,?,?,?)', (row['id'], data['submission'], data['label'], _now().isoformat()))
    return view(store, row)


def stall(service, store, data, ApiError):
    """After the run: what stopped the team on one unsolved problem."""
    row = store.one('SELECT * FROM contests WHERE id=?', (data.get('run'),)) if type(data.get('run')) is int else None
    if not row or active(store) and active(store)['id'] == row['id']:
        raise ApiError('The debrief comes after the contest has ended.', 409)
    unsolved = {r['index'] for r in json.loads(row['board'])['rows'] if not r['solved']}
    if data.get('problem') not in unsolved or data.get('label') not in STALLS:
        raise ApiError('Pick an unsolved problem of this run and one of the listed reasons.')
    store.run('INSERT OR REPLACE INTO contest_stalls VALUES(?,?,?,?)', (row['id'], data['problem'], data['label'], _now().isoformat()))
    return view(store, row)


def lesson(service, store, data, ApiError):
    """After the run: the one thing the team will do differently next time, in its own words."""
    row = store.one('SELECT * FROM contests WHERE id=?', (data.get('run'),)) if type(data.get('run')) is int else None
    if not row or active(store) and active(store)['id'] == row['id']:
        raise ApiError('The debrief comes after the contest has ended.', 409)
    text = data.get('lesson')
    if not isinstance(text, str) or len(text) > 600:
        raise ApiError('Keep the lesson to a sentence or two.')
    store.run('INSERT OR REPLACE INTO contest_notes VALUES(?,?,?)', (row['id'], text.strip(), _now().isoformat()))
    return view(store, row)


def overview(store):
    """Everything for the contest page: the run in progress or the latest one, the history, the upsolve list, the mistake counts."""
    rows = store.all('SELECT * FROM contests ORDER BY id DESC')
    runs = [view(store, r) for r in rows]
    upsolve = [{'run': v['id'], 'contest': v['contest'], 'index': r['index'], 'name': r['name'], 'rating': r['rating'],
                'label': (f'Mixed set {v["id"]} · ' if v['mixed'] else str(v['contest'])) + r['index'], 'url': r['url']}
               for v in runs if v['ended'] for r in v['rows'] if not r['solved'] and not r['upsolved']]
    counts = {k: 0 for k in MISTAKES}
    for r in store.all('SELECT label, COUNT(*) AS n FROM contest_mistakes GROUP BY label'):
        counts[r['label']] = r['n']
    unlabelled = sum(1 for v in runs if v['ended'] for r in v['rows'] for w in r['wrong'] if not w.get('label'))
    stalls = {k: 0 for k in STALLS}
    for r in store.all('SELECT label, COUNT(*) AS n FROM contest_stalls GROUP BY label'):
        stalls[r['label']] = r['n']
    lessons = [{'run': v['id'], 'title': v['title'], 'date': v['started_at'][:10], 'lesson': v['lesson']} for v in runs if v['ended'] and v['lesson']]
    return {'current': runs[0] if runs and not runs[0]['ended'] else None, 'runs': runs[:20], 'upsolve': upsolve,
            'mistakes': [{'id': k, 'label': v, 'count': counts[k]} for k, v in MISTAKES.items()], 'unlabelled': unlabelled, 'wrong_cost': WRONG_COST,
            'stalls': [{'id': k, 'label': v, 'count': stalls[k]} for k, v in STALLS.items()], 'lessons': lessons}
