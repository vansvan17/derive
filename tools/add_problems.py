"""Append hand-written problem entries (JSON list on stdin) to content/problems.json.

Each entry is written only after its statement and editorial were read. Title and
rating are taken from the Codeforces API, never typed from memory. Dropped
candidates are recorded in content/reading_log.json with the reason.
"""
import datetime, json, pathlib, sys, urllib.request
ROOT = pathlib.Path(__file__).resolve().parent.parent
BANK, LOG, CACHE = ROOT / 'content/problems.json', ROOT / 'content/reading_log.json', ROOT / '.cache-problemset.json'

def problemset():
    if not CACHE.exists():
        with urllib.request.urlopen('https://codeforces.com/api/problemset.problems', timeout=60) as r:
            CACHE.write_text(json.dumps({f"{p['contestId']}{p['index']}": p for p in json.load(r)['result']['problems']}))
    return json.loads(CACHE.read_text())

def main():
    data = json.load(sys.stdin)
    bank = json.loads(BANK.read_text()) if BANK.exists() else []
    log = json.loads(LOG.read_text()) if LOG.exists() else {}
    known, have = problemset(), {p['id'] for p in bank}
    today = datetime.date.today().isoformat()
    for code, reason in data.get('dropped', {}).items():
        log[code] = 'dropped: ' + reason
    for e in data.get('kept', []):
        code = e.pop('code')
        api = known[code]
        contest, index = api['contestId'], api['index']
        entry = {'id': f'cf-{code}', 'site': 'Codeforces', 'contest': contest, 'index': index, 'title': api['name'], 'rating': api['rating'],
                 'url': f'https://codeforces.com/contest/{contest}/problem/{index}', 'editorial': f"https://codeforces.com/blog/entry/{e.pop('tut')}",
                 'ideas': e['ideas'], 'observations': e['observations'], 'nudges': e['nudges'], 'checked': today}
        if entry['id'] in have:
            bank = [entry if p['id'] == entry['id'] else p for p in bank]
        else:
            bank.append(entry); have.add(entry['id'])
        log[code] = 'kept'
    bank.sort(key=lambda p: (p['rating'], p['id']))
    BANK.write_text(json.dumps(bank, indent=1, ensure_ascii=False) + '\n')
    LOG.write_text(json.dumps(log, indent=1, sort_keys=True) + '\n')
    print(len(bank), 'problems;', sum(v == 'kept' for v in log.values()), 'kept,', sum(v != 'kept' for v in log.values()), 'dropped')

main()
