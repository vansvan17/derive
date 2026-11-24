"""Reading the learner's own public submissions, so a solve is the judge's word and not a click.

Two read-only public endpoints are used, and the only thing sent is the handle
the learner typed into Settings:
  Codeforces  https://codeforces.com/api/user.status
  AtCoder     https://kenkoooo.com/atcoder/atcoder-api/v3/user/submissions (the AtCoder Problems mirror)
CSES has no public submission list, so CSES results can only be self-reported.
"""
from __future__ import annotations
from datetime import datetime
import gzip
import json
import re
import urllib.error
import urllib.parse
import urllib.request

HANDLE = re.compile(r'[A-Za-z0-9_.\-]{1,40}')


class SyncError(RuntimeError):
    pass


def fetch(url):
    request = urllib.request.Request(url, headers={'Accept': 'application/json', 'Accept-Encoding': 'gzip', 'User-Agent': 'derive-local/1.0'})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read()
            if response.headers.get('Content-Encoding') == 'gzip':
                raw = gzip.decompress(raw)
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        raise SyncError(f'The judge site answered with an error ({exc.code}). Check the handle in Settings.') from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise SyncError('Could not reach the judge site. Check your connection and try again.') from exc


def accepted(problem, handle, opened_at, fetch=fetch):
    """Look for an accepted submission of this problem by this handle.

    Returns None, or {'id', 'at', 'before_open'}. An accept from before the
    problem was opened here proves it was solved once, but not cold today.
    """
    if not handle or not HANDLE.fullmatch(handle):
        raise SyncError('Add your handle for this site in Settings first.')
    opened = datetime.fromisoformat(opened_at).timestamp()
    hits = []
    if problem['site'] == 'Codeforces':
        data = fetch('https://codeforces.com/api/user.status?' + urllib.parse.urlencode({'handle': handle, 'from': 1, 'count': 500}))
        if data.get('status') != 'OK':
            raise SyncError('Codeforces did not recognise that handle.')
        for sub in data['result']:
            p = sub.get('problem', {})
            if sub.get('verdict') == 'OK' and p.get('contestId') == problem['contest'] and p.get('index') == problem['index']:
                hits.append((sub['creationTimeSeconds'], str(sub['id'])))
    elif problem['site'] == 'AtCoder':
        # The mirror pages by time; start a little before the problem was opened, and also catch older accepts.
        for start in (0, int(opened) - 3600):
            data = fetch('https://kenkoooo.com/atcoder/atcoder-api/v3/user/submissions?' + urllib.parse.urlencode({'user': handle, 'from_second': start}))
            for sub in data:
                if sub.get('result') == 'AC' and sub.get('problem_id') == problem['index']:
                    hits.append((sub['epoch_second'], str(sub['id'])))
            if any(t >= opened for t, _ in hits):
                break
    else:
        raise SyncError('This site has no public submission list; report the result yourself.')
    if not hits:
        return None
    after = [h for h in hits if h[0] >= opened]
    when, sid = min(after) if after else max(hits)
    return {'id': sid, 'at': datetime.fromtimestamp(when).astimezone().isoformat(), 'before_open': not after}
