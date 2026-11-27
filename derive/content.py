"""Loading and checking the course content: ideas, their links, chains and real problems."""
from __future__ import annotations
import json
from pathlib import Path

LINK_KINDS = ('used to prove', 'special case of', 'combines with')
STEP_KINDS = ('number', 'list', 'choice', 'formula', 'counterexample', 'proof', 'code')
SITES = ('Codeforces', 'AtCoder', 'CSES')


class Content:
    def __init__(self, root):
        self.root = Path(root)
        data = json.loads((self.root / 'content/ideas.json').read_text())
        self.areas = data['areas']
        self.ideas = {i['id']: i for i in data['ideas']}
        self.order = [i['id'] for i in data['ideas']]
        self.links = json.loads((self.root / 'content/links.json').read_text())
        # The CSES dynamic programming section: one chain per CSES task, grouped by topic. They are chains like the
        # others (same steps, same checking) but they are not dots on the map, so they stay out of `order`.
        path = self.root / 'content/cses_dp.json'
        self.cses = json.loads(path.read_text()) if path.exists() else {'topics': [], 'problems': []}
        for p in self.cses['problems']:
            self.ideas[p['id']] = {'id': p['id'], 'area': 'dp', 'name': p['name'], 'statement': p['statement'], 'needs': [], 'marks': ['standard'],
                                   'track': 'cses', 'cses': {'title': p['title'], 'url': p['url'], 'topic': p['topic']}}
        self.chains = {}
        for path in sorted((self.root / 'content/chains').glob('*.json')):
            chain = json.loads(path.read_text())
            self.chains[chain['idea']] = chain
        path = self.root / 'content/problems.json'
        self.problems = {p['id']: p for p in json.loads(path.read_text())} if path.exists() else {}
        # Unrated practice tasks (CSES) offered once an idea's chain is finished.
        path = self.root / 'content/practice.json'
        self.practice = json.loads(path.read_text()) if path.exists() else {}
        for p in self.cses['problems']:                       # after its chain, the task itself is the practice
            self.practice[p['id']] = [{'site': 'CSES', 'title': p['title'], 'url': p['url'], 'checked': p['checked']}]
        # Short single-question puzzles, grouped in sets (invariants, games, bits).
        path = self.root / 'content/puzzles.json'
        self.puzzles = json.loads(path.read_text()) if path.exists() else {'sets': [], 'puzzles': []}
        # Implement tasks: code written by the learner and judged locally.
        path = self.root / 'content/tasks.json'
        self.tasks = {t['id']: t for t in json.loads(path.read_text())} if path.exists() else {}
        self.task_tracks = [{'id': 'core', 'title': 'Arrays and counting', 'about': 'Plain statements, no hint about technique. The obvious loop is too slow.'},
                            {'id': 'standard', 'title': 'Standard moves', 'about': 'Here the technique is named and nothing has to be discovered. The job is to write it quickly and get it accepted on the first submission.'},
                            {'id': 'graphs', 'title': 'Graphs and trees, from the adjacency list up', 'about': 'A ladder: each task asks for exactly one thing, and each builds on the one before.'},
                            {'id': 'numbers', 'title': 'Numbers', 'about': 'Primes, factors, powers and binomials at contest sizes.'},
                            {'id': 'structures', 'title': 'Structures and graph algorithms', 'about': 'The standard machinery, written by you.'},
                            {'id': 'tables', 'title': 'Tables and orders', 'about': 'Filling a table in the right order, and sorting by the right key.'},
                            {'id': 'bits', 'title': 'Bits and games', 'about': 'XOR, masks, and positions that win or lose.'},
                            {'id': 'strings', 'title': 'Strings', 'about': 'Matching without comparing letter by letter.'},
                            {'id': 'toolbox', 'title': 'From the toolbox', 'about': 'The tasks that go with the Toolbox pages.'}]
        # Toolbox pages: techniques that are recognised and written rather than derived.
        path = self.root / 'content/tools.json'
        self.tools = {t['id']: t for t in json.loads(path.read_text())} if path.exists() else {}
        # Real problems read and tagged but below the working level: never handed out under Solve, used by the recognition drill.
        path = self.root / 'content/parked_below_1600.json'
        self.parked = {p['id']: p for p in json.loads(path.read_text())} if path.exists() else {}
        # Break it: wrong solutions to existing tasks, to be broken with an input.
        path = self.root / 'content/breaks.json'
        self.breaks = {b['id']: b for b in json.loads(path.read_text())} if path.exists() else {}
        # Past ICPC regional papers: links only, shown on the contest page.
        path = self.root / 'content/papers.json'
        self.papers = json.loads(path.read_text()) if path.exists() else []

    def step(self, idea, step_id):
        chain = self.chains.get(idea)
        if not chain:
            raise KeyError('This idea has no chain yet.')
        for index, step in enumerate(chain['steps']):
            if step['id'] == step_id:
                return index, step
        raise KeyError('Unknown step.')

    def task_basis(self, task_id):
        """What a task rests on: the chains that end in it or that it names, and the Toolbox page it belongs to."""
        tool = next((t for t in self.tools.values() if t['task'] == task_id), None)
        named = [*self.tasks[task_id].get('needs', []), *(tool.get('needs', []) if tool else [])]
        in_chain = [idea for idea, chain in self.chains.items() if any(s.get('task') == task_id for s in chain['steps'])]
        ideas = [i for i in dict.fromkeys([*in_chain, *named]) if i in self.chains]
        return ideas, tool

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
        if any(m not in ('standard', 'common') for m in idea.get('marks', [])):
            faults.append(f'idea {idea.get("id")}: marks may only be standard and common')
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
            # A code step is judged by running the program; a failing small test is its nudge, so it may have none.
            if not (0 if step.get('kind') == 'code' else 1) <= len(step.get('nudges', [])) <= 3:
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
            if kind == 'code' and step.get('task') not in content.tasks:
                faults.append(f'{tag}: a code step must name an existing task')
            if kind == 'formula' and not step.get('vars'):
                faults.append(f'{tag}: formula needs variable ranges')
            if kind == 'counterexample' and not (step.get('vars') and step.get('property') and step.get('bounds')):
                faults.append(f'{tag}: counterexample needs vars, bounds and a property')
            if kind == 'proof' and not 2 <= len(step.get('claims', [])) <= 6:
                faults.append(f'{tag}: proof needs two to six required claims')
    seen_puzzles, set_ids = set(), {s['id'] for s in content.puzzles['sets']}
    for puzzle in content.puzzles['puzzles']:
        tag = f'puzzle {puzzle.get("id")}'
        if puzzle.get('id') in seen_puzzles:
            faults.append(f'{tag}: id used twice')
        seen_puzzles.add(puzzle.get('id'))
        if puzzle.get('set') not in set_ids:
            faults.append(f'{tag}: unknown set')
        if puzzle.get('kind') not in ('number', 'list', 'choice'):
            faults.append(f'{tag}: a puzzle is a number, a list or a choice')
        if not puzzle.get('prompt') or not puzzle.get('showed'):
            faults.append(f'{tag}: needs a prompt and the one-line reason shown afterwards')
        # A judged puzzle is a multiple-choice call about method; it has no computable answer and says so on the page.
        if not puzzle.get('verify') and not (puzzle.get('judged') and puzzle.get('kind') == 'choice'):
            faults.append(f'{tag}: needs brute-force "verify" code')
    for task in content.tasks.values():
        tag = f'task {task.get("id")}'
        for key in ('title', 'statement', 'code'):
            if not task.get(key):
                faults.append(f'{tag}: missing {key}')
        if not task.get('samples'):
            faults.append(f'{tag}: needs at least one sample')
    for tool in content.tools.values():
        tag = f'tool {tool.get("id")}'
        for key in ('title', 'when', 'idea', 'traps', 'reference'):
            if not tool.get(key):
                faults.append(f'{tag}: missing {key}')
        if tool.get('task') not in content.tasks:
            faults.append(f'{tag}: must name an existing task')
        marks = tool.get('marks', [])
        if not isinstance(marks, list) or any(m not in ('standard', 'common') for m in marks):
            faults.append(f'{tag}: marks may only be standard and common')
    for idea, tasks in content.practice.items():
        if idea not in content.chains:
            faults.append(f'practice {idea}: practice is offered after a chain, and this idea has none')
        for task in tasks:
            if not (task.get('title') and task.get('checked') and str(task.get('url', '')).startswith('https://cses.fi/problemset/task/')):
                faults.append(f'practice {idea}: each task needs a title, a CSES link and the date it was read')
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
        if not isinstance(problem.get('rating'), int) or not 1600 <= problem['rating'] <= 3000:
            faults.append(f'{tag}: rating must be a whole number from the source, 1600 or above (below that is chains only)')
        for nudge in problem.get('nudges', []):
            if not nudge.rstrip().endswith('?'):
                faults.append(f'{tag}: a nudge must be a question')
    return faults
