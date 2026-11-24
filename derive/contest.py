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

Only two public, read-only Codeforces calls are used: the problem list
(problemset.problems) and each handle's submissions (user.status). Gym contests
cannot be read without logging in, so only regular rounds are supported.
"""
from __future__ import annotations
from datetime import datetime, timezone
import json
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
API = 'https://codeforces.com/api/'


def _now():
    return datetime.now(timezone.utc)


def problems_of(contest_id, fetch, cache):
    """The problems of one round, from the public problem list (kept in memory after the first call)."""
    if 'all' not in cache:
        data = fetch(API + 'problemset.problems')
        if data.get('status') != 'OK':
            raise SyncError('Codeforces did not return its problem list.')
        cache['all'] = data['result']['problems']
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


def read_submissions(handles, contest_id, fetch):
    out = []
    for handle in handles:
        data = fetch(API + 'user.status?' + urllib.parse.urlencode({'handle': handle, 'from': 1, 'count': 300}))
        if data.get('status') != 'OK':
            raise SyncError(f'Codeforces did not recognise the handle {handle}.')
        for sub in data['result']:
            if sub.get('problem', {}).get('contestId') == contest_id:
                out.append({'index': sub['problem']['index'], 'verdict': sub.get('verdict'), 'at': sub['creationTimeSeconds'], 'id': str(sub['id']), 'handle': handle})
    return out


def view(store, row):
    """What the page needs about one run."""
    if not row:
        return None
    start = datetime.fromisoformat(row['started_at']).timestamp()
    end = start + row['minutes'] * 60
    over = bool(row['ended_at']) or _now().timestamp() >= end
    labels = {r['submission']: r['label'] for r in store.all('SELECT * FROM contest_mistakes WHERE run=?', (row['id'],))}
    board = json.loads(row['board'])
    for r in board.get('rows', []):
        for w in r['wrong']:
            w['label'] = labels.get(w['id'])
    return {'id': row['id'], 'contest': row['contest'], 'url': f'https://codeforces.com/contest/{row["contest"]}', 'handles': json.loads(row['handles']),
            'minutes': row['minutes'], 'started_at': row['started_at'], 'ended': over, 'closed': bool(row['ended_at']),
            'seconds_left': max(0, int(end - _now().timestamp())) if not over else 0, 'checked_at': row['checked_at'], **board}


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
    contest_id, minutes, handles = data.get('contest'), data.get('minutes', 300), data.get('handles')
    if type(contest_id) is not int or not 1 <= contest_id < 100000:
        raise ApiError('Give the number of a regular Codeforces round (the number in its address). Gym contests cannot be read without a login.')
    if type(minutes) is not int or not 30 <= minutes <= 600:
        raise ApiError('Choose a length between 30 and 600 minutes.')
    if not isinstance(handles, list) or not 1 <= len(handles) <= 3 or not all(isinstance(h, str) and HANDLE.fullmatch(h) for h in handles):
        raise ApiError('Give one to three Codeforces handles.')
    try:
        problems = problems_of(contest_id, service.fetch, service.cf_cache)
    except SyncError as exc:
        raise ApiError(str(exc), 502) from exc
    if not problems:
        raise ApiError('Codeforces lists no problems for that round. Check the number.')
    board = score(problems, [], 0, 0)
    store.run('INSERT INTO contests(contest,started_at,minutes,handles,board) VALUES(?,?,?,?,?)',
              (contest_id, _now().isoformat(), minutes, json.dumps(handles), json.dumps(board)))
    return view(store, store.one('SELECT * FROM contests ORDER BY id DESC LIMIT 1'))


def refresh(service, store, data, ApiError):
    row = store.one('SELECT * FROM contests WHERE id=?', (data.get('run'),)) if type(data.get('run')) is int else None
    if not row:
        raise ApiError('No such contest run.', 404)
    problems = [{k: r[k] for k in ('index', 'name', 'rating')} for r in json.loads(row['board'])['rows']]
    try:
        subs = read_submissions(json.loads(row['handles']), row['contest'], service.fetch)
    except SyncError as exc:
        raise ApiError(str(exc), 502) from exc
    start_at = datetime.fromisoformat(row['started_at']).timestamp()
    stop = datetime.fromisoformat(row['ended_at']).timestamp() if row['ended_at'] else start_at + row['minutes'] * 60
    board = score(problems, subs, start_at, min(stop, start_at + row['minutes'] * 60))
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


def overview(store):
    """Everything for the contest page: the run in progress or the latest one, the history, the upsolve list, the mistake counts."""
    rows = store.all('SELECT * FROM contests ORDER BY id DESC')
    runs = [view(store, r) for r in rows]
    upsolve = [{'run': v['id'], 'contest': v['contest'], 'index': r['index'], 'name': r['name'], 'rating': r['rating'],
                'url': f'https://codeforces.com/contest/{v["contest"]}/problem/{r["index"]}'}
               for v in runs if v['ended'] for r in v['rows'] if not r['solved'] and not r['upsolved']]
    counts = {k: 0 for k in MISTAKES}
    for r in store.all('SELECT label, COUNT(*) AS n FROM contest_mistakes GROUP BY label'):
        counts[r['label']] = r['n']
    unlabelled = sum(1 for v in runs if v['ended'] for r in v['rows'] for w in r['wrong'] if not w.get('label'))
    return {'current': runs[0] if runs and not runs[0]['ended'] else None, 'runs': runs[:20], 'upsolve': upsolve,
            'mistakes': [{'id': k, 'label': v, 'count': counts[k]} for k, v in MISTAKES.items()], 'unlabelled': unlabelled, 'wrong_cost': WRONG_COST}
