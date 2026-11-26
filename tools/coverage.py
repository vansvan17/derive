"""What follows each chain: how many real problems use its idea, by source.

    python3 tools/coverage.py          every chain, emptiest first
    python3 tools/coverage.py --empty  only the chains with nothing after them

The CSES chains are left out: each of those is itself a CSES task.
"""
import json, pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parent.parent
load = lambda name: json.loads((ROOT / 'content' / name).read_text())

def main():
    count = lambda rows, idea: sum(idea in p['ideas'] for p in rows)
    solve, easier, practice = load('problems.json'), load('parked_below_1600.json'), load('practice.json')
    rows = []
    for path in sorted((ROOT / 'content/chains').glob('*.json')):
        idea = json.loads(path.read_text())['idea']
        if idea.startswith('cses-'):
            continue
        rows.append((idea, count(solve, idea), count(easier, idea), len(practice.get(idea, []))))
    rows.sort(key=lambda r: (sum(r[1:]), r[0]))
    empty = [r for r in rows if not sum(r[1:])]
    if '--empty' not in sys.argv:
        print(f"{'chain':24}{'Solve set':>10}{'easier':>8}{'CSES':>6}")
        for r in rows:
            print(f'{r[0]:24}{r[1]:>10}{r[2]:>8}{r[3]:>6}')
    print(f'{len(rows)} chains: {len(rows) - len(empty)} followed by a real problem, {len(empty)} by none'
          + (': ' + ', '.join(r[0] for r in empty) if empty else ''))
    print(f'{sum(1 for r in rows if r[1] + r[2])} have a Codeforces problem, {sum(1 for r in rows if not (r[1] + r[2]) and r[3])} have CSES tasks only')

main()
