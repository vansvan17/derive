#!/usr/bin/env python3
"""Check the course content before it is trusted.

1. Structure: every rule in derive.content.problems (references resolve, a chain
   never names its result early, nudges are questions, and so on).
2. Answers: every stored answer is recomputed by the step's own brute-force
   "verify" code and must match; the stored answer must also pass the same
   checker the learner's answer goes through.
3. With --links: every real problem's page is fetched, and for Codeforces the
   rating is re-read from the official API.

Exit status 0 only when nothing is wrong.
"""
from __future__ import annotations
import argparse
from fractions import Fraction
import json
import math
from pathlib import Path
import sys
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from derive import checks, content as content_module  # noqa: E402


def brute(code, variables=None):
    """Run a step's verify code (written by the course author, never by the learner) and return `result`."""
    scope = {'math': math, 'Fraction': Fraction, **(variables or {})}
    exec(code, scope)
    return scope.get('result')


def verify_step(tag, step):
    faults = []
    kind = step['kind']
    if kind in ('number', 'list'):
        want = brute(step['verify'])
        stored = step['answer']
        if want is None:
            faults.append(f'{tag}: the brute force did not produce a single value')
        elif kind == 'number' and Fraction(str(stored)) != Fraction(want):
            faults.append(f'{tag}: stored answer {stored} but brute force gives {want}')
        elif kind == 'list' and (list(stored) != list(want) if step.get('ordered') else sorted(stored) != sorted(want)):
            faults.append(f'{tag}: stored answer {stored} but brute force gives {want}')
        typed = ', '.join(map(str, stored)) if kind == 'list' else str(stored)
        if not checks.check(step, typed)[0]:
            faults.append(f'{tag}: the checker rejects the stored answer')
        wrong = str(stored + 1) if kind == 'number' else ', '.join(map(str, list(stored) + [987654]))
        if checks.check(step, wrong)[0]:
            faults.append(f'{tag}: the checker accepts a wrong answer')
    elif kind == 'formula':
        tested = 0
        for point in checks.sample_points(step['vars'], count=60):
            if 'verify_when' in step and not checks.evaluate(step['verify_when'], point, logic=True):
                continue
            want = brute(step['verify'], point)
            got = checks.evaluate(step['answer'], point)
            tested += 1
            if Fraction(got) != Fraction(want):
                faults.append(f'{tag}: formula gives {got} at {point} but brute force gives {want}')
                break
        if tested < 5:
            faults.append(f'{tag}: only {tested} points could be brute-forced; widen the ranges')
        if not checks.check(step, step['answer'])[0]:
            faults.append(f'{tag}: the checker rejects the stored formula')
        if checks.check(step, f'({step["answer"]})+1')[0]:
            faults.append(f'{tag}: the checker accepts a wrong formula')
    elif kind == 'counterexample':
        for values in step['verify']['works']:
            if not checks.check(step, ', '.join(map(str, values)))[0]:
                faults.append(f'{tag}: {values} should be accepted and is not')
        for values in step['verify']['fails']:
            try:
                accepted = checks.check(step, ', '.join(map(str, values)))[0]
            except checks.CheckError:
                accepted = False
            if accepted:
                faults.append(f'{tag}: {values} should be refused and is accepted')
        if not step['verify']['works'] or not step['verify']['fails']:
            faults.append(f'{tag}: needs at least one example that works and one that fails')
    elif kind == 'choice':
        if checks.check(step, (step['answer'] + 1) % len(step['options']))[0]:
            faults.append(f'{tag}: the checker accepts a wrong option')
    return faults


def verify_links(course):
    faults = []
    ratings = {}
    if any(p['site'] == 'Codeforces' for p in course.problems.values()):
        with urllib.request.urlopen(urllib.request.Request('https://codeforces.com/api/problemset.problems', headers={'User-Agent': 'derive-verify/1.0'}), timeout=60) as reply:
            for p in json.load(reply)['result']['problems']:
                ratings[(p.get('contestId'), p.get('index'))] = (p.get('rating'), p.get('name'))
    for problem in course.problems.values():
        tag = f'problem {problem["id"]}'
        if problem['site'] == 'Codeforces':
            found = ratings.get((problem.get('contest'), problem.get('index')))
            if not found:
                faults.append(f'{tag}: not in the Codeforces problem set')
            elif found[0] != problem['rating']:
                faults.append(f'{tag}: rating {problem["rating"]} here, {found[0]} on Codeforces')
            elif found[1] != problem['title']:
                faults.append(f'{tag}: title "{problem["title"]}" here, "{found[1]}" on Codeforces')
            continue
        try:
            request = urllib.request.Request(problem['url'], headers={'User-Agent': 'Mozilla/5.0 derive-verify/1.0'})
            with urllib.request.urlopen(request, timeout=30) as reply:
                if reply.status != 200:
                    faults.append(f'{tag}: page answered {reply.status}')
        except Exception as exc:  # any failure to load the page is a fault to look at
            faults.append(f'{tag}: page could not be loaded ({exc})')
    return faults


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--links', action='store_true', help='also fetch every problem page and re-read ratings')
    args = parser.parse_args()
    course = content_module.Content(ROOT)
    faults = content_module.problems(course)
    steps = 0
    for idea, chain in course.chains.items():
        for step in chain['steps']:
            steps += 1
            try:
                faults += verify_step(f'chain {idea} step {step["id"]}', step)
            except Exception as exc:  # a crash in verify code is itself a content fault
                faults.append(f'chain {idea} step {step["id"]}: verification crashed: {exc!r}')
    if args.links:
        faults += verify_links(course)
    for fault in faults:
        print('FAULT', fault)
    print(f'{len(course.ideas)} ideas, {len(course.links)} links, {len(course.chains)} chains, {steps} steps, {len(course.problems)} problems: '
          + ('all checks passed' if not faults else f'{len(faults)} fault(s)'))
    return 1 if faults else 0


if __name__ == '__main__':
    raise SystemExit(main())
