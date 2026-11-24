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

from . import contest, evidence, grader, sync, tutor
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

    def chain_open(self, idea, derived):
        """A chain may be started once every idea it builds on that has a chain is derived."""
        return all(n in derived or n not in self.content.chains for n in self.content.ideas[idea].get('needs', []))

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
                'has_chain': bool(chain), 'open': bool(chain) and self.chain_open(idea_id, derived),
                'steps_total': len(chain['steps']) if chain else 0, 'steps_done': len(self.done_steps(store, idea_id)) if chain else 0,
                'evidence': ev[idea_id],
            })
        links = [{'from': l['from'], 'to': l['to'], 'kind': l['kind'],
                  # Why two ideas are connected is told only once both have been derived.
                  'note': l['note'] if l['from'] in derived and l['to'] in derived else None} for l in self.content.links]
        return {'areas': self.content.areas, 'ideas': ideas, 'links': links}

    def counts(self, store):
        rows = evidence.attempts(store)
        return {'ideas': len(self.content.ideas), 'chains': len(self.content.chains), 'derived': len(self.derived(store)),
                'problems': len(self.content.problems), 'solved': sum(1 for r in rows.values() if r['solved_at']),
                'cold': sum(1 for r in rows.values() if evidence.is_cold(r))}

    def next_chain(self, store):
        derived = self.derived(store)
        started = [i for i in self.content.order if i in self.content.chains and i not in derived and self.done_steps(store, i)]
        if started:
            return started[0]
        return next((i for i in self.content.order if i in self.content.chains and i not in derived and self.chain_open(i, derived)), None)

    def bootstrap(self, store):
        return {'csrf': self.csrf, 'settings': self.settings(store), 'grader_available': grader.available(), 'tutor_available': tutor.available(),
                'counts': self.counts(store), 'band': evidence.band(self.content, store),
                'open_problem': evidence.open_problem(store), 'next_chain': self.next_chain(store)}

    # ---------- chains ----------
    def nudges_open(self, store, scope, owner, step):
        return store.one('SELECT COALESCE(MAX(level),0) FROM nudges WHERE scope=? AND owner=? AND step=?', (scope, owner, step))[0]

    def public_step(self, store, idea, step, done):
        level = self.nudges_open(store, 'chain', idea, step['id'])
        out = {'id': step['id'], 'kind': step['kind'], 'prompt': step['prompt'], 'done': bool(done),
               'nudges': step.get('nudges', [])[:level], 'nudges_total': len(step.get('nudges', []))}
        if step['kind'] == 'choice':
            out['options'] = step['options']
        if step['kind'] in ('formula', 'counterexample'):
            out['vars'] = list(step['vars'])
        if step['kind'] == 'counterexample':
            out['bounds'] = step['bounds']
        if step['kind'] == 'proof':
            last = store.one("SELECT * FROM proofs WHERE scope='chain' AND owner=? AND step=? ORDER BY id DESC LIMIT 1", (idea, step['id']))
            out['proof'] = {'id': last['id'], 'text': last['text'], 'status': last['status'], 'feedback': json.loads(last['feedback'])} if last else None
        if done:
            out['answer'] = done['answer']
            out['showed'] = step['showed']
        return out

    def chain(self, store, idea):
        if idea not in self.content.ideas:
            raise ApiError('No such idea.', 404)
        chain = self.content.chains.get(idea)
        if not chain:
            raise ApiError('The chain for this idea has not been written yet.', 404)
        derived = self.derived(store)
        if not self.chain_open(idea, derived) and idea not in derived:
            raise ApiError('This chain builds on something you have not derived yet.', 409)
        done = self.done_steps(store, idea)
        steps = []
        for step in chain['steps']:
            steps.append(self.public_step(store, idea, step, done.get(step['id'])))
            if step['id'] not in done:
                break                                  # later steps stay unseen until this one is right
        complete = idea in derived
        ticked = set(store.get('practice_done', []))
        info = self.content.ideas[idea]
        return {'idea': idea, 'opening': chain['opening'], 'steps': steps, 'total': len(chain['steps']), 'complete': complete,
                'reveal': {**chain['reveal'], 'problems': len(self.content.problems_for(idea))} if complete else None,
                # Practice tasks would give the topic away, so they are listed only once the chain is finished.
                'practice': [{**t, 'done': t['url'] in ticked} for t in self.content.practice.get(idea, [])] if complete else [],
                'area': next(a['title'] for a in self.content.areas if a['id'] == info['area'])}

    def current_step(self, store, idea, step_id):
        chain = self.content.chains.get(idea)
        if not chain:
            raise ApiError('No such chain.', 404)
        done = self.done_steps(store, idea)
        current = next((s for s in chain['steps'] if s['id'] not in done), None)
        if not current or current['id'] != step_id:
            raise ApiError('That is not the step you are on.', 409)
        if not self.chain_open(idea, self.derived(store)):
            raise ApiError('This chain builds on something you have not derived yet.', 409)
        return chain, current

    def finish_step(self, store, idea, chain, step, answer):
        store.run('INSERT OR IGNORE INTO steps_done VALUES(?,?,?,?)', (idea, step['id'], now(), answer))
        complete = step['id'] == chain['steps'][-1]['id']
        if complete:
            store.run('INSERT OR IGNORE INTO discoveries VALUES(?,?)', (idea, now()))
        return complete

    def answer(self, store, data):
        idea, step_id = data.get('idea'), data.get('step')
        chain, step = self.current_step(store, idea, step_id)
        if step['kind'] == 'proof':
            raise ApiError('This step is a written proof.')
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
            if not row['committed_at']:
                raise ApiError('Commit to an approach before asking for a nudge.', 409)
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
            'cold': bool(row['cold']), 'verdict_source': row['verdict_source'], 'cause': row['cause'], 'notes': row['notes'],
            'returned_for': bool(row['returned_for']), 'finished': finished,
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
        cue = text(data.get('cue'), 'The cue', 2000, required=True).strip()
        if len(approach) < 20:
            raise ApiError('Say a little more: what you will do, and why you think it works.')
        store.run('UPDATE attempts SET approach=?, cue=?, committed_at=? WHERE problem=?', (approach, cue, now(), problem['id']))
        return self.problem(store, problem['id'])

    def editorial(self, store, data):
        self.no_contest(store)
        problem, row = self.attempt(store, data.get('id'))
        if not row['committed_at']:
            raise ApiError('Commit to an approach before opening the editorial.', 409)
        if not row['editorial_at']:
            store.run('UPDATE attempts SET editorial_at=? WHERE problem=?', (now(), problem['id']))
        return self.problem(store, problem['id'])

    def finish(self, store, problem, row, source, submission=None, before_open=False):
        tutored = store.one("SELECT 1 FROM tutor_uses WHERE scope='problem' AND owner=? AND gated=1", (problem['id'],))
        helped = bool(self.nudges_open(store, 'problem', problem['id'], '-') or row['editorial_at'] or tutored)
        cold = source == 'judge' and not helped and not before_open and bool(row['committed_at'])
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
        if not row['committed_at']:
            raise ApiError('Record your approach first; it is what shows whether you saw the idea.', 409)
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
        if not row['committed_at']:
            raise ApiError('Record your approach first.', 409)
        result = self.finish(store, problem, row, 'self')
        return {**self.problem(store, problem['id']), **result}

    def give_up(self, store, data):
        problem, row = self.attempt(store, data.get('id'))
        if row['solved_at'] or row['gave_up_at']:
            raise ApiError('This problem is already finished.', 409)
        if not row['committed_at']:
            raise ApiError('Write down your best approach before giving up; a wrong guess is still information.', 409)
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
            if not row['committed_at']:
                raise ApiError('Commit to an approach before asking a tutor; your own first idea is what the tutor works from.', 409)
            return tutor.problem_stuck(problem, row['approach'], row['cue'], problem.get('nudges', [])[:level], question), True, 'problem', problem['id'], '-', []
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
        return prompt, True, 'chain', idea, step['id'], [self.content.ideas[idea]['name']]

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
        if owner not in self.content.problems:
            raise ApiError('No such problem.', 404)
        if language not in ('cpp', 'python'):
            raise ApiError('Choose C++ or Python.')
        saved = {r['file']: r['code'] for r in store.all('SELECT * FROM code WHERE owner=? AND language=?', (owner, language))}
        template = (self.root / 'templates' / ('main.py' if language == 'python' else 'main.cpp')).read_text()
        return {'language': language, 'files': {f: saved.get(f, template if f == 'main' else '') for f in FILES}}

    def save_code(self, store, data):
        owner, language, file = data.get('id'), data.get('language'), data.get('file')
        if owner not in self.content.problems or language not in ('cpp', 'python') or file not in FILES:
            raise ApiError('That file cannot be saved.')
        store.run('INSERT OR REPLACE INTO code VALUES(?,?,?,?,?)', (owner, language, file, text(data.get('code'), 'Code', CODE_LIMIT), now()))
        return {'saved': True}

    def queue(self, store, kind, payload):
        waiting = store.one("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running')")[0]
        if waiting >= 3:
            raise ApiError('Let the current run finish first.', 429)
        job = uuid.uuid4().hex
        store.run('INSERT INTO jobs VALUES(?,?,?,?,?,?,NULL)', (job, kind, 'queued', now(), now(), json.dumps(payload)))
        (self.tutors if kind == 'tutor' else self.workers).submit(self.work, job)
        return job

    def queue_run(self, store, data):
        kind = data.get('kind')
        if kind not in ('run', 'stress'):
            raise ApiError('Choose run or stress.')
        owner, language = data.get('id'), data.get('language')
        if owner not in self.content.problems or language not in ('cpp', 'python'):
            raise ApiError('That cannot be run.')
        payload = {'language': language, 'input': text(data.get('input', ''), 'Input', CODE_LIMIT)}
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
                'returns': owed, 'band': evidence.band(self.content, store), 'counts': self.counts(store), 'areas': self.content.areas}

    # ---------- routing ----------
    def get(self, path, query):
        with self.store() as store:
            if path == '/bootstrap':
                return self.bootstrap(store)
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
            if path == '/contests':
                return {**contest.overview(store), 'papers': self.content.papers}
        raise ApiError('Not found.', 404)

    def post(self, path, data):
        if not isinstance(data, dict):
            raise ApiError('Send a JSON object.')
        routes = {'/chain/answer': self.answer, '/nudge': self.nudge, '/chain/proof': self.submit_proof, '/proof/verdict': self.manual_verdict,
                  '/problem/commit': self.commit, '/problem/editorial': self.editorial, '/problem/check': self.check_submissions,
                  '/problem/report': self.report, '/problem/giveup': self.give_up, '/problem/cause': self.cause,
                  '/code': self.save_code, '/run': self.queue_run,
                  '/tutor/prompt': self.tutor_prompt, '/tutor/ask': self.tutor_ask}
        with self.lock, self.store() as store:
            if path == '/problem/next':
                return self.open_next(store)
            if path == '/problem/notes':
                problem, _ = self.attempt(store, data.get('id'))
                store.run('UPDATE attempts SET notes=? WHERE problem=?', (text(data.get('notes', ''), 'Notes', 100000), problem['id']))
                return {'saved': True}
            if path == '/settings':
                return {'settings': self.save_settings(store, data)}
            if path in ('/contest/start', '/contest/refresh', '/contest/end', '/contest/label'):
                return getattr(contest, path[9:])(self, store, data, ApiError)
            if path == '/practice':
                known = {t['url'] for tasks in self.content.practice.values() for t in tasks}
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
