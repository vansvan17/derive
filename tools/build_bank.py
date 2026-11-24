"""List recent Codeforces problems to read for the problem set.

Ratings drift: an 1800 from a 2025 round is harder than an 1800 from years ago.
So candidates come only from contests that started on or after --since.

This only uses the public Codeforces API (titles, ratings, tags, solve counts).
It writes a reading list. Nothing here goes into content/problems.json until the
statement and editorial of that problem have actually been read.

    python3 tools/build_bank.py --since 2025-01-01 --per-band 12
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import pathlib
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
API = 'https://codeforces.com/api/'
# Tags that are implementation-heavy or need special handling by the judge.
SKIP_TAGS = {'*special', 'interactive'}


def call(method):
    with urllib.request.urlopen(urllib.request.Request(API + method, headers={'User-Agent': 'derive-local'}), timeout=60) as reply:
        body = json.load(reply)
    if body.get('status') != 'OK':
        raise SystemExit(f'Codeforces API: {body.get("comment")}')
    return body['result']


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--since', default='2025-01-01')
    parser.add_argument('--low', type=int, default=1200)
    parser.add_argument('--high', type=int, default=2500)
    parser.add_argument('--per-band', type=int, default=12, help='candidates per 100 points (more than needed, some get dropped on reading)')
    parser.add_argument('--out', default=str(ROOT / 'content' / 'candidates.json'))
    args = parser.parse_args()
    since = dt.datetime.fromisoformat(args.since).replace(tzinfo=dt.timezone.utc).timestamp()

    # Contests that are finished, rated-style rounds, and recent enough.
    contests = {c['id']: c for c in call('contest.list?gym=false')
                if c.get('phase') == 'FINISHED' and c.get('startTimeSeconds', 0) >= since}
    data = call('problemset.problems')
    solved = {(s['contestId'], s['index']): s['solvedCount'] for s in data['problemStatistics']}

    # A Div. 1 and Div. 2 round share problems under two contest ids; keep one copy by name.
    seen, bands = set(), {}
    for p in data['problems']:
        rating, cid = p.get('rating'), p.get('contestId')
        if rating is None or cid not in contests or not args.low <= rating <= args.high:
            continue
        if SKIP_TAGS & set(p.get('tags', [])) or p['name'] in seen:
            continue
        seen.add(p['name'])
        contest = contests[cid]
        bands.setdefault(rating, []).append({
            'site': 'Codeforces', 'contest': cid, 'index': p['index'], 'title': p['name'], 'rating': rating,
            'tags': p.get('tags', []), 'solved': solved.get((cid, p['index']), 0),
            'round': contest['name'], 'date': dt.datetime.fromtimestamp(contest['startTimeSeconds'], dt.timezone.utc).date().isoformat(),
            'url': f'https://codeforces.com/contest/{cid}/problem/{p["index"]}',
        })

    # Within a band: spread across tags, newest first, so one topic cannot fill the band.
    chosen = []
    for rating in sorted(bands):
        pool = sorted(bands[rating], key=lambda q: q['date'], reverse=True)
        used, picked = {}, []
        while pool and len(picked) < args.per_band:
            pool.sort(key=lambda q: (max((used.get(t, 0) for t in q['tags']), default=0), -dt.date.fromisoformat(q['date']).toordinal()))
            q = pool.pop(0)
            picked.append(q)
            for t in q['tags']:
                used[t] = used.get(t, 0) + 1
        chosen += picked
        print(f'{rating}: {len(picked)} of {len(bands[rating])} recent problems')
    pathlib.Path(args.out).write_text(json.dumps({'since': args.since, 'made': dt.date.today().isoformat(), 'read': False, 'problems': chosen}, indent=1) + '\n')
    print(f'{len(chosen)} candidates written to {args.out}')


if __name__ == '__main__':
    main()
