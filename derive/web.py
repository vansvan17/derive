"""The local app: a small HTTP server on 127.0.0.1 that serves the pages and a JSON API.

Nothing here talks to the internet except derive.sync (the learner's own public
submission list, when they ask) and derive.grader (the local Claude Code
command, when they have switched it on).
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import re
import secrets
import sys
import tempfile
import threading
from urllib.parse import parse_qs, unquote, urlparse
import uuid
import webbrowser

from . import breaks, contest, evidence, grader, recognise, session, stars, sync, tasks, tutor
from .checks import CheckError, check
from .content import Content
from .runner import Executable, JudgeError, same_output
from .store import Store, now

ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).with_name('static')
MAX_BODY = 2_000_000
CODE_LIMIT = 500_000
FILES = ('main', 'brute', 'gen')
RUN_SECONDS, RUN_MEMORY = 5, 512


class ApiError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def text(value, name, limit, required=False):
    if not isinstance(value, str):
        raise ApiError(f'{name} must be text.')
    if len(value.encode()) > limit:
        raise ApiError(f'{name} is too long.', 413)
    if required and not value.strip():
        raise ApiError(f'{name} is empty.')
    return value


class Service:
    def __init__(self, root=ROOT, data=None, static=STATIC):
        self.root = Path(root).resolve()
        self.data = Path(data).resolve() if data else self.root / '.data'
        self.static = Path(static).resolve()
        self.content = Content(self.root)
        self.csrf = secrets.token_urlsafe(32)
        self.lock = threading.RLock()            # one writer at a time keeps the record consistent
        self.workers = ThreadPoolExecutor(max_workers=1, thread_name_prefix='derive-run')
        self.tutors = ThreadPoolExecutor(max_workers=1, thread_name_prefix='derive-tutor')   # slow, so kept apart from code runs
        self.fetch = sync.fetch                  # replaced in tests with recorded replies
        self.grade = grader.grade
        self.teach = tutor.teach                 # replaced in tests
        self.stream = tutor.Stream()             # the conversation of a sitting, shown while it is written
        self.writing = {}                        # job -> what the tutor has written so far, the names to keep out, and what it was about
        self.cf_cache = {}                       # the Codeforces problem list, read once per launch
        with self.store() as store:
            store.run("UPDATE jobs SET status='error', result=?, updated=? WHERE status IN ('queued','running')",
                      (json.dumps({'error': 'The app restarted before this finished.'}), now()))
            store.run("UPDATE proofs SET status='awaiting' WHERE status='grading'")

    def store(self):
        return Store(self.data)

    def close(self):
        self.workers.shutdown(wait=False, cancel_futures=True)
        self.tutors.shutdown(wait=False, cancel_futures=True)
        self.stream.close()

    # ---------- settings ----------
    def settings(self, store):
        saved = store.get('settings', {})
        return {'language': 'cpp', 'cf_handle': '', 'atcoder_handle': '', 'grader': 'off', 'tutor': 'off', 'theme': 'light', 'font_size': 14, **saved}

    def save_settings(self, store, data):
        current = self.settings(store)
        for key, value in data.items():
            if key == 'language' and value in ('cpp', 'python'):
                current[key] = value
            elif key in ('cf_handle', 'atcoder_handle') and isinstance(value, str) and (value == '' or sync.HANDLE.fullmatch(value)):
                current[key] = value
            elif key == 'grader' and value in ('off', 'claude'):
                if value == 'claude' and not grader.available():
                    raise ApiError('The Claude Code command is not installed on this computer.')
                current[key] = value
            elif key == 'tutor' and value in ('off', 'codex'):
                if value == 'codex' and not tutor.available():
                    raise ApiError('The codex command is not installed on this computer.')
                current[key] = value
            elif key == 'theme' and value in ('light', 'dark', 'system'):
                current[key] = value
            elif key == 'font_size' and type(value) is int and 12 <= value <= 24:
                current[key] = value
            else:
                raise ApiError(f'That value for "{key}" is not allowed.')
        store.set('settings', current)
        return current

    # ---------- the map ----------
    def done_steps(self, store, idea):
        return {r['step']: r for r in store.all('SELECT * FROM steps_done WHERE idea=?', (idea,))}

    def derived(self, store):
        return {r['idea'] for r in store.all('SELECT idea FROM discoveries')}

    def chain_open(self, idea, derived, started=False):
        """A chain may be started once every idea it builds on that has a chain is derived.

        A chain already begun stays open: writing the chain of something it builds on must not lock it again."""
        return started or all(n in derived or n not in self.content.chains for n in self.content.ideas[idea].get('needs', []))

    def map(self, store):
        derived = self.derived(store)
        ev = evidence.idea_evidence(self.content, store)
        depth = self.content.depth()
        ideas = []
        for idea_id in self.content.order:
            idea = self.content.ideas[idea_id]
            chain = self.content.chains.get(idea_id)
            known = idea_id in derived
            ideas.append({
                'id': idea_id, 'area': idea['area'], 'level': depth[idea_id], 'needs': idea.get('needs', []),
                'derived': known, 'name': idea['name'] if known else None, 'statement': idea['statement'] if known else None,
                'marks': idea.get('marks', []), 'has_chain': bool(chain), 'open': bool(chain) and self.chain_open(idea_id, derived, bool(self.done_steps(store, idea_id))),
                'steps_total': len(chain['steps']) if chain else 0, 'steps_done': len(self.done_steps(store, idea_id)) if chain else 0,
                'evidence': ev[idea_id],
            })
        links = [{'from': l['from'], 'to': l['to'], 'kind': l['kind'],
                  # Why two ideas are connected is told only once both have been derived.
                  'note': l['note'] if l['from'] in derived and l['to'] in derived else None} for l in self.content.links]
        return {'areas': self.content.areas, 'ideas': ideas, 'links': links}

    def counts(self, store):
        rows = evidence.attempts(store)
        on_map = set(self.content.order)                 # the CSES chains are counted on their own page, not here
        return {'ideas': len(on_map), 'chains': sum(1 for i in self.content.chains if i in on_map), 'derived': len(self.derived(store) & on_map),
                'problems': len(self.content.problems), 'solved': sum(1 for r in rows.values() if r['solved_at']),
                'cold': sum(1 for r in rows.values() if evidence.is_cold(r))}

    def cses_page(self, store):
        """The CSES dynamic programming section: every task with its chain, grouped by topic."""
        derived = self.derived(store)
        ticked = set(store.get('practice_done', []))
        rows = []
        for p in self.content.cses['problems']:
            chain = self.content.chains.get(p['id'])
            known = p['id'] in derived
            rows.append({'id': p['id'], 'title': p['title'], 'url': p['url'], 'topic': p['topic'], 'has_chain': bool(chain),
                         'steps_total': len(chain['steps']) if chain else 0, 'steps_done': len(self.done_steps(store, p['id'])) if chain else 0,
                         'derived': known, 'lesson': p['name'] if known else None, 'accepted': p['url'] in ticked})
        return {'topics': self.content.cses['topics'], 'problems': rows}

    def next_chain(self, store):
        derived = self.derived(store)
        started = [i for i in self.content.order if i in self.content.chains and i not in derived and self.done_steps(store, i)]
        if started:
            return started[0]
        return next((i for i in self.content.order if i in self.content.chains and i not in derived and self.chain_open(i, derived)), None)

    def bootstrap(self, store):
        return {'csrf': self.csrf, 'settings': self.settings(store), 'grader_available': grader.available(), 'tutor_available': tutor.available(),
                'counts': self.counts(store), 'band': evidence.band(self.content, store),
                'open_problem': evidence.open_problem(store), 'next_chain': self.next_chain(store), 'stars': stars.keys(store),
                'session': session.status(self, store), 'voice': self.voice_on(store)}

    # ---------- chains ----------
    def nudges_open(self, store, scope, owner, step):
        return store.one('SELECT COALESCE(MAX(level),0) FROM nudges WHERE scope=? AND owner=? AND step=?', (scope, owner, step))[0]

    def public_step(self, store, idea, step, done):
        level = self.nudges_open(store, 'chain', idea, step['id'])
        out = {'id': step['id'], 'kind': step['kind'], 'prompt': step['prompt'], 'done': bool(done), 'hard': step.get('tier') == 'hard',
               'nudges': step.get('nudges', [])[:level], 'nudges_total': len(step.get('nudges', []))}
        if step['kind'] == 'choice':
            out['options'] = step['options']
        if step['kind'] in ('formula', 'counterexample'):
            out['vars'] = list(step['vars'])
        if step['kind'] == 'counterexample':
            out['bounds'] = step['bounds']
        if step['kind'] == 'code':
            out['task'] = step['task']
        if step['kind'] == 'proof':
            last = store.one("SELECT * FROM proofs WHERE scope='chain' AND owner=? AND step=? ORDER BY id DESC LIMIT 1", (idea, step['id']))
            out['proof'] = {'id': last['id'], 'text': last['text'], 'status': last['status'], 'feedback': json.loads(last['feedback'])} if last else None
        if done:
            out['answer'] = done['answer']
            if step['kind'] == 'proof':             # once the step is behind her, the argument itself may be read
                out['argument'] = step.get('claims', [])
            out['showed'] = step['showed']
        return out

    def chain(self, store, idea):
        if idea not in self.content.ideas:
            raise ApiError('No such idea.', 404)
        chain = self.content.chains.get(idea)
        if not chain:
            raise ApiError('The chain for this idea has not been written yet.', 404)
        derived = self.derived(store)
        if not self.chain_open(idea, derived, bool(self.done_steps(store, idea))) and idea not in derived:
            raise ApiError('This chain builds on something you have not derived yet.', 409)
        self.settle_code_steps(store, idea, chain)
        derived = self.derived(store)
        done = self.done_steps(store, idea)
        steps = []
        for step in chain['steps']:
            steps.append(self.public_step(store, idea, step, done.get(step['id'])))
            if step['id'] not in done:
                break                                  # later steps stay unseen until this one is right
        complete = idea in derived
        ticked = set(store.get('practice_done', []))
        info = self.content.ideas[idea]
        # What skipping leads to: the hard questions if the chain has them, otherwise just its final step (the proof).
        hard = self.unskippable(chain)
        return {'idea': idea, 'opening': chain['opening'], 'steps': steps, 'total': len(chain['steps']), 'complete': complete,
                'hard_total': len(hard), 'has_hard': any(s.get('tier') == 'hard' for s in chain['steps']),
                'can_skip': any(s['id'] not in done for s in chain['steps'] if s['id'] not in hard),
                'reveal': {**chain['reveal'], 'problems': len(self.content.problems_for(idea))} if complete else None,
                # Practice tasks would give the topic away, so they are listed only once the chain is finished.
                'practice': [{**t, 'done': t['url'] in ticked} for t in self.content.practice.get(idea, [])] if complete else [],
                'problems': self.chain_problems(store, idea, ticked) if complete else None,
                'marks': info.get('marks', []), 'cses': info.get('cses'), 'pattern': info.get('track') == 'pattern', 'notes': store.get('chain_notes', {}).get(idea, ''),
                'area': next(a['title'] for a in self.content.areas if a['id'] == info['area'])}

    def chain_problems(self, store, idea, ticked):
        """Real problems that use a derived idea: the easier ones Solve never hands out, and the ones in the Solve set."""
        rows = evidence.attempts(store)
        def state(p):
            row = rows.get(p['id'])
            return 'new' if not row else 'solved' if row['solved_at'] else 'gave up' if row['gave_up_at'] else 'open'
        return {'easier': [{'title': p['title'], 'site': p['site'], 'url': p['url'], 'rating': p['rating'], 'done': p['url'] in ticked}
                           for p in sorted(self.content.parked.values(), key=lambda p: p['rating']) if idea in p['ideas']],
                'set': [{'id': p['id'], 'title': p['title'], 'site': p['site'], 'rating': p['rating'], 'state': state(p), 'others': len(p['ideas']) - 1}
                        for p in sorted(self.content.problems_for(idea), key=lambda p: p['rating'])]}

    def open_from_chain(self, store, data):
        """Open a Solve-set problem from the end of a chain or from a Toolbox page. The topic is known, so it can count as applied but never as recognised."""
        problem = self.content.problems.get(data.get('id')) if isinstance(data.get('id'), str) else None
        idea, tool = data.get('idea'), data.get('tool')
        if tool is not None:
            page = self.content.tools.get(tool) if isinstance(tool, str) else None
            if not problem or not page or tool not in problem.get('tools', []) or not store.one('SELECT 1 FROM tasks_done WHERE task=?', (page['task'],)):
                raise ApiError('That problem is not listed under a Toolbox page you have written.', 404)
            known = 'tool:' + tool
        else:
            if not problem or idea not in problem['ideas'] or idea not in self.derived(store):
                raise ApiError('That problem is not listed under a chain you have finished.', 404)
            known = idea
        if not store.one('SELECT 1 FROM attempts WHERE problem=?', (problem['id'],)):
            store.run('INSERT INTO attempts(problem,opened_at,topic_known) VALUES(?,?,?)', (problem['id'], now(), known))
        return {'id': problem['id']}

    def settle_code_steps(self, store, idea, chain):
        """A code step is finished by the judge, not by a typed answer: once its task is accepted, the step is done."""
        while True:
            done = self.done_steps(store, idea)
            current = next((s for s in chain['steps'] if s['id'] not in done), None)
            if not current or current['kind'] != 'code' or not store.one('SELECT 1 FROM tasks_done WHERE task=?', (current['task'],)):
                return
            self.finish_step(store, idea, chain, current, 'accepted')

    def current_step(self, store, idea, step_id):
        chain = self.content.chains.get(idea)
        if not chain:
            raise ApiError('No such chain.', 404)
        done = self.done_steps(store, idea)
        current = next((s for s in chain['steps'] if s['id'] not in done), None)
        if not current or current['id'] != step_id:
            raise ApiError('That is not the step you are on.', 409)
        if not self.chain_open(idea, self.derived(store), bool(self.done_steps(store, idea))):
            raise ApiError('This chain builds on something you have not derived yet.', 409)
        return chain, current

    def finish_step(self, store, idea, chain, step, answer):
        store.run('INSERT OR IGNORE INTO steps_done VALUES(?,?,?,?)', (idea, step['id'], now(), answer))
        complete = step['id'] == chain['steps'][-1]['id']
        if complete:
            store.run('INSERT OR IGNORE INTO discoveries VALUES(?,?)', (idea, now()))
        return complete

    @staticmethod
    def unskippable(chain):
        """Steps that "Skip the warm-up" never skips: the hard part (or the final step if there is none), and every step where code is written."""
        hard = [s['id'] for s in chain['steps'] if s.get('tier') == 'hard'] or [chain['steps'][-1]['id']]
        return hard + [s['id'] for s in chain['steps'] if s['kind'] == 'code' and s['id'] not in hard]

    def skip_easy(self, store, data):
        """Too easy: mark the warm-up steps as skipped and go straight to the hard questions."""
        idea = data.get('idea')
        chain = self.content.chains.get(idea) if isinstance(idea, str) else None
        if not chain:
            raise ApiError('No such chain.', 404)
        keep = self.unskippable(chain)
        if not self.chain_open(idea, self.derived(store), bool(self.done_steps(store, idea))) and idea not in self.derived(store):
            raise ApiError('This chain builds on something you have not derived yet.', 409)
        for step in chain['steps']:
            if step['id'] not in keep:
                store.run('INSERT OR IGNORE INTO steps_done VALUES(?,?,?,?)', (idea, step['id'], now(), '(skipped)'))
        return self.chain(store, idea)

    def answer(self, store, data):
        idea, step_id = data.get('idea'), data.get('step')
        chain, step = self.current_step(store, idea, step_id)
        if step['kind'] == 'proof':
            raise ApiError('This step is a written proof.')
        if step['kind'] == 'code':
            raise ApiError('This step is finished by getting your program accepted.')
        raw = data.get('answer')
        raw = text(raw, 'Your answer', 2000) if isinstance(raw, str) else raw
        try:
            correct, message = check(step, raw)
        except CheckError as exc:
            # Unreadable input is not counted as a wrong attempt.
            return {'correct': False, 'unreadable': True, 'message': str(exc)}
        store.run('INSERT INTO step_attempts(at,idea,step,answer,correct) VALUES(?,?,?,?,?)', (now(), idea, step_id, str(raw)[:2000], int(correct)))
        if not correct:
            return {'correct': False, 'message': message}
        complete = self.finish_step(store, idea, chain, step, str(raw)[:2000])
        return {'correct': True, 'showed': step['showed'], 'complete': complete}

    def no_contest(self, store):
        if contest.active(store):
            raise ApiError('A contest is running: no nudges, tutor or editorials until it ends.', 409)

    def nudge(self, store, data):
        self.no_contest(store)
        if data.get('scope') == 'problem':
            problem, row = self.attempt(store, data.get('id'))
            if row['solved_at'] or row['gave_up_at']:
                raise ApiError('This problem is already finished.', 409)
            owner, step_id, available = problem['id'], '-', problem.get('nudges', [])
            scope = 'problem'
        else:
            _, step = self.current_step(store, data.get('idea'), data.get('step'))
            owner, step_id, available, scope = data['idea'], step['id'], step.get('nudges', []), 'chain'
        level = self.nudges_open(store, scope, owner, step_id) + 1
        if level > len(available):
            raise ApiError('There are no more nudges here.', 409)
        store.run('INSERT OR IGNORE INTO nudges VALUES(?,?,?,?,?)', (scope, owner, step_id, level, now()))
        return {'nudges': available[:level], 'nudges_total': len(available)}

    # ---------- proofs ----------
    def submit_proof(self, store, data):
        idea, step_id = data.get('idea'), data.get('step')
        chain, step = self.current_step(store, idea, step_id)
        if step['kind'] != 'proof':
            raise ApiError('This step is not a written proof.')
        body = text(data.get('text'), 'Your proof', 12000, required=True).strip()
        if len(body) < 40:
            raise ApiError('Write the argument out: the claim, and why it is true.')
        automatic = self.settings(store)['grader'] == 'claude'
        proof = store.run('INSERT INTO proofs(at,scope,owner,step,text,status) VALUES(?,?,?,?,?,?)',
                          (now(), 'chain', idea, step_id, body, 'grading' if automatic else 'awaiting')).lastrowid
        if not automatic:
            return {'proof': proof, 'status': 'awaiting'}
        job = self.queue(store, 'grade', {'proof': proof})
        return {'proof': proof, 'status': 'grading', 'job': job}

    def read_proof(self, store, data):
        """Writing a proof out is optional: in a contest you only need to be convinced. This finishes the step
        by showing the argument instead; it is recorded as read, not written."""
        idea, step_id = data.get('idea'), data.get('step')
        chain, step = self.current_step(store, idea, step_id)
        if step['kind'] != 'proof':
            raise ApiError('This step is not a written proof.')
        complete = self.finish_step(store, idea, chain, step, '(read, not written)')
        return {'complete': complete, 'argument': step.get('claims', [])}

    def apply_verdict(self, store, proof_id, verdict):
        row = store.one('SELECT * FROM proofs WHERE id=?', (proof_id,))
        status = 'pass' if verdict['pass'] else 'fail'
        store.run('UPDATE proofs SET status=?, feedback=?, graded_at=? WHERE id=?', (status, json.dumps(verdict), now(), proof_id))
        complete = False
        if verdict['pass']:
            chain = self.content.chains[row['owner']]
            _, step = self.content.step(row['owner'], row['step'])
            if row['step'] not in self.done_steps(store, row['owner']):
                complete = self.finish_step(store, row['owner'], chain, step, '(proof accepted)')
        return {'status': status, 'feedback': verdict, 'complete': complete}

    def proof_prompt(self, store, proof_id):
        row = store.one('SELECT * FROM proofs WHERE id=?', (proof_id,))
        if not row:
            raise ApiError('No such proof.', 404)
        _, step = self.content.step(row['owner'], row['step'])
        return {'id': row['id'], 'status': row['status'], 'prompt': grader.SYSTEM + '\n\n' + grader.build_prompt(step['prompt'], step['claims'], row['text'])}

    def manual_verdict(self, store, data):
        """A verdict pasted back from a Claude session the learner ran by hand."""
        row = store.one('SELECT * FROM proofs WHERE id=?', (data.get('proof'),))
        if not row or row['status'] in ('pass', 'grading'):
            raise ApiError('That proof is not waiting for a grade.', 409)
        _, step = self.content.step(row['owner'], row['step'])
        try:
            verdict = grader.parse(text(data.get('verdict'), 'The verdict', 20000, required=True), len(step['claims']))
        except (ValueError, TypeError) as exc:
            raise ApiError('That is not a verdict this page can read. Paste the whole JSON reply.') from exc
        return self.apply_verdict(store, row['id'], verdict)

    # ---------- real problems ----------
    def attempt(self, store, problem_id):
        problem = self.content.problems.get(problem_id) if isinstance(problem_id, str) else None
        if not problem:
            raise ApiError('No such problem.', 404)
        row = store.one('SELECT * FROM attempts WHERE problem=?', (problem_id,))
        if not row:
            raise ApiError('Open this problem first.', 409)
        return problem, row

    def problem(self, store, problem_id):
        problem = self.content.problems.get(problem_id)
        if not problem:
            raise ApiError('No such problem.', 404)
        row = store.one('SELECT * FROM attempts WHERE problem=?', (problem_id,))
        out = {'id': problem['id'], 'site': problem['site'], 'url': problem['url'], 'title': problem['title'], 'rating': problem['rating'],
               'opened': bool(row), 'verifiable': problem['site'] in ('Codeforces', 'AtCoder')}
        if not row:
            return out
        finished = bool(row['solved_at'] or row['gave_up_at'])
        level = self.nudges_open(store, 'problem', problem_id, '-')
        derived = self.derived(store)
        out.update({
            'approach': row['approach'], 'cue': row['cue'], 'committed': bool(row['committed_at']),
            'nudges': problem.get('nudges', [])[:level], 'nudges_total': len(problem.get('nudges', [])),
            'editorial_opened': bool(row['editorial_at']), 'solved': bool(row['solved_at']), 'gave_up': bool(row['gave_up_at']),
            'cold': bool(row['cold']), 'verdict_source': row['verdict_source'], 'cause': row['cause'], 'notes': row['notes'], 'move': row['move'], 'move_made': row['move_made'], 'lesson': row['lesson'],
            'returned_for': bool(row['returned_for']), 'finished': finished, 'topic_known': bool(row['topic_known']),
        })
        if row['editorial_at'] or finished:
            out['editorial'] = problem.get('editorial')
        if finished:
            # Only now: what cracked it, and which ideas it rested on.
            out['observations'] = problem['observations']
            out['ideas'] = [{'id': i, 'derived': i in derived, 'name': self.content.ideas[i]['name'] if i in derived else None,
                             'has_chain': i in self.content.chains} for i in problem['ideas']]
        return out

    def open_next(self, store):
        problem_id, why = evidence.next_problem(self.content, store)
        if not problem_id:
            return {'id': None}
        if not store.one('SELECT 1 FROM attempts WHERE problem=?', (problem_id,)):
            store.run('INSERT INTO attempts(problem,opened_at,returned_for) VALUES(?,?,?)', (problem_id, now(), why[7:] if why.startswith('return:') else None))
        return {'id': problem_id}

    def commit(self, store, data):
        problem, row = self.attempt(store, data.get('id'))
        if row['committed_at']:
            raise ApiError('Your first approach is already recorded; it cannot be rewritten.', 409)
        approach = text(data.get('approach'), 'Your approach', 6000, required=True).strip()
        cue = text(data.get('cue'), 'The cue', 2000).strip()
        if not approach:
            raise ApiError('Write the approach first, or leave this part out: it is optional.')
        store.run('UPDATE attempts SET approach=?, cue=?, committed_at=? WHERE problem=?', (approach, cue, now(), problem['id']))
        return self.problem(store, problem['id'])

    def editorial(self, store, data):
        self.no_contest(store)
        problem, row = self.attempt(store, data.get('id'))
        if not row['editorial_at']:
            store.run('UPDATE attempts SET editorial_at=? WHERE problem=?', (now(), problem['id']))
        return self.problem(store, problem['id'])

    def finish(self, store, problem, row, source, submission=None, before_open=False):
        tutored = store.one("SELECT 1 FROM tutor_uses WHERE scope='problem' AND owner=? AND gated=1", (problem['id'],))
        helped = bool(self.nudges_open(store, 'problem', problem['id'], '-') or row['editorial_at'] or tutored)
        cold = source == 'judge' and not helped and not before_open and not row['topic_known']
        store.run('UPDATE attempts SET solved_at=?, verdict_source=?, submission=?, cold=? WHERE problem=?',
                  (now(), source, submission, int(cold), problem['id']))
        if cold:
            evidence.settle_returns(store, problem)
        elif helped:
            evidence.schedule_returns(self.content, store, problem, 'solved with help')
        return {'cold': cold, 'band_raised_to': evidence.raise_band(self.content, store)}

    def check_submissions(self, store, data):
        problem, row = self.attempt(store, data.get('id'))
        if row['solved_at']:
            return {**self.problem(store, problem['id']), 'found': True}
        handle = self.settings(store)['cf_handle' if problem['site'] == 'Codeforces' else 'atcoder_handle']
        try:
            hit = sync.accepted(problem, handle, row['opened_at'], self.fetch)
        except sync.SyncError as exc:
            raise ApiError(str(exc), 502 if 'reach' in str(exc) else 400) from exc
        if not hit:
            return {**self.problem(store, problem['id']), 'found': False}
        result = self.finish(store, problem, row, 'judge', hit['id'], hit['before_open'])
        return {**self.problem(store, problem['id']), 'found': True, 'before_open': hit['before_open'], **result}

    def report(self, store, data):
        problem, row = self.attempt(store, data.get('id'))
        if problem['site'] in ('Codeforces', 'AtCoder'):
            raise ApiError('This site can be checked directly; use "Check my submissions".')
        if row['solved_at'] or row['gave_up_at']:
            raise ApiError('This problem is already finished.', 409)
        result = self.finish(store, problem, row, 'self')
        return {**self.problem(store, problem['id']), **result}

    def give_up(self, store, data):
        problem, row = self.attempt(store, data.get('id'))
        if row['solved_at'] or row['gave_up_at']:
            raise ApiError('This problem is already finished.', 409)
        store.run('UPDATE attempts SET gave_up_at=?, cold=0 WHERE problem=?', (now(), problem['id']))
        evidence.schedule_returns(self.content, store, problem, 'gave up')
        return self.problem(store, problem['id'])

    def cause(self, store, data):
        problem, row = self.attempt(store, data.get('id'))
        if not (row['solved_at'] or row['gave_up_at']):
            raise ApiError('Finish the problem before recording why it went as it did.', 409)
        cause = data.get('cause')
        if cause not in evidence.CAUSES and cause != 'none':
            raise ApiError('Pick one of the listed causes.')
        if cause == 'none' and not row['cold']:
            raise ApiError('This was not a cold solve, so something was in the way. Pick what it was.')
        store.run('UPDATE attempts SET cause=? WHERE problem=?', (cause, problem['id']))
        return self.problem(store, problem['id'])

    def move(self, store, data):
        """After a problem: which move cracks it, whether she made it herself, and the lesson in a sentence."""
        problem, row = self.attempt(store, data.get('id'))
        if not (row['solved_at'] or row['gave_up_at']):
            raise ApiError('Finish the problem before recording the move that cracks it.', 409)
        if 'move' in data:
            if data['move'] not in evidence.MOVES:
                raise ApiError('Pick one of the listed moves.')
            store.run('UPDATE attempts SET move=? WHERE problem=?', (data['move'], problem['id']))
        if 'made' in data:
            if type(data['made']) is not bool:
                raise ApiError('Say whether you made the move yourself.')
            store.run('UPDATE attempts SET move_made=? WHERE problem=?', (int(data['made']), problem['id']))
        if 'lesson' in data:
            store.run('UPDATE attempts SET lesson=? WHERE problem=?', (text(data['lesson'], 'The lesson', 600).strip(), problem['id']))
        return self.problem(store, problem['id'])

    # ---------- puzzles ----------
    def puzzles(self, store, which, at=None):
        """The sets with their progress, and the next unsolved puzzle of the chosen set."""
        done = {r['puzzle']: r for r in store.all('SELECT * FROM puzzles_done')}
        sets = []
        for s in self.content.puzzles['sets']:
            mine = [p for p in self.content.puzzles['puzzles'] if p['set'] == s['id']]
            sets.append({'id': s['id'], 'title': s['title'], 'about': s.get('about', ''), 'total': len(mine),
                         'done': sum(1 for p in mine if p['id'] in done),
                         'first_try': sum(1 for p in mine if p['id'] in done and not done[p['id']]['wrong'] and not done[p['id']]['shown'])})
        chosen = which if any(s['id'] == which for s in sets) else (sets[0]['id'] if sets else None)
        mine = [p for p in self.content.puzzles['puzzles'] if p['set'] == chosen]
        # The frontier is the first unfinished puzzle. You may look back at anything before it, not ahead of it.
        frontier = next((i for i, p in enumerate(mine) if p['id'] not in done), len(mine))
        position = at if isinstance(at, int) and 0 <= at <= min(frontier, len(mine) - 1) else frontier
        public = None
        if position < len(mine):
            todo = mine[position]
            public = {'id': todo['id'], 'kind': todo['kind'], 'prompt': todo['prompt'], 'options': todo.get('options'), 'judged': bool(todo.get('judged')),
                      'wrong': store.one('SELECT COUNT(*) FROM puzzle_tries WHERE puzzle=? AND correct=0', (todo['id'],))[0]}
            if todo['id'] in done:
                row = done[todo['id']]
                last = store.one('SELECT answer FROM puzzle_tries WHERE puzzle=? AND correct=1 ORDER BY id DESC LIMIT 1', (todo['id'],))
                public['finished'] = {'shown': bool(row['shown']), 'first_try': not row['wrong'] and not row['shown'], 'showed': todo['showed'],
                                      'yours': last['answer'] if last else None}
        return {'sets': sets, 'set': chosen, 'puzzle': public, 'position': position, 'frontier': frontier, 'count': len(mine)}

    def puzzle_answer(self, store, data):
        puzzle = next((p for p in self.content.puzzles['puzzles'] if p['id'] == data.get('id')), None)
        if not puzzle:
            raise ApiError('No such puzzle.', 404)
        if store.one('SELECT 1 FROM puzzles_done WHERE puzzle=?', (puzzle['id'],)):
            raise ApiError('That puzzle is already finished.', 409)
        wrong = store.one('SELECT COUNT(*) FROM puzzle_tries WHERE puzzle=? AND correct=0', (puzzle['id'],))[0]
        if data.get('show'):
            # Giving up shows the reason; it is recorded as shown, never as solved.
            store.run('INSERT INTO puzzles_done VALUES(?,?,?,1)', (puzzle['id'], now(), wrong))
            return {'correct': False, 'shown': True, 'showed': puzzle['showed']}
        raw = data.get('answer')
        raw = text(raw, 'Your answer', 2000) if isinstance(raw, str) else raw
        try:
            correct, message = check(puzzle, raw)
        except CheckError as exc:
            return {'correct': False, 'unreadable': True, 'message': str(exc)}
        store.run('INSERT INTO puzzle_tries(at,puzzle,answer,correct) VALUES(?,?,?,?)', (now(), puzzle['id'], str(raw)[:2000], int(correct)))
        if not correct:
            return {'correct': False, 'message': message}
        store.run('INSERT INTO puzzles_done VALUES(?,?,?,0)', (puzzle['id'], now(), wrong))
        return {'correct': True, 'showed': puzzle['showed'], 'first_try': wrong == 0}

    # ---------- implement tasks ----------
    def task_basis(self, store, task_id, derived=None):
        """What to point at before a task: chains not derived yet (never named) and a Toolbox page not done yet. Empty once she has them."""
        derived = self.derived(store) if derived is None else derived
        ideas, tool = self.content.task_basis(task_id)
        area = {a['id']: a['title'] for a in self.content.areas}
        out = [{'kind': 'chain', 'id': i, 'area': area[self.content.ideas[i]['area']]} for i in ideas if i not in derived]
        if tool and not store.one('SELECT 1 FROM tasks_done WHERE task=?', (task_id,)):
            out.append({'kind': 'tool', 'id': tool['id'], 'title': tool['title']})
        return out

    def task(self, store, task_id):
        task = self.content.tasks.get(task_id)
        if not task:
            raise ApiError('No such task.', 404)
        opened = self.nudges_open(store, 'task', task_id, '-')
        # Only the hints already opened are sent; the rest stay on the server.
        shown = tasks.public(task, store)
        return {**shown, 'statement': task['statement'], 'samples': task['samples'], 'seconds': task.get('seconds', 1.0),
                'hints': task['hints'][:opened], 'hints_total': len(task['hints']), 'basis': self.task_basis(store, task_id), 'behind': self.task_behind(store, task),
                'found': self.task_found(task, shown['solved'], opened)}

    def task_found(self, task, solved, opened):
        """How the idea could have been found, and the name of the move. It gives the whole problem away, so it is sent
        only once the task is accepted or every hint is already open."""
        found = task.get('found')
        if not found or not (solved or opened >= len(task['hints'])):
            return None
        return {**found, 'move_label': evidence.MOVES[found['move']]}

    def thinking_patterns(self, store):
        """The thinking patterns for the Think it up page. A pattern has no name there until its chain is derived."""
        derived = self.derived(store)
        started = {r['idea'] for r in store.all('SELECT DISTINCT idea FROM steps_done')}
        return [{'id': p['id'], 'name': p['name'] if p['id'] in derived else None, 'statement': p['statement'] if p['id'] in derived else None,
                 'derived': p['id'] in derived, 'started': p['id'] in started, 'steps': len(self.content.chains[p['id']]['steps'])} for p in self.content.patterns]

    def task_behind(self, store, task):
        """For a prediction: the chains and Toolbox pages that teach what it needs. Sent to the page, which keeps it folded
        until she asks. A chain she has not derived is given by its area only, never by its name."""
        derived = self.derived(store)
        area = {a['id']: a['title'] for a in self.content.areas}
        out = [{'kind': 'chain', 'id': i, 'area': area[self.content.ideas[i]['area']], 'name': self.content.ideas[i]['name'] if i in derived else None}
               for i in task.get('behind', []) if i in self.content.ideas]
        return out + [{'kind': 'tool', 'id': t, 'title': self.content.tools[t]['title']} for t in task.get('behind_pages', []) if t in self.content.tools]

    def task_hint(self, store, data):
        """Open the next hint of a task. Hints come one at a time, in order: a question, the observation, then the plan."""
        self.no_contest(store)
        task = self.content.tasks.get(data.get('id')) if isinstance(data.get('id'), str) else None
        if not task:
            raise ApiError('No such task.', 404)
        level = self.nudges_open(store, 'task', task['id'], '-') + 1
        if level > len(task['hints']):
            raise ApiError('There are no more hints for this task.', 409)
        store.run('INSERT OR IGNORE INTO nudges VALUES(?,?,?,?,?)', ('task', task['id'], '-', level, now()))
        return {'hints': task['hints'][:level], 'hints_total': len(task['hints']), 'found': self.task_found(task, False, level)}

    def task_judge(self, store, data):
        task = self.content.tasks.get(data.get('id')) if isinstance(data.get('id'), str) else None
        language = data.get('language')
        if not task or language not in ('cpp', 'python'):
            raise ApiError('That cannot be judged.')
        source = text(data.get('main'), 'Your code', CODE_LIMIT, required=True)
        self.save_code(store, {'id': task['id'], 'language': language, 'file': 'main', 'code': source})
        return {'job': self.queue(store, 'judge', {'task': task['id'], 'language': language, 'main': source})}

    def work_judge(self, store, payload):
        task = self.content.tasks[payload['task']]
        result = tasks.judge(task, payload['language'], payload['main'])
        store.run('INSERT INTO task_tries(at,task,verdict) VALUES(?,?,?)', (now(), task['id'], result['verdict']))
        if result['verdict'] == 'AC':
            tries = store.one('SELECT COUNT(*) FROM task_tries WHERE task=?', (task['id'],))[0]
            store.run('INSERT OR IGNORE INTO tasks_done VALUES(?,?,?)', (task['id'], now(), tries))
            store.run('INSERT OR REPLACE INTO accepted_code VALUES(?,?,?,?)', (task['id'], payload['language'], payload['main'], now()))
        return result

    # ---------- break it ----------
    def break_item(self, data):
        item = self.content.breaks.get(data.get('id')) if isinstance(data.get('id'), str) else None
        if not item:
            raise ApiError('No such page.', 404)
        return item

    def break_try(self, store, data):
        item = self.break_item(data)
        typed = data.get('input') if isinstance(data.get('input'), str) else ''
        reason = breaks.invalid(item, typed)
        if reason:
            return {'valid': False, 'reason': reason}
        return {'valid': True, 'job': self.queue(store, 'break', {'item': item['id'], 'input': typed})}

    def break_nudge(self, store, data):
        item = self.break_item(data)
        self.no_contest(store)
        opened = store.one("SELECT COUNT(*) FROM nudges WHERE scope='break' AND owner=?", (item['id'],))[0]
        if opened < len(item['nudges']):
            store.run('INSERT OR IGNORE INTO nudges VALUES(?,?,?,?,?)', ('break', item['id'], '', opened + 1, now()))
        return breaks.page(self.content, store, item)

    def work_break(self, store, payload):
        item = self.content.breaks[payload['item']]
        result = breaks.attempt(item, self.content.tasks[item['task']], payload['input'])
        with self.lock:
            breaks.record(store, item, payload['input'], result)
        if result['verdict'] == 'BROKEN':
            result['why'] = item['why']
        return result

    # ---------- the toolbox ----------
    def tool_list(self, store):
        done = {r['task'] for r in store.all('SELECT task FROM tasks_done')}
        return {'tools': [{'id': t['id'], 'title': t['title'], 'when': t['when'][0], 'marks': t.get('marks', []), 'written': t['task'] in done} for t in self.content.tools.values()]}

    def tool(self, store, tool_id):
        tool = self.content.tools.get(tool_id)
        if not tool:
            raise ApiError('No such page.', 404)
        written = bool(store.one('SELECT 1 FROM tasks_done WHERE task=?', (tool['task'],)))
        out = {k: tool[k] for k in ('id', 'title', 'when', 'idea', 'traps', 'task')}
        out['example'] = tool.get('example')                      # the core lines in C++, shown with the idea
        out['practice'] = tool.get('practice', [])                # standard tasks elsewhere (links only) that use this page
        out['written'] = written
        out['marks'] = tool.get('marks', [])
        # The reference version is for comparing with your own, so it appears only once yours is accepted.
        out['reference'] = tool['reference'] if written else None
        # Real problems that use the technique: listed only once her own version is accepted, like the reference.
        mine = sorted(self.content.problems_for_tool(tool_id), key=lambda p: p['rating'])
        rows = evidence.attempts(store)
        def state(p):
            row = rows.get(p['id'])
            return 'new' if not row else 'solved' if row['solved_at'] else 'gave up' if row['gave_up_at'] else 'open'
        out['problems_total'] = len(mine)
        out['problems'] = [{'id': p['id'], 'title': p['title'], 'site': p['site'], 'rating': p['rating'], 'state': state(p)} for p in mine] if written else []
        return out

    def notebook(self, store):
        """The team notebook: for every toolbox page she has written, her own accepted code.

        Only her code goes in, never the reference. Tasks accepted before accepted sources were kept
        fall back to the code saved in the editor, marked as not re-judged."""
        done = {r['task'] for r in store.all('SELECT task FROM tasks_done')}
        kept = {(r['task'], r['language']): r for r in store.all('SELECT * FROM accepted_code')}
        prefer = [self.settings(store).get('language', 'cpp'), 'cpp', 'python']
        entries = []
        for tool in self.content.tools.values():
            entry = {'id': tool['id'], 'title': tool['title'], 'marks': tool.get('marks', []), 'when': tool['when'], 'traps': tool['traps'], 'written': tool['task'] in done, 'code': None}
            if entry['written']:
                for language in prefer:
                    row = kept.get((tool['task'], language))
                    if row:
                        entry.update(code=row['code'], language=language, judged=True)
                        break
                else:
                    for language in prefer:
                        row = store.one("SELECT code FROM code WHERE owner=? AND language=? AND file='main'", (tool['task'], language))
                        if row and row['code'].strip():
                            entry.update(code=row['code'], language=language, judged=False)
                            break
            entries.append(entry)
        return {'entries': entries, 'extra': store.get('notebook_extra', ''), 'title': store.get('notebook_title', '')}

    # ---------- a sitting with the tutor (derive/session.py) ----------
    def voice_on(self, store):
        return self.settings(store)['tutor'] == 'codex' and tutor.available()

    def latest_code(self, store, owner, since=''):
        """What she last wrote in the editor for a task, or in the code pad of a chain: (language, code, when). The untouched
        starting template does not count as her code."""
        for row in store.all("SELECT language, code, updated FROM code WHERE owner=? AND file='main' AND updated>=? ORDER BY updated DESC", (owner, since)):
            template = (self.root / 'templates' / ('main.py' if row['language'] == 'python' else 'main.cpp')).read_text()
            if row['code'].strip() and row['code'].strip() != template.strip():
                return row['language'], row['code'][:20000], row['updated']
        return None

    def sitting_context(self, store):
        """Where she is, written for the talking tutor, with the names that must not come back in a reply."""
        state = store.get(session.KEY)
        stage = state.get('stage') if state else None
        if not stage:
            return '', []
        try:
            if stage['kind'] == 'chain':
                if stage['id'] in self.derived(store):
                    prompt, _, _, _, _, secret = self.tutor_context(store, {'scope': 'chain', 'idea': stage['id']})
                else:
                    done = self.done_steps(store, stage['id'])
                    current = next(s for s in self.content.chains[stage['id']]['steps'] if s['id'] not in done)
                    prompt, _, _, _, _, secret = self.tutor_context(store, {'scope': 'chain', 'idea': stage['id'], 'step': current['id']})
                    reveal = self.content.chains[stage['id']]['reveal']
                    prompt += ('\n\nFOR YOUR EYES ONLY: where this chain ends. She has not been told and must not be, by name or by paraphrase, unless she passes the skip test.'
                               f'\nName: {reveal["name"]}\nStatement: {reveal["statement"]}\nUse it to write your own easier questions and to set the skip test. '
                               f'She has answered {len(done)} of {len(self.content.chains[stage["id"]]["steps"])} questions of this chain.'
                               + ('\nA SKIP TEST IS RUNNING: judge the code she pastes or has in the code pad (kindly), then pass her or tell her what is missing.' if (state.get('check') or {}).get('id') == stage['id'] else ''))
                    pad, notes = self.latest_code(store, stage['id']), store.get('chain_notes', {}).get(stage['id'], '').strip()
                    prompt += ('\n\nHER CODE PAD on this page right now (' + pad[0] + '), saved a moment after she stops typing:\n' + pad[1]) if pad else '\n\nHER CODE PAD on this page is empty. She can open "Code pad" under the question to write and run code; you see what is in it each time you speak.'
                    if notes:
                        prompt += '\n\nHER SCRATCH PAD on this page right now:\n' + notes[:6000]
                return prompt, secret
            task_id = session._task_of(self, stage)
            prompt, _, _, _, _, secret = self.tutor_context(store, {'scope': 'task', 'id': task_id})
            if stage['kind'] == 'tool':
                page = self.content.tools[stage['id']]
                prompt += '\n\nTHE TOOLBOX PAGE SHE HAS IN FRONT OF HER (she can read all of this; you may teach from it freely)\n' + page['title'] + '\nWhen to reach for it: ' + str(page['when']) + '\n' + str(page['idea'])[:6000]
            return prompt, secret
        except (ApiError, StopIteration):
            return '', []

    def sitting_speak(self, store, unasked=''):
        """Queue the tutor's next message. Talking on an unfinished chain or task is help, recorded like the Ask a tutor button."""
        state = store.get(session.KEY)
        context, secret = self.sitting_context(store)
        stage = state.get('stage')
        if stage and not unasked and not session._complete(self, store, stage):
            owner = stage['id'] if stage['kind'] == 'chain' else session._task_of(self, stage)
            store.run('INSERT INTO tutor_uses(at,scope,owner,step,outlet,gated) VALUES(?,?,?,?,?,?)', (now(), 'chain' if stage['kind'] == 'chain' else 'task', owner, '-', 'sitting', 1))
        # Names that must not come back: the chain she is on and the chains still planned, unless she used the words herself.
        derived = self.derived(store)
        planned = [self.content.ideas[i['id']]['name'] for i in state.get('plan', []) if i['kind'] == 'chain' and i['id'] not in derived and self.content.ideas[i['id']].get('track') != 'cses']
        hers = (state.get('goal', '') + ' ' + ' '.join(m['text'] for m in state.get('chat', []) if m['who'] == 'me')).casefold()
        secret = [n for n in dict.fromkeys([*secret, *planned]) if n.casefold() not in hers]
        # A message nobody asked for is about one moment; if she has moved on by the time it is written, it is dropped.
        job = self.queue(store, 'sitting', {'mode': 'talk', 'prompt': session.voice_prompt(self, store, context, unasked), 'secret': secret,
                                            'about': session.position(self, store) if unasked else None})
        state = store.get(session.KEY)
        state['pending'] = job
        store.set(session.KEY, state)
        return job

    def being_written(self, store, out):
        state = store.get(session.KEY)
        entry = self.writing.get(state.get('pending')) if state else None
        if entry and out.get('running'):
            text = session.split_action(entry['text'].split('ACTION:')[0])[0]
            stale = entry['about'] and entry['about'] != session.position(self, store)
            out['writing'] = '' if stale or any(n.casefold() in text.casefold() for n in entry['secret']) else text
        return out

    def sitting(self, store, data, action):
        return self.being_written(store, self.sitting_act(store, data, action))

    def sitting_act(self, store, data, action):
        if action == 'plan':
            minutes = data.get('minutes')
            if minutes not in session.LENGTHS:
                raise ApiError('Pick one of the listed lengths.')
            goal = text(data.get('goal', ''), 'What you want to do', 2000).strip()
            area = session.area_plan(self, store, goal)
            if not self.voice_on(store):
                return {'voice': False, 'say': '', 'plan': session.shown_plan(self, store, area or session.default_plan(self, store))}
            prompt, secret = session.plan_prompt(self, store, goal, minutes, area)
            secret = [n for n in secret if n.casefold() not in goal.casefold()]      # a topic she named herself is not a secret from her
            return {'voice': True, 'job': self.queue(store, 'sitting', {'mode': 'plan', 'prompt': prompt, 'secret': secret, 'area': area})}
        if action == 'start':
            if contest.active(store):
                raise ApiError('A contest is running. Start a sitting when it has ended.', 409)
            plan = data.get('plan') if isinstance(data.get('plan'), list) else []
            try:
                return session.start(self, store, data.get('minutes'), goal=text(data.get('goal', ''), 'What you want to do', 2000), plan=plan[:session.PLAN_MAX], say=text(data.get('say', ''), 'A message', 6000))
            except ValueError as error:
                raise ApiError(str(error), 409)
        if action == 'say':
            said = text(data.get('text', ''), 'Your message', 6000).strip()
            state = store.get(session.KEY)
            if not state or not said:
                raise ApiError('There is no sitting to talk in.', 409)
            if not self.voice_on(store):
                raise ApiError('The talking tutor is switched off. Turn it on in Settings (it uses the Codex command on this Mac).', 409)
            if state.get('pending'):
                raise ApiError('The tutor is still answering your last message.', 409)
            self.no_contest(store)
            session.add_chat(store, 'me', said)
            self.sitting_speak(store)
            return session.status(self, store)
        if action == 'check':
            if not self.voice_on(store):
                raise ApiError('The skip test needs the talking tutor, which is switched off.', 409)
            self.no_contest(store)
            if not session.ask_check(self, store):
                raise ApiError('The tutor is busy, or there is no chain to test you on right now.', 409)
            self.sitting_speak(store)
            return session.status(self, store)
        if action == 'seen':
            out = session.seen(self, store, data.get('route', ''), bool(data.get('active')))
            state = store.get(session.KEY)
            if state and state.get('pending'):                   # a reply that never came must not block her for ever
                row = store.one('SELECT status FROM jobs WHERE id=?', (state['pending'],))
                if not row or row['status'] in ('done', 'error'):
                    state['pending'] = None
                    store.set(session.KEY, state)
            if out.get('running') and self.voice_on(store) and not contest.active(store):
                why = session.wants_voice(self, store)
                if why:
                    try:
                        self.sitting_speak(store, unasked=why)
                    except ApiError:
                        pass                                     # the queue is busy judging her code; the rules still speak
                    out = session.status(self, store)
            return out
        return {'break': session.take_break, 'back': session.back, 'keep': session.keep_going, 'next': session.move_on, 'end': session.end}[action](self, store)

    def work_sitting(self, payload):
        # Talk goes through the running Codex process and is shown while it is written; the plan is one plain call.
        if payload['mode'] == 'talk' and self.teach is tutor.teach:
            job = payload.get('job')
            self.writing[job] = {'text': '', 'secret': payload.get('secret', []), 'about': payload.get('about')}
            try:
                outcome = self.stream.teach(payload['prompt'], lambda text: self.writing[job].update(text=text))
            finally:
                self.writing.pop(job, None)
        else:
            outcome = self.teach(payload['prompt'])
        if payload['mode'] == 'plan':
            with self.lock, self.store() as store:
                if outcome['status'] != 'ok':
                    return {'status': 'fallback', 'reason': outcome['reason'], 'say': '', 'plan': session.shown_plan(self, store, payload.get('area') or session.default_plan(self, store))}
                plan, say = session.read_plan(self, store, outcome['reply'], payload.get('secret', []))
                wanted = [i['id'] for i in payload.get('area', [])]
                if wanted and [p['id'] for p in plan if p['kind'] == 'chain'][:len(wanted)] != wanted:
                    # she named a whole area: the plan is that area, in order, whatever else the tutor thought of
                    plan = [*payload['area'], *[p for p in plan if p['id'] not in wanted]]
                if not plan:
                    return {'status': 'fallback', 'reason': 'The tutor did not come back with a usable plan, so here is the usual one.', 'say': say, 'plan': session.shown_plan(self, store, payload.get('area') or session.default_plan(self, store))}
                return {'status': 'ok', 'say': say, 'plan': session.shown_plan(self, store, plan)}
        if outcome['status'] != 'ok':
            reply = 'I could not answer just now (' + outcome['reason'] + ') Carry on; the strip at the top still watches, and you can ask me again.'
        elif any(name.casefold() in session.split_action(outcome['reply'])[0].casefold() for name in payload.get('secret', [])):
            reply = 'I started to name the thing you are about to discover, so I have held that reply back. Ask me again, or open the smaller question under the one you are on.'
        else:
            reply = outcome['reply']
        reply, action = session.split_action(reply)             # the tutor may end a message by doing something
        with self.lock, self.store() as store:
            if payload.get('about') and payload['about'] != session.position(self, store):
                session.add_chat(store, None, '')               # she has moved past what this was about: say nothing
                return {'status': 'stale'}
            session.add_chat(store, 'tutor', reply or 'Done.')
            if action and outcome['status'] == 'ok':
                state = store.get(session.KEY) or {}
                check = state.get('check') or {}
                pad = self.latest_code(store, check['id'], check.get('at', '')) if check.get('id') else None
                session.act(self, store, action, shown=bool(pad and session.looks_like_code(pad[1])))
        return {'status': 'ok'}

    # ---------- the tutor ----------
    def tutor_context(self, store, data):
        """Build the prompt for wherever the learner is. Returns (prompt, gated, scope, owner, step, names to keep out of a reply)."""
        self.no_contest(store)
        question = text(data.get('question', ''), 'Your question', 4000).strip()
        if data.get('scope') == 'problem':
            problem, row = self.attempt(store, data.get('id'))
            level = self.nudges_open(store, 'problem', problem['id'], '-')
            if row['solved_at'] or row['gave_up_at']:
                derived = self.derived(store)
                names = [self.content.ideas[i]['name'] for i in problem['ideas'] if i in derived]
                return tutor.problem_full(problem, row['approach'], problem['observations'], names, bool(row['solved_at'])), False, 'problem', problem['id'], '-', []
            return tutor.problem_stuck(problem, row['approach'], row['cue'], problem.get('nudges', [])[:level], question), True, 'problem', problem['id'], '-', []
        seen = session.seen_by_tutor(self, store)             # during a sitting the tutor is told what the app has watched
        if data.get('scope') == 'task':
            task = self.content.tasks.get(data.get('id')) if isinstance(data.get('id'), str) else None
            if not task:
                raise ApiError('No such task.', 404)
            mine = self.latest_code(store, task['id'])          # whichever language she typed in last
            code = mine[1] if mine else ''
            if store.one('SELECT 1 FROM tasks_done WHERE task=?', (task['id'],)):
                return tutor.task_full(task, code), False, 'task', task['id'], '-', []
            verdicts = [r['verdict'] for r in store.all('SELECT verdict FROM task_tries WHERE task=? ORDER BY id', (task['id'],))][-10:]
            opened = self.nudges_open(store, 'task', task['id'], '-')
            return tutor.task_stuck(task, code, verdicts, task['hints'][:opened], question) + seen, True, 'task', task['id'], '-', []
        idea = data.get('idea')
        chain = self.content.chains.get(idea) if isinstance(idea, str) else None
        if not chain:
            raise ApiError('No such chain.', 404)
        if idea in self.derived(store):
            reveal = chain['reveal']
            return tutor.chain_full(reveal['name'], reveal['statement'], reveal.get('remark', ''), chain['steps']), False, 'chain', idea, '-', []
        _, step = self.current_step(store, idea, data.get('step'))
        done = self.done_steps(store, idea)
        shown = lambda s: s['options'][int(done[s['id']]['answer'])] if s['kind'] == 'choice' and str(done[s['id']]['answer']).isdigit() else done[s['id']]['answer']
        earlier = [(s['prompt'], shown(s), s['showed']) for s in chain['steps'] if s['id'] in done]
        level = self.nudges_open(store, 'chain', idea, step['id'])
        prompt = tutor.chain_step(chain['opening'], earlier, step, step.get('options'), step.get('nudges', [])[:level], question)
        return prompt + seen, True, 'chain', idea, step['id'], [self.content.ideas[idea]['name']]

    def tutor_prompt(self, store, data):
        """The copy outlet: hand back the prompt to paste into ChatGPT."""
        prompt, gated, scope, owner, step, _ = self.tutor_context(store, data)
        store.run('INSERT INTO tutor_uses(at,scope,owner,step,outlet,gated) VALUES(?,?,?,?,?,?)', (now(), scope, owner, step, 'copy', int(gated)))
        return {'prompt': prompt, 'gated': gated}

    def tutor_ask(self, store, data):
        """The in-app outlet: run Codex in the background and show its reply."""
        if self.settings(store)['tutor'] != 'codex':
            raise ApiError('The in-app tutor is switched off. Turn it on in Settings, or copy the prompt into ChatGPT.', 409)
        prompt, gated, scope, owner, step, secret = self.tutor_context(store, data)
        turns = data.get('thread', [])
        if not isinstance(turns, list) or len(turns) > 40:
            raise ApiError('That conversation is too long; start a new one.', 413)
        said = [(t.get('who') == 'tutor', text(t.get('text'), 'A message', 20000)) for t in turns if isinstance(t, dict)]
        prompt = tutor.with_thread(prompt, said)
        store.run('INSERT INTO tutor_uses(at,scope,owner,step,outlet,gated) VALUES(?,?,?,?,?,?)', (now(), scope, owner, step, 'codex', int(gated)))
        return {'job': self.queue(store, 'tutor', {'prompt': prompt, 'secret': secret}), 'gated': gated}

    def work_tutor(self, payload):
        outcome = self.teach(payload['prompt'])
        if outcome['status'] != 'ok':
            return {'status': 'unavailable', 'reason': outcome['reason']}
        # A reply that says the name of a result she has not finished deriving is not shown.
        if any(name.casefold() in outcome['reply'].casefold() for name in payload.get('secret', [])):
            return {'status': 'withheld', 'reason': 'The tutor named the result you are deriving, so its reply is not shown. Ask again, or use a smaller question.'}
        return {'status': 'ok', 'reply': outcome['reply']}

    # ---------- code and runs ----------
    def code(self, store, owner, language):
        if owner not in self.content.problems and owner not in self.content.tasks and owner not in self.content.chains:
            raise ApiError('No such problem.', 404)
        if language not in ('cpp', 'python'):
            raise ApiError('Choose C++ or Python.')
        saved = {r['file']: r['code'] for r in store.all('SELECT * FROM code WHERE owner=? AND language=?', (owner, language))}
        template = (self.root / 'templates' / ('main.py' if language == 'python' else 'main.cpp')).read_text()
        return {'language': language, 'files': {f: saved.get(f, template if f == 'main' else '') for f in FILES}}

    def save_code(self, store, data):
        owner, language, file = data.get('id'), data.get('language'), data.get('file')
        if (owner not in self.content.problems and owner not in self.content.tasks and owner not in self.content.chains) or language not in ('cpp', 'python') or file not in FILES:
            raise ApiError('That file cannot be saved.')
        store.run('INSERT OR REPLACE INTO code VALUES(?,?,?,?,?)', (owner, language, file, text(data.get('code'), 'Code', CODE_LIMIT), now()))
        return {'saved': True}

    def queue(self, store, kind, payload):
        waiting = store.one("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running')")[0]
        if waiting >= 3:
            raise ApiError('Let the current run finish first.', 429)
        job = uuid.uuid4().hex
        payload = {**payload, 'job': job} if kind == 'sitting' else payload
        store.run('INSERT INTO jobs VALUES(?,?,?,?,?,?,NULL)', (job, kind, 'queued', now(), now(), json.dumps(payload)))
        (self.tutors if kind in ('tutor', 'sitting') else self.workers).submit(self.work, job)
        return job

    def queue_run(self, store, data):
        kind = data.get('kind')
        if kind not in ('run', 'stress'):
            raise ApiError('Choose run or stress.')
        owner, language = data.get('id'), data.get('language')
        if (owner not in self.content.problems and owner not in self.content.tasks and owner not in self.content.chains) or language not in ('cpp', 'python'):
            raise ApiError('That cannot be run.')
        payload = {'language': language, 'input': text(data.get('input', ''), 'Input', CODE_LIMIT), 'owner': owner}
        for file in FILES:
            if file in data:
                self.save_code(store, {'id': owner, 'language': language, 'file': file, 'code': data[file]})
                payload[file] = data[file]
        if not payload.get('main', '').strip():
            raise ApiError('There is no solution code to run.')
        if kind == 'stress':
            if not payload.get('brute', '').strip() or not payload.get('gen', '').strip():
                raise ApiError('Stress testing needs your brute force and your generator as well.')
            cases = data.get('cases', 100)
            if type(cases) is not int or not 1 <= cases <= 1000:
                raise ApiError('Choose between 1 and 1000 cases.')
            payload['cases'] = cases
        return {'job': self.queue(store, kind, payload)}

    def job(self, store, job_id):
        if not isinstance(job_id, str) or not re.fullmatch(r'[a-f0-9]{32}', job_id):
            raise ApiError('No such run.', 404)
        row = store.one('SELECT * FROM jobs WHERE id=?', (job_id,))
        if not row:
            raise ApiError('No such run.', 404)
        return {'id': row['id'], 'kind': row['kind'], 'status': row['status'], 'result': json.loads(row['result']) if row['result'] else None}

    def work(self, job_id):
        with self.store() as store:
            row = store.one('SELECT * FROM jobs WHERE id=?', (job_id,))
            if not row:
                return
            store.run("UPDATE jobs SET status='running', updated=? WHERE id=?", (now(), job_id))
            payload = json.loads(row['payload'])
            try:
                if row['kind'] == 'grade':
                    result = self.work_grade(store, payload)
                elif row['kind'] == 'tutor':
                    result = self.work_tutor(payload)
                elif row['kind'] == 'sitting':
                    result = self.work_sitting(payload)
                elif row['kind'] == 'judge':
                    result = self.work_judge(store, payload)
                elif row['kind'] == 'break':
                    result = self.work_break(store, payload)
                else:
                    result = self.work_run(row['kind'], payload)
                status = 'done'
            except JudgeError as exc:
                result, status = {'verdict': 'CE', 'detail': str(exc)}, 'done'
            except Exception as exc:  # a broken run must never leave the job hanging
                result, status = {'error': f'The run could not finish: {exc}'}, 'error'
            store.run('UPDATE jobs SET status=?, result=?, updated=? WHERE id=?', (status, json.dumps(result), now(), job_id))

    def work_grade(self, store, payload):
        row = store.one('SELECT * FROM proofs WHERE id=?', (payload['proof'],))
        _, step = self.content.step(row['owner'], row['step'])
        outcome = self.grade(step['prompt'], step['claims'], row['text'])
        if outcome['status'] != 'graded':
            store.run("UPDATE proofs SET status='awaiting', feedback=? WHERE id=?", (json.dumps({'reason': outcome['reason']}), row['id']))
            return {'status': 'awaiting', 'reason': outcome['reason']}
        verdict = {k: outcome[k] for k in ('pass', 'established', 'gap', 'question')}
        with self.lock:
            return self.apply_verdict(store, row['id'], verdict)

    def work_run(self, kind, payload):
        suffix = '.py' if payload['language'] == 'python' else '.cpp'
        with tempfile.TemporaryDirectory(prefix='derive-src-') as folder:
            def build(name):
                path = Path(folder) / (name + suffix)
                path.write_text(payload[name])
                try:
                    return Executable(path, RUN_SECONDS, RUN_MEMORY)
                except JudgeError as exc:
                    raise JudgeError({'main': 'Your solution', 'brute': 'Your brute force', 'gen': 'Your generator'}[name] + ' did not compile.\n' + str(exc)) from exc
            with build('main') as main:
                if kind == 'run':
                    task = self.content.tasks.get(payload.get('owner'))
                    if task and task.get('interactive'):
                        # A trial run of an interactive task: the judge's side plays against the program, and the exchange is shown.
                        try:
                            got, reason, transcript = main.talk(tasks.talkers(task)[0](payload['input']))
                        except JudgeError:
                            raise
                        except Exception:
                            return {'verdict': 'WA', 'seconds': 0, 'output': '', 'detail': 'That hidden input is not in the form this task uses. Start from the example and change the numbers.'}
                        verdict = got.verdict if got.verdict != 'OK' else 'WA' if reason else 'OK'
                        return {'verdict': verdict, 'seconds': got.seconds, 'output': tasks.script(transcript), 'detail': reason or got.detail or 'The judge accepted the exchange.'}
                    return asdict(main.run(payload['input']))
                with build('brute') as brute, build('gen') as gen:
                    for seed in range(1, payload['cases'] + 1):
                        made = gen.run(f'{seed}\n')
                        if made.verdict != 'OK':
                            return {'verdict': 'GEN', 'detail': f'Your generator failed on seed {seed}: {made.verdict}. {made.detail}'[:2000], 'cases': seed - 1}
                        want, got = brute.run(made.output), main.run(made.output)
                        if want.verdict != 'OK':
                            return {'verdict': 'BRUTE', 'detail': f'Your brute force failed on seed {seed}: {want.verdict}. {want.detail}'[:2000], 'input': made.output[:20000], 'cases': seed - 1}
                        if got.verdict != 'OK' or not same_output(got.output, want.output):
                            return {'verdict': 'DIFF' if got.verdict == 'OK' else got.verdict, 'detail': f'Seed {seed}: your solution and your brute force disagree.' if got.verdict == 'OK' else f'Seed {seed}: your solution stopped with {got.verdict}. {got.detail}'[:2000],
                                    'input': made.output[:20000], 'output': got.output[:20000], 'expected': want.output[:20000], 'cases': seed - 1}
                    return {'verdict': 'SAME', 'detail': f'Your solution and your brute force agreed on all {payload["cases"]} generated tests.', 'cases': payload['cases']}

    # ---------- mastery ----------
    def mastery(self, store):
        derived = self.derived(store)
        ev = evidence.idea_evidence(self.content, store)
        named = lambda i: self.content.ideas[i]['name'] if i in derived else None
        ideas = [{'id': i, 'name': named(i), 'area': self.content.ideas[i]['area'], 'has_chain': i in self.content.chains, **ev[i]} for i in self.content.order]
        pairs = [{'a': a, 'b': b, 'a_name': named(a), 'b_name': named(b), **v} for (a, b), v in sorted(evidence.pair_evidence(self.content, store).items())
                 if a in derived and b in derived]
        causes = {r['cause']: r[1] for r in store.all('SELECT cause, COUNT(*) FROM attempts WHERE cause IS NOT NULL GROUP BY cause')}
        owed = [{'idea': r['idea'], 'name': named(r['idea']), 'due': r['due'], 'reason': r['reason']} for r in store.all('SELECT * FROM returns WHERE done_at IS NULL ORDER BY due')]
        return {'ideas': ideas, 'pairs': pairs, 'causes': [{'id': k, 'label': v, 'count': causes.get(k, 0)} for k, v in evidence.CAUSES.items()],
                'returns': owed, 'band': evidence.band(self.content, store), 'counts': self.counts(store), 'areas': self.content.areas,
                'patterns': self.patterns(store, derived)}

    def patterns(self, store, derived):
        """Where the mistakes are, cut several ways. Counts only: with few rows a sentence would claim more than is known."""
        ideas, areas = self.content.ideas, {a['id']: a['title'] for a in self.content.areas}
        label = lambda i: ideas[i]['name'] if i in derived else None
        # what got in the way, by area of the problem (a problem with ideas in two areas counts in both)
        by_area = {}
        for r in store.all("SELECT problem, cause FROM attempts WHERE cause IS NOT NULL AND cause != 'none'"):
            problem = self.content.problems.get(r['problem'])
            for area in sorted({ideas[i]['area'] for i in problem['ideas']}) if problem else []:
                by_area.setdefault(area, {})[r['cause']] = by_area.setdefault(area, {}).get(r['cause'], 0) + 1
        # the move that cracks each finished problem: made by her, or missed
        moves = {}
        for r in store.all('SELECT move, move_made, COUNT(*) AS n FROM attempts WHERE move IS NOT NULL AND move_made IS NOT NULL GROUP BY move, move_made'):
            moves.setdefault(r['move'], {})['made' if r['move_made'] else 'missed'] = r['n']
        lessons = [{'title': self.content.problems[r['problem']]['title'], 'id': r['problem'], 'move': evidence.MOVES.get(r['move']), 'made': r['move_made'], 'lesson': r['lesson']}
                   for r in store.all("SELECT problem, move, move_made, lesson FROM attempts WHERE lesson != '' ORDER BY COALESCE(solved_at, gave_up_at) DESC LIMIT 30") if r['problem'] in self.content.problems]
        # chains: wrong answers, smaller questions opened, tutor asked while unfinished
        chains = {}
        for r in store.all('SELECT idea, COUNT(*) AS n FROM step_attempts WHERE correct=0 GROUP BY idea'):
            chains.setdefault(r['idea'], {})['wrong'] = r['n']
        for r in store.all("SELECT owner, COUNT(*) AS n FROM nudges WHERE scope='chain' GROUP BY owner"):
            chains.setdefault(r['owner'], {})['nudges'] = r['n']
        for r in store.all("SELECT owner, COUNT(*) AS n FROM tutor_uses WHERE scope='chain' AND gated=1 GROUP BY owner"):
            chains.setdefault(r['owner'], {})['tutor'] = r['n']
        hardest = sorted(((i, v) for i, v in chains.items() if i in ideas), key=lambda x: -(x[1].get('wrong', 0) + 2 * x[1].get('nudges', 0) + 2 * x[1].get('tutor', 0)))[:10]
        # code: what the judge said, and how many tasks went through on the first try
        verdicts = {r['verdict']: r['n'] for r in store.all('SELECT verdict, COUNT(*) AS n FROM task_tries GROUP BY verdict')}
        accepted = store.all('SELECT tries FROM tasks_done')
        # the 'standard' track is drill: what matters there is being right on the first submission
        drill = {t['id'] for t in self.content.tasks.values() if t.get('track') == 'standard'}
        drilled = [r['tries'] for r in store.all('SELECT task, tries FROM tasks_done') if r['task'] in drill]
        # a hint counts against an accept only if it was opened before the program was accepted
        hinted = store.one("SELECT COUNT(*) FROM tasks_done d WHERE EXISTS(SELECT 1 FROM nudges n WHERE n.scope='task' AND n.owner=d.task AND n.at<=d.at)")[0]
        broken = store.all('SELECT tries, nudges FROM breaks_done')
        recog = {r['rating']: r['n'] for r in store.all('SELECT rating, COUNT(*) AS n FROM recognitions WHERE rating IS NOT NULL GROUP BY rating')}
        sets = {s['id']: s['title'] for s in self.content.puzzles.get('sets', [])}
        of_set = {p['id']: p.get('set') for p in self.content.puzzles.get('puzzles', [])}
        puzzles = {}
        for r in store.all('SELECT puzzle, wrong, shown FROM puzzles_done'):
            row = puzzles.setdefault(of_set.get(r['puzzle']), {'done': 0, 'clean': 0, 'shown': 0})
            row['done'] += 1; row['clean'] += int(not r['wrong'] and not r['shown']); row['shown'] += int(bool(r['shown']))
        return {
            'moves': [{'label': v, 'made': moves[k].get('made', 0), 'missed': moves[k].get('missed', 0)} for k, v in evidence.MOVES.items() if k in moves], 'lessons': lessons,
            'by_area': [{'area': areas.get(a, a), 'total': sum(c.values()), 'causes': [{'label': evidence.CAUSES[k], 'count': n} for k, n in sorted(c.items(), key=lambda x: -x[1])]} for a, c in sorted(by_area.items(), key=lambda x: -sum(x[1].values()))],
            'chains': [{'id': i, 'name': label(i), 'area': areas.get(ideas[i]['area'], ''), 'track': ideas[i].get('track'), 'title': ideas[i].get('cses', {}).get('title'),
                        'wrong': v.get('wrong', 0), 'nudges': v.get('nudges', 0), 'tutor': v.get('tutor', 0)} for i, v in hardest],
            'code': {'verdicts': [{'verdict': k, 'count': verdicts[k]} for k in ('AC', 'WA', 'TLE', 'RE', 'MLE', 'CE') if verdicts.get(k)], 'accepted': len(accepted), 'first_try': sum(1 for r in accepted if r['tries'] == 1), 'no_hint': len(accepted) - hinted,
                     'standard': {'of': len(drill), 'accepted': len(drilled), 'first_try': sum(1 for n in drilled if n == 1)}},
            'breaks': {'broken': len(broken), 'of': len(self.content.breaks), 'first_try': sum(1 for r in broken if r['tries'] == 1), 'with_questions': sum(1 for r in broken if r['nudges'])},
            'recognise': [{'label': v, 'count': recog.get(k, 0)} for k, v in recognise.RATINGS.items()],
            'puzzles': [{'set': sets.get(k, k or 'Other'), **v} for k, v in puzzles.items()],
        }

    # ---------- routing ----------
    def get(self, path, query):
        with self.store() as store:
            if path in ('/bootstrap', '/session'):               # these can move the sitting on, so they take the writer's lock
                with self.lock:
                    return self.bootstrap(store) if path == '/bootstrap' else self.being_written(store, session.status(self, store))
            if path == '/map':
                return self.map(store)
            if path.startswith('/chain/'):
                return self.chain(store, path[7:])
            if path.startswith('/problem/'):
                return self.problem(store, path[9:])
            if path.startswith('/code/'):
                return self.code(store, path[6:], query.get('language', ['cpp'])[0])
            if path.startswith('/jobs/'):
                return self.job(store, path[6:])
            if path.startswith('/proof/'):
                return self.proof_prompt(store, path[7:])
            if path == '/mastery':
                return self.mastery(store)
            if path == '/cses':
                return self.cses_page(store)
            if path == '/tools':
                return self.tool_list(store)
            if path == '/notebook':
                return self.notebook(store)
            if path == '/recognise':
                return recognise.overview(self.content, store, self.derived(store))
            if path == '/breaks':
                return {'items': breaks.listing(self.content, store)}
            if path.startswith('/break/'):
                return breaks.page(self.content, store, self.break_item({'id': path[7:]}))
            if path.startswith('/tool/'):
                return self.tool(store, path[6:])
            if path == '/tasks':
                derived = self.derived(store)
                return {'tasks': [{**tasks.public(t, store), 'basis': self.task_basis(store, t['id'], derived)} for t in self.content.tasks.values()], 'tracks': self.content.task_tracks, 'patterns': self.thinking_patterns(store)}
            if path.startswith('/task/'):
                return self.task(store, path[6:])
            if path == '/puzzles':
                at = query.get('at', [''])[0]
                return self.puzzles(store, query.get('set', [''])[0], int(at) if at.isdigit() else None)
            if path == '/revise':
                return stars.cards(self, store, bool(contest.active(store)))
            if path == '/contests':
                return contest.overview(store)
        raise ApiError('Not found.', 404)

    def post(self, path, data):
        if not isinstance(data, dict):
            raise ApiError('Send a JSON object.')
        routes = {'/chain/answer': self.answer, '/chain/skip': self.skip_easy, '/nudge': self.nudge, '/chain/proof': self.submit_proof, '/chain/proof/read': self.read_proof, '/proof/verdict': self.manual_verdict,
                  '/problem/commit': self.commit, '/problem/editorial': self.editorial, '/problem/check': self.check_submissions,
                  '/problem/report': self.report, '/problem/giveup': self.give_up, '/problem/cause': self.cause, '/problem/move': self.move,
                  '/code': self.save_code, '/run': self.queue_run,
                  '/tutor/prompt': self.tutor_prompt, '/tutor/ask': self.tutor_ask, '/puzzle/answer': self.puzzle_answer, '/task/judge': self.task_judge, '/task/hint': self.task_hint,
                  '/problem/open': self.open_from_chain, '/break/try': self.break_try, '/break/nudge': self.break_nudge}
        with self.lock, self.store() as store:
            if path.startswith('/session/') and path[9:] in ('plan', 'start', 'say', 'check', 'seen', 'break', 'back', 'keep', 'next', 'end'):
                return self.sitting(store, data, path[9:])
            if path == '/problem/next':
                return self.open_next(store)
            if path == '/problem/notes':
                problem, _ = self.attempt(store, data.get('id'))
                store.run('UPDATE attempts SET notes=? WHERE problem=?', (text(data.get('notes', ''), 'Notes', 100000), problem['id']))
                return {'saved': True}
            if path == '/chain/notes':                       # the scratch pad of one chain
                idea = data.get('idea')
                if idea not in self.content.chains:
                    raise ApiError('No such chain.', 404)
                notes = store.get('chain_notes', {})
                notes[idea] = text(data.get('notes', ''), 'Notes', 100000)
                if not notes[idea]:
                    del notes[idea]
                store.set('chain_notes', notes)
                return {'saved': True}
            if path == '/notebook':                          # the notebook's own title and free notes
                store.set('notebook_title', text(data.get('title', ''), 'Title', 200))
                store.set('notebook_extra', text(data.get('extra', ''), 'Notes', 100000))
                return {'saved': True}
            if path in ('/recognise/reveal', '/recognise/rate'):
                if path.endswith('reveal'):
                    self.no_contest(store)                   # what cracks a problem is help
                getattr(recognise, path[11:])(self.content, store, data, ApiError)
                return recognise.overview(self.content, store, self.derived(store))
            if path == '/settings':
                return {'settings': self.save_settings(store, data)}
            if path == '/star':
                return stars.toggle(self, store, data, ApiError)
            if path in ('/contest/start', '/contest/refresh', '/contest/end', '/contest/label', '/contest/stall', '/contest/lesson'):
                return getattr(contest, path[9:])(self, store, data, ApiError)
            if path == '/practice':
                known = {t['url'] for tasks in self.content.practice.values() for t in tasks} | {p['url'] for p in self.content.parked.values()}
                if data.get('url') not in known:
                    raise ApiError('No such practice task.', 404)
                ticked = set(store.get('practice_done', []))
                (ticked.add if data.get('done') else ticked.discard)(data['url'])
                store.set('practice_done', sorted(ticked))
                return {'done': data['url'] in ticked}
            if path in routes:
                return routes[path](store, data)
        raise ApiError('Not found.', 404)


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, service):
        self.service = service
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    server_version = 'DeriveLocal/1.0'
    protocol_version = 'HTTP/1.1'

    def log_message(self, format, *args):
        pass

    def common(self):
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Cross-Origin-Resource-Policy', 'same-origin')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")

    def json(self, value, status=200):
        body = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.common()
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def host(self):
        # Only this machine's own address is served, so a web page elsewhere cannot aim a hostname at the app.
        host, port = self.headers.get('Host', ''), self.server.server_address[1]
        if host not in (f'127.0.0.1:{port}', f'localhost:{port}'):
            raise ApiError('This app only answers on its local address.', 403)
        return host

    def do_GET(self):
        try:
            self.host()
            parsed = urlparse(self.path)
            path = unquote(parsed.path)
            if path.startswith('/api/'):
                return self.json(self.server.service.get(path[4:], parse_qs(parsed.query)))
            relative = 'index.html' if path in ('/', '/index.html') else path[8:] if path.startswith('/assets/') else None
            if relative is None:
                raise ApiError('Not found.', 404)
            static = self.server.service.static
            file = (static / relative).resolve()
            if not file.is_relative_to(static) or not file.is_file():
                raise ApiError('Not found.', 404)
            body = file.read_bytes()
            kind = mimetypes.guess_type(file.name)[0] or 'application/octet-stream'
            self.send_response(200)
            self.common()
            self.send_header('Content-Type', kind + ('; charset=utf-8' if kind.startswith('text/') or kind.endswith('javascript') else ''))
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-cache')
            self.end_headers()
            self.wfile.write(body)
        except (ApiError, KeyError, ValueError) as exc:
            self.json({'error': str(exc).strip('\'"')}, getattr(exc, 'status', 400))
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            self.json({'error': 'The app could not complete this. Try again.'}, 500)

    def do_POST(self):
        try:
            host = self.host()
            origin = self.headers.get('Origin')
            if origin is not None and origin != f'http://{host}':
                raise ApiError('Changes from another site are blocked.', 403)
            if self.headers.get('Sec-Fetch-Site') == 'cross-site':
                raise ApiError('Changes from another site are blocked.', 403)
            if not secrets.compare_digest(self.headers.get('X-Derive-Token', ''), self.server.service.csrf):
                raise ApiError('Reload the page before saving changes.', 403)
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                raise ApiError('Send application/json.', 415)
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= MAX_BODY:
                raise ApiError('The request is empty or too large.', 413)
            data = json.loads(self.rfile.read(length))
            path = unquote(urlparse(self.path).path)
            if not path.startswith('/api/'):
                raise ApiError('Not found.', 404)
            self.json(self.server.service.post(path[4:], data))
        except (ApiError, KeyError, ValueError) as exc:
            self.json({'error': str(exc).strip('\'"')}, getattr(exc, 'status', 400))
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            self.json({'error': 'The app could not complete this. Your work is saved.'}, 500)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Launch the local derive app.')
    parser.add_argument('--data', type=Path, default=Path(os.environ['DERIVE_DATA']) if os.environ.get('DERIVE_DATA') else None,
                        help='folder for the learner record (default: .data in the project)')
    parser.add_argument('--port', type=int, default=8770)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args(argv)
    service = Service(ROOT, args.data)
    try:
        server = LocalServer(('127.0.0.1', args.port), service)
    except OSError as exc:
        print(f'Cannot start: {exc}. Try another --port.', file=sys.stderr)
        return 1
    url = f'http://127.0.0.1:{args.port}'
    print(f'derive\n{url}\nYour record: {service.data / "learner.db"}\nPress Ctrl+C to stop.', flush=True)
    if not args.no_browser:
        threading.Timer(.3, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever(poll_interval=.2)
    except KeyboardInterrupt:
        print('\nStopped. Your work is saved.')
    finally:
        server.server_close()
        service.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
