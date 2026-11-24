"""Loading and checking the course content: ideas, their links, chains and real problems."""
from __future__ import annotations
import json
from pathlib import Path

LINK_KINDS = ('used to prove', 'special case of', 'combines with')
STEP_KINDS = ('number', 'list', 'choice', 'formula', 'counterexample', 'proof')
SITES = ('Codeforces', 'AtCoder', 'CSES')


class Content:
    def __init__(self, root):
        self.root = Path(root)
        data = json.loads((self.root / 'content/ideas.json').read_text())
        self.areas = data['areas']
        self.ideas = {i['id']: i for i in data['ideas']}
        self.order = [i['id'] for i in data['ideas']]
        self.links = json.loads((self.root / 'content/links.json').read_text())
        self.chains = {}
        for path in sorted((self.root / 'content/chains').glob('*.json')):
            chain = json.loads(path.read_text())
            self.chains[chain['idea']] = chain
        path = self.root / 'content/problems.json'
        self.problems = {p['id']: p for p in json.loads(path.read_text())} if path.exists() else {}

    def step(self, idea, step_id):
        chain = self.chains.get(idea)
        if not chain:
            raise KeyError('This idea has no chain yet.')
        for index, step in enumerate(chain['steps']):
            if step['id'] == step_id:
                return index, step
        raise KeyError('Unknown step.')

    def problems_for(self, idea):
        return [p for p in self.problems.values() if idea in p['ideas']]

    def depth(self):
        """How many layers of other ideas each idea rests on (used to lay out the map)."""
        memo = {}

        def level(idea, trail=()):
            if idea in memo:
                return memo[idea]
            if idea in trail:
                raise ValueError('Ideas depend on each other in a circle: ' + ' -> '.join(trail + (idea,)))
            needs = self.ideas[idea].get('needs', [])
            memo[idea] = 1 + max((level(n, trail + (idea,)) for n in needs), default=-1)
            return memo[idea]
        return {i: level(i) for i in self.order}


def problems(content):
    """Every structural rule the content must obey. Returns a list of plain-language faults."""
    faults = []
    areas = {a['id'] for a in content.areas}
    for idea in content.ideas.values():
        for key in ('id', 'name', 'area', 'statement'):
            if not idea.get(key):
                faults.append(f'idea {idea.get("id")}: missing {key}')
        if idea.get('area') not in areas:
            faults.append(f'idea {idea["id"]}: unknown area {idea.get("area")}')
        for need in idea.get('needs', []):
            if need not in content.ideas:
                faults.append(f'idea {idea["id"]}: builds on unknown idea {need}')
    try:
        content.depth()
    except ValueError as exc:
        faults.append(str(exc))
    seen = set()
    for link in content.links:
        tag = f'link {link.get("from")} -> {link.get("to")}'
        if link.get('from') not in content.ideas or link.get('to') not in content.ideas:
            faults.append(f'{tag}: unknown idea')
        if link.get('kind') not in LINK_KINDS:
            faults.append(f'{tag}: kind must be one of {LINK_KINDS}')
        if not link.get('note'):
            faults.append(f'{tag}: needs a one-line reason')
        if (link.get('from'), link.get('to')) in seen:
            faults.append(f'{tag}: listed twice')
        seen.add((link.get('from'), link.get('to')))
    for idea, chain in content.chains.items():
        if idea not in content.ideas:
            faults.append(f'chain {idea}: no such idea')
            continue
        if not chain.get('opening'):
            faults.append(f'chain {idea}: needs an opening line')
        if chain.get('reveal', {}).get('name') != content.ideas[idea]['name']:
            faults.append(f'chain {idea}: the name revealed must match the idea name')
        if not chain.get('reveal', {}).get('statement'):
            faults.append(f'chain {idea}: the reveal needs the formal statement')
        ids = [s.get('id') for s in chain.get('steps', [])]
        if len(ids) != len(set(ids)):
            faults.append(f'chain {idea}: step ids repeat')
        if not 6 <= len(ids) <= 18:
            faults.append(f'chain {idea}: has {len(ids)} steps; a chain is 6 to 18')
        name = content.ideas[idea]['name'].casefold()
        for step in chain.get('steps', []):
            tag = f'chain {idea} step {step.get("id")}'
            if step.get('kind') not in STEP_KINDS:
                faults.append(f'{tag}: unknown kind {step.get("kind")}')
            for key in ('prompt', 'showed'):
                if not step.get(key):
                    faults.append(f'{tag}: missing {key}')
            # The whole point: the name is not said until the end.
            for text in [step.get('prompt', ''), step.get('showed', '')] + step.get('nudges', []):
                if name in text.casefold():
                    faults.append(f'{tag}: names the result before the reveal')
            if not 1 <= len(step.get('nudges', [])) <= 3:
                faults.append(f'{tag}: needs one to three nudges')
            for nudge in step.get('nudges', []):
                if not nudge.rstrip().endswith('?'):
                    faults.append(f'{tag}: a nudge must be a question: "{nudge[:50]}"')
            kind = step.get('kind')
            if kind == 'choice' and not (isinstance(step.get('options'), list) and 0 <= step.get('answer', -1) < len(step['options'])):
                faults.append(f'{tag}: choice needs options and a valid answer index')
            if kind in ('number', 'list', 'formula') and 'answer' not in step:
                faults.append(f'{tag}: missing answer')
            if kind in ('number', 'list', 'formula', 'counterexample') and not step.get('verify'):
                faults.append(f'{tag}: needs a "verify" expression so the stored answer can be recomputed')
            if kind == 'formula' and not step.get('vars'):
                faults.append(f'{tag}: formula needs variable ranges')
            if kind == 'counterexample' and not (step.get('vars') and step.get('property') and step.get('bounds')):
                faults.append(f'{tag}: counterexample needs vars, bounds and a property')
            if kind == 'proof' and not 2 <= len(step.get('claims', [])) <= 6:
                faults.append(f'{tag}: proof needs two to six required claims')
    for problem in content.problems.values():
        tag = f'problem {problem.get("id")}'
        if problem.get('site') not in SITES:
            faults.append(f'{tag}: site must be one of {SITES}')
        for key in ('url', 'title', 'checked'):
            if not problem.get(key):
                faults.append(f'{tag}: missing {key}')
        if not 1 <= len(problem.get('ideas', [])) <= 3:
            faults.append(f'{tag}: needs one to three ideas')
        for idea in problem.get('ideas', []):
            if idea not in content.ideas:
                faults.append(f'{tag}: unknown idea {idea}')
        if not 1 <= len(problem.get('observations', [])) <= 4:
            faults.append(f'{tag}: needs one to four observations')
        if not isinstance(problem.get('rating'), int) or not 800 <= problem['rating'] <= 3000:
            faults.append(f'{tag}: rating must be a whole number from the source')
        for nudge in problem.get('nudges', []):
            if not nudge.rstrip().endswith('?'):
                faults.append(f'{tag}: a nudge must be a question')
    return faults
