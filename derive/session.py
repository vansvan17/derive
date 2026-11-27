"""A sitting with the tutor: a timed session that picks what to do, watches how it goes, and calls the breaks.

Two things work together. The eyes are a set of rules that read the record the app already keeps
(every answer, every judged program, every smaller question opened, with times) plus one small signal from the
page (when something was last typed or clicked). From those it decides what to say:

  what to do now      a chain to learn from, then a task that uses it, then a problem that needs an idea of her own
  when she is stuck   a run of wrong answers, a long time on one question, the same verdict twice
  when to break       at a natural stopping point, after long enough or when the mistakes pile up
  when to stop        the time she chose is up

Everything the rules say is about how to work (try a small case, say what is counted, stop guessing). It never
contains an answer, a hint from the content, or the name of an idea that is not derived yet.

The voice is optional: when the in-app tutor (Codex) is switched on, she says what she wants from the day, the
tutor turns that into a plan made of things the app has, and a conversation runs alongside the whole sitting.
Each time it speaks it is told what she is on and what the rules have seen. A talking tutor on a chain or an
unaccepted task is help, and is recorded as help exactly like the "Ask a tutor" button.

A sitting is opt-in and locks nothing: every page works as usual while one runs, and she can move on or end it
at any moment. Every function takes the time as an argument so the rules can be tested without waiting.
"""
from __future__ import annotations
from datetime import datetime, timezone

KEY, LOG = 'session', 'session_log'
LENGTHS = (30, 60, 90, 120)
CYCLE = ('chain', 'task', 'think')
OFF_CODE_PAGE = ('predictions', 'ladder', 'transfer', 'toolbox')

BREAK_AFTER = 45 * 60          # minutes of work since the last break before one is offered
BREAK_EARLY = 20 * 60          # ... or this long, if the mistakes are piling up
MISTAKES_WINDOW, MISTAKES_MANY = 15 * 60, 6
BOUNDARY = 150                 # a break is offered only this soon after something was finished
IDLE = 5 * 60
SNOOZE = 15 * 60
LONG = {'chain': 40 * 60, 'task': 35 * 60, 'think': 35 * 60, 'tool': 45 * 60}
PLAN_MAX = 24
VOICE_GAP = 4 * 60             # the talking tutor speaks unasked at most this often


def moment(at=None):
    return at or datetime.now(timezone.utc)


def _t(iso):
    return datetime.fromisoformat(iso)


def _mins(seconds):
    return max(1, round(seconds / 60))


def _break_seconds(state, at):
    return sum(((_t(b[1]) if b[1] else at) - _t(b[0])).total_seconds() for b in state['breaks'])


def _worked(state, at):
    """Seconds of work so far: the time since the start, without the breaks."""
    end = _t(state['ended']) if state.get('ended') else at
    return max(0.0, (end - _t(state['started'])).total_seconds() - _break_seconds(state, end))


def _on_break(state):
    return bool(state['breaks'] and state['breaks'][-1][1] is None)


# ---------- what a stage is, said without giving anything away ----------
def describe(service, store, stage):
    content = service.content
    if stage['kind'] == 'chain':
        idea = content.ideas[stage['id']]
        derived = stage['id'] in service.derived(store)
        if idea.get('track') == 'cses':
            title = 'CSES: ' + idea['cses']['title']
        elif derived:
            title = idea['name']
        elif idea.get('track') == 'pattern':
            title = 'A way of thinking, not named yet'
        else:
            title = 'A chain in ' + next(a['title'] for a in content.areas if a['id'] == idea['area'])
        return {'kind': 'chain', 'title': title, 'href': '#/chain/' + stage['id'], 'label': 'Learn'}
    if stage['kind'] == 'tool':
        return {'kind': 'tool', 'title': content.tools[stage['id']]['title'], 'href': '#/tool/' + stage['id'], 'label': 'Toolbox'}
    task = content.tasks[stage['id']]
    label = {'ladder': 'Think', 'transfer': 'Think', 'predictions': 'Mock'}.get(task.get('track'), 'Use it')
    title = task['title'].split('. ', 1)[1] if task['title'].split('. ', 1)[0].isdigit() or len(task['title'].split('. ', 1)[0]) == 1 and '. ' in task['title'] else task['title']
    return {'kind': stage['kind'], 'title': title, 'href': '#/task/' + stage['id'], 'label': label}


def _task_of(service, stage):
    """The task whose acceptance finishes a stage (a Toolbox page is finished by writing its task)."""
    return service.content.tools[stage['id']]['task'] if stage['kind'] == 'tool' else stage['id']


def _complete(service, store, stage):
    if stage['kind'] == 'chain':
        return stage['id'] in service.derived(store)
    return bool(store.one('SELECT 1 FROM tasks_done WHERE task=?', (_task_of(service, stage),)))


def valid_item(service, item):
    """A plan item names something the app really has. Returns it in the shape a stage uses, or None."""
    content = service.content
    kind, ident = (item or {}).get('kind'), (item or {}).get('id')
    if kind == 'chain' and ident in content.chains:
        return {'kind': 'chain', 'id': ident}
    if kind == 'tool' and ident in content.tools:
        return {'kind': 'tool', 'id': ident}
    if kind in ('task', 'think') and ident in content.tasks and content.tasks[ident].get('track') != 'toolbox':
        return {'kind': 'think' if content.tasks[ident].get('track') in ('ladder', 'transfer') else 'task', 'id': ident}
    return None


def _pick(service, store, kind, state):
    """The next thing of one kind, or None when there is nothing of that kind left."""
    content = service.content
    skipped = {d['id'] for d in state['done'] if d['outcome'] != 'done'}       # moved on from: not offered again this sitting
    solved = {r['task'] for r in store.all('SELECT task FROM tasks_done')}
    if kind == 'chain':
        derived = service.derived(store)
        started = [i for i in content.order if i in content.chains and i not in derived and i not in skipped and service.done_steps(store, i)]
        ready = [i for i in content.order if i in content.chains and i not in derived and i not in skipped and service.chain_open(i, derived)]
        return (started or ready or [None])[0]
    if kind == 'task':
        derived = service.derived(store)
        just = [d['id'] for d in state['done'] if d['kind'] == 'chain' and d['outcome'] == 'done'][-3:]
        fits = []
        for t in content.tasks.values():
            if t.get('track', 'core') in OFF_CODE_PAGE or t['id'] in solved or t['id'] in skipped:
                continue
            ideas, _ = content.task_basis(t['id'])
            if all(i in derived for i in ideas):
                fits.append((0 if any(i in just for i in ideas) else 1, t['id']))   # first, one that rests on what she has just derived
        return min(fits, key=lambda f: f[0])[1] if fits else None
    derived = service.derived(store)
    transfer = [t['id'] for t in content.tasks.values() if t.get('track') == 'transfer' and t.get('pattern') in derived and t['id'] not in solved and t['id'] not in skipped]
    ladder = sorted((t.get('rung', 9), n, t['id']) for n, t in enumerate(content.tasks.values()) if t.get('track') == 'ladder' and t['id'] not in solved and t['id'] not in skipped)
    return transfer[0] if transfer else ladder[0][2] if ladder else None


def _next_stage(service, store, state, at):
    """Take the next thing from her plan; when the plan is used up, go round learn, use, think."""
    # The first planned thing that is not finished and can be opened now. A chain that still waits for an earlier
    # one stays in the plan and gets its turn once that one is derived.
    state['plan'] = [i for i in state.get('plan', []) if not _complete(service, store, i)]
    derived = service.derived(store)
    for k, item in enumerate(state['plan']):
        if item['kind'] != 'chain' or service.chain_open(item['id'], derived) or service.done_steps(store, item['id']):
            state['plan'].pop(k)
            state['stage'] = {**item, 'since': at.isoformat()}
            state['intro'] = at.isoformat()
            return
    was = state['stage']['kind'] if state.get('stage') else None
    start = (CYCLE.index(was) + 1) if was in CYCLE else 0
    for k in range(len(CYCLE)):
        kind = CYCLE[(start + k) % len(CYCLE)]
        chosen = _pick(service, store, kind, state)
        if chosen:
            state['stage'] = {'kind': kind, 'id': chosen, 'since': at.isoformat()}
            state['intro'] = at.isoformat()
            return
    state['stage'] = None


def _close_stage(service, store, state, outcome, at):
    stage = state.get('stage')
    if stage:
        state['done'].append({**describe(service, store, stage), 'id': stage['id'], 'outcome': outcome,
                              'seconds': round((at - _t(stage['since'])).total_seconds())})
        state['finished'] = at.isoformat()


# ---------- the actions ----------
def area_plan(service, store, goal):
    """If her words name an area of the map ("finish numbers and remainders"), every chain of it she has not derived, in map order."""
    said = ' '.join(str(goal).casefold().split())
    areas = [a['id'] for a in service.content.areas if a['title'].casefold() in said]
    derived = service.derived(store)
    return [{'kind': 'chain', 'id': i} for i in service.content.order if service.content.ideas[i]['area'] in areas and i in service.content.chains and i not in derived][:PLAN_MAX]


def default_plan(service, store):
    """Without a talking tutor: one of each, chosen by the rules."""
    state = {'done': [], 'stage': None}
    out = []
    for kind in CYCLE:
        chosen = _pick(service, store, kind, state)
        if chosen:
            out.append({'kind': kind, 'id': chosen})
    return out


def shown_plan(service, store, plan):
    return [{**item, **describe(service, store, item), 'why': str(item.get('why', ''))[:300]} for item in plan]


def start(service, store, minutes, at=None, goal='', plan=None, say=''):
    at = moment(at)
    if minutes not in LENGTHS:
        raise ValueError('Pick one of the listed lengths.')
    if store.get(KEY):
        raise ValueError('A sitting is already running.')
    state = {'started': at.isoformat(), 'minutes': minutes, 'stage': None, 'breaks': [], 'last_break': at.isoformat(), 'snooze': None,
             'offered': None, 'seen': at.isoformat(), 'route': '', 'done': [], 'ended': None, 'finished': None, 'intro': None,
             'goal': str(goal)[:2000], 'plan': [v for v in (valid_item(service, i) for i in (plan or [])) if v][:PLAN_MAX], 'chat': [], 'pending': None, 'voiced': None, 'voiced_at': None}
    if say:
        state['chat'].append({'who': 'tutor', 'text': str(say)[:6000], 'at': at.isoformat()})
    _next_stage(service, store, state, at)
    store.set(KEY, state)
    return status(service, store, at)


def seen(service, store, route, active, at=None):
    """The page reports where she is and whether anything was typed or clicked since the last report."""
    at = moment(at)
    state = store.get(KEY)
    if state:
        state['route'] = str(route)[:200]
        if active:
            state['seen'] = at.isoformat()
        store.set(KEY, state)
    return status(service, store, at)


def take_break(service, store, at=None):
    at = moment(at)
    state = store.get(KEY)
    if state and not _on_break(state):
        state['breaks'].append([at.isoformat(), None])
        state['offered'] = None
        store.set(KEY, state)
    return status(service, store, at)


def back(service, store, at=None):
    at = moment(at)
    state = store.get(KEY)
    if state and _on_break(state):
        state['breaks'][-1][1] = at.isoformat()
        state['last_break'] = state['seen'] = at.isoformat()
        if state.get('stage'):                               # the time away does not count against the question she is on
            state['resumed'] = at.isoformat()
        store.set(KEY, state)
    return status(service, store, at)


def keep_going(service, store, at=None):
    at = moment(at)
    state = store.get(KEY)
    if state:
        state['offered'] = None
        state['snooze'] = at.isoformat()
        store.set(KEY, state)
    return status(service, store, at)


def move_on(service, store, at=None):
    """Leave the current stage unfinished. It stays exactly where it is; the sitting just stops pointing at it."""
    at = moment(at)
    state = store.get(KEY)
    if state and state.get('stage') and not _on_break(state):
        _close_stage(service, store, state, 'moved on', at)
        _next_stage(service, store, state, at)
        store.set(KEY, state)
    return status(service, store, at)


def end(service, store, at=None):
    at = moment(at)
    state = store.get(KEY)
    if not state:
        return status(service, store, at)
    if _on_break(state):
        state['breaks'][-1][1] = at.isoformat()
    if state.get('stage'):
        _close_stage(service, store, state, 'done' if _complete(service, store, state['stage']) else 'unfinished', at)
    state['ended'] = at.isoformat()
    summary = recap(service, store, state, at)
    store.set(LOG, ([summary] + (store.get(LOG) or []))[:30])
    store.run('DELETE FROM settings WHERE key=?', (KEY,))
    return status(service, store, at)


# ---------- reading the record ----------
def _signals(service, store, state, at):
    """What the record says about the stage she is on, since she started it (or came back from a break)."""
    stage = state['stage']
    since = stage['since']
    clock = max(since, state.get('resumed') or since)                 # where "time on this" is measured from
    out = {'kind': stage['kind'], 'on_stage': (at - _t(since)).total_seconds()}
    if stage['kind'] == 'chain':
        chain = service.content.chains[stage['id']]
        done = service.done_steps(store, stage['id'])
        current = next((s for s in chain['steps'] if s['id'] not in done), None)
        out['step'] = current['id'] if current else None
        tries = store.all('SELECT * FROM step_attempts WHERE idea=? AND step=? AND at>=? ORDER BY id', (stage['id'], current['id'], since)) if current else []
        out['wrong'] = sum(1 for r in tries if not r['correct'])
        marks = [clock] + [r['at'] for r in done.values() if r['at'] >= since] + [r['at'] for r in tries]
        out['quiet'] = (at - _t(max(marks))).total_seconds()                      # since anything happened on this chain
        out['on_step'] = (at - _t(max([clock] + [r['at'] for r in done.values() if r['at'] >= since]))).total_seconds()
        # how many of the latest steps were right on the first try, counting back from the newest
        recent = sorted((r for r in done.values() if r['at'] >= since and r['answer'] != '(skipped)'), key=lambda r: r['at'], reverse=True)
        clean = 0
        for r in recent:
            if store.one('SELECT 1 FROM step_attempts WHERE idea=? AND step=? AND correct=0', (stage['id'], r['step'])):
                break
            clean += 1
        out['clean'] = clean
        out['helped'] = bool(current and store.one("SELECT 1 FROM nudges WHERE scope='chain' AND owner=? AND step=?", (stage['id'], current['id'])))
    else:
        task_id = _task_of(service, stage)
        tries = [r['verdict'] for r in store.all('SELECT verdict FROM task_tries WHERE task=? AND at>=? ORDER BY id', (task_id, since))]
        out['verdicts'] = tries
        last = store.one('SELECT at FROM task_tries WHERE task=? AND at>=? ORDER BY id DESC LIMIT 1', (task_id, since))
        out['quiet'] = (at - _t(max(clock, last['at'] if last else clock))).total_seconds()
        out['hints'] = store.one("SELECT COUNT(*) FROM nudges WHERE scope='task' AND owner=?", (task_id,))[0]
    return out


def _mistakes(store, since):
    wrong = store.one('SELECT COUNT(*) FROM step_attempts WHERE correct=0 AND at>=?', (since,))[0]
    bad = store.one("SELECT COUNT(*) FROM task_tries WHERE verdict NOT IN ('AC','CE') AND at>=?", (since,))[0]
    return wrong + 2 * bad                                       # a rejected program costs more than a wrong number


def _coach(sig):
    """One thing to say about how the work is going, or None. Never anything about the content."""
    if sig['kind'] == 'chain':
        wrong, mins = sig['wrong'], _mins(sig['on_step'])
        if wrong >= 5:
            return ('stuck', 'Five misses on this one question. Guessing will not get there. Open the smaller question under it, or ask the tutor from the button there. Needing help at this point is normal.')
        if wrong >= 3:
            return ('stuck', 'Three misses. Stop answering for a minute and say, in your own words, exactly what the question asks you to count or find. Then open the smaller question under it; that is what it is for.')
        if wrong == 2:
            return ('nudge', 'Two misses on this question. Before a third try, put the smallest case on the scratch pad and work it out by hand.')
        if sig['on_step'] >= 12 * 60 and not sig['helped']:
            return ('stuck', f'{mins} minutes on one question. Open the smaller question under it. It asks you something easier; it does not hand you the answer.')
        if sig['on_step'] >= 6 * 60:
            return ('nudge', f'You have been on this question for {mins} minutes. Take the smallest case that still makes sense, write its answer down, then the next one, and look at the row.')
        if sig['clean'] >= 4:
            return ('good', f'{sig["clean"]} in a row, right on the first try. If this part feels easy, "Skip the warm-up" at the top jumps to the hard questions.')
        return None
    verdicts = sig['verdicts']
    last = verdicts[-1] if verdicts else None
    if last == 'WA' and verdicts[-2:] == ['WA', 'WA']:
        return ('stuck', 'Second wrong answer in a row. Stop editing the fast solution. Write the slow, obvious one and compare the two on tiny inputs until they disagree.')
    if last == 'WA':
        return ('nudge', 'A wrong answer. Do not resubmit yet: run the sample, then the smallest inputs you can think of (a single element, all equal, already sorted).')
    if last == 'TLE':
        return ('nudge', 'Too slow. Count the steps your loops make for the largest input the statement allows. Roughly a hundred million simple steps fit in a second.')
    if last in ('RE', 'MLE'):
        return ('nudge', 'It crashed or ran out of memory. Check every array size against the largest input, and every place that indexes or divides by something read from the input.')
    if not verdicts and sig['quiet'] >= 30 * 60 and not sig['hints']:
        return ('stuck', f'{_mins(sig["quiet"])} minutes with nothing judged. Open the first hint: it only points you at small cases, not at the idea.')
    if not verdicts and sig['quiet'] >= 15 * 60:
        return ('nudge', f'{_mins(sig["quiet"])} minutes in and nothing judged yet. Write your idea as one sentence in a comment at the top of the code. If you cannot, work two small cases by hand first.')
    return None


INTRO = {
    'chain': 'Start here: a chain of small questions. Answer each one before the next appears. Use the scratch pad; nobody is timing a single question.',
    'task': 'Now use it. Write this one in the editor and judge it. Read the limits first and decide how fast the solution must be before typing.',
    'think': 'Now one where no technique is named. Work small cases by hand before writing any code, and stay with it before opening a hint.',
    'tool': 'A standard technique. Read when to reach for it and the idea, then write it yourself in the editor below and judge it.',
}


def status(service, store, at=None):
    at = moment(at)
    state = store.get(KEY)
    if not state:
        return {'running': False, 'lengths': list(LENGTHS), 'past': (store.get(LOG) or [])[:5]}
    changed = False
    praise = ''
    # A finished stage hands over to the next one on its own.
    if state.get('stage') and not _on_break(state) and _complete(service, store, state['stage']):
        was = state['stage']['kind']
        _close_stage(service, store, state, 'done', at)
        _next_stage(service, store, state, at)
        praise = {'chain': 'That chain is derived. ', 'task': 'Accepted. ', 'think': 'Accepted, and that one needed your own idea. ', 'tool': 'Accepted: that technique is yours now. '}[was]
        state['praise'] = [praise, at.isoformat()]
        changed = True
    elif state.get('praise') and (at - _t(state['praise'][1])).total_seconds() < 90:
        praise = state['praise'][0]
    worked, total = _worked(state, at), state['minutes'] * 60
    on_break = _on_break(state)
    stage = state.get('stage')
    sig = _signals(service, store, state, at) if stage and not on_break else None
    # A break is offered only just after something was finished, never in the middle of a thought.
    if not on_break and not state.get('offered') and stage:
        since_break = (at - _t(state['last_break'])).total_seconds()
        snoozed = state.get('snooze') and (at - _t(state['snooze'])).total_seconds() < SNOOZE
        edge = state.get('finished') and (at - _t(state['finished'])).total_seconds() <= BOUNDARY
        if sig and sig['kind'] == 'chain' and sig['on_step'] <= BOUNDARY and sig['on_stage'] > BOUNDARY:
            edge = True                                          # a question was just answered
        window = (at.timestamp() - MISTAKES_WINDOW)
        many = _mistakes(store, datetime.fromtimestamp(window, timezone.utc).isoformat()) >= MISTAKES_MANY
        if edge and not snoozed and (since_break >= BREAK_AFTER or (since_break >= BREAK_EARLY and many)):
            state['offered'] = ('You have worked ' + str(_mins(since_break)) + ' minutes without stopping. This is a good place for one: ten minutes, away from the screen.'
                                if since_break >= BREAK_AFTER else 'The misses are piling up, which is usually tiredness rather than the material. Take five minutes away from the screen.')
            changed = True
    if changed:
        store.set(KEY, state)
    # What to say, most pressing first.
    tone, text = 'plain', ''
    if on_break:
        away = (at - _t(state['breaks'][-1][0])).total_seconds()
        tone, text = 'break', f'On a break for {_mins(away)} min. The clock is stopped. Stand up, drink some water, look at something far away.'
    elif not stage:
        tone, text = 'good', 'There is nothing left to hand you: every chain open to you is derived and every task is accepted. End the sitting.'
    elif worked >= total:
        tone, text = 'done', praise + f'That is the {state["minutes"]} minutes you set. Finish the question you are on if you are close, then end the sitting.'
    else:
        coach = _coach(sig)
        if coach and not (praise and coach[0] == 'good'):
            tone, text = coach
        elif (at - _t(state['seen'])).total_seconds() >= IDLE:   # said only when there is nothing more useful to say
            tone, text = 'nudge', f'Nothing typed for {_mins((at - _t(state["seen"])).total_seconds())} minutes. Thinking on paper is fine. If you stepped away, call it a break so the clock stops.'
        elif sig['on_stage'] >= LONG[stage['kind']]:
            tone, text = 'nudge', f'You have given this {_mins(sig["on_stage"])} minutes. Moving on is not failing: it stays exactly where you left it, and coming back fresh often cracks it.'
        else:
            tone, text = ('good' if praise else 'plain'), praise + INTRO[stage['kind']]
    return {'running': True, 'minutes': state['minutes'], 'worked': round(worked), 'left': max(0, round(total - worked)), 'over': worked >= total,
            'on_break': on_break, 'break_for': round((at - _t(state['breaks'][-1][0])).total_seconds()) if on_break else 0,
            'offer_break': state.get('offered'), 'stage': describe(service, store, stage) if stage else None,
            'talk': ({'scope': 'chain', 'idea': stage['id'], 'step': sig['step']} if stage['kind'] == 'chain' else {'scope': 'task', 'id': _task_of(service, stage)}) if sig else None,
            'goal': state.get('goal', ''), 'chat': state.get('chat', [])[-40:], 'thinking': bool(state.get('pending')),
            'plan': [describe(service, store, i) for i in state.get('plan', [])],
            'stage_number': len(state['done']) + 1, 'tone': tone, 'say': text, 'route': state.get('route', ''),
            'steer': state.get('steer'), 'checking': bool(stage and (state.get('check') or {}).get('id') == stage['id']),
            'done': [{'label': d['label'], 'title': d['title'], 'outcome': d['outcome']} for d in state['done']]}


def seen_by_tutor(service, store, at=None):
    """A few lines for the talking tutor about what has been watched in this sitting. Empty when no sitting runs.
    Only things she did herself: times, counts, and the wrong answers she typed."""
    at = moment(at)
    state = store.get(KEY)
    if not state or not state.get('stage') or _on_break(state):
        return ''
    sig = _signals(service, store, state, at)
    lines = ['', '', 'WHAT THE APP HAS WATCHED IN THIS SITTING (use it; do not read it back to her as a list)',
             f'- She is {_mins(_worked(state, at))} minutes into a {state["minutes"]}-minute sitting and has taken {len(state["breaks"])} break(s).']
    if sig['kind'] == 'chain':
        lines.append(f'- She has been on the current question for about {_mins(sig["on_step"])} minutes and has given {sig["wrong"]} wrong answer(s) to it.')
        if sig['step']:
            typed = [r['answer'] for r in store.all('SELECT answer FROM step_attempts WHERE idea=? AND step=? AND correct=0 ORDER BY id DESC LIMIT 3', (state['stage']['id'], sig['step']))]
            if typed:
                lines.append('- Her latest wrong answers, newest first: ' + ' | '.join(a[:120] for a in typed))
    else:
        lines.append(f'- She has been on this for about {_mins(sig["on_stage"])} minutes; verdicts so far in this sitting: {", ".join(sig["verdicts"]) or "none"}; hints opened: {sig["hints"]}.')
    coach = _coach(sig)
    if coach:
        lines.append('- The app has just told her: ' + coach[1])
    if (at - _t(state['last_break'])).total_seconds() >= BREAK_AFTER:
        lines.append('- She has gone a long time without a break. If she seems tired or is going in circles, tell her to take one.')
    return '\n'.join(lines)


# ---------- the talking tutor ----------
PLANNER = '''You are a tutor planning one sitting for a student of competitive programming (about 1600 on Codeforces, preparing for an ICPC regional). She has told you what she wants from today. Build the sitting ONLY out of items from the catalogue below; the app can open nothing else.

How to choose:
- Follow her words first. If she names a topic, find the items that teach and drill it. If she is vague, pick what suits her record.
- Order: something that teaches (a chain or a Toolbox page), then something that uses it (a task), then one harder thing. 3 to 6 items for the minutes she has; a chain takes 15 to 40 minutes, a task 15 to 35.
- If she asks to finish or work through a whole area of the map (or "derive" for a topic), the plan is EVERY chain of that area that is not done, in catalogue order, and nothing else unless she asked for more. Locked ones are included: they open as she finishes the earlier ones. Up to 24 items; say honestly if that is more than fits in her time, and that the rest waits for the next sitting.
- Otherwise, a chain marked "locked" cannot be opened yet; do not pick it. Do not pick anything marked done unless she asks to revise.
- Chains marked "name hidden" teach a result she is meant to discover. NEVER write that name, or an obvious synonym, in "say" or "why": refer to it as "a chain in <area>". (If she named the topic herself you may use her own words.)

Reply with ONE JSON object and nothing else:
{"say": "two to four warm, plain sentences to her: what today will be and why", "plan": [{"kind": "chain|tool|task", "id": "<id from the catalogue>", "why": "one short sentence"}]}'''

VOICE = '''You are her tutor for a whole sitting, not a one-off helper. You sit beside her: you teach, you watch, you decide when she should change tack or rest. The app shows her the material and checks her answers; you talk.

How to talk:
- Short by default (under 120 words), plain words, one question at a time. If she asks you to teach or explain something, teach it properly: the idea in plain words, a tiny worked example, then a question to check she is with you.
- The rules given further down about not giving the answer and not naming the result still hold while the thing she is on is unfinished. Teaching background on a DIFFERENT example is always allowed.
- Use what the app has watched. If she is guessing, slow her down. If she has been stuck a long time, shrink the problem. If she is flying, say so and raise the bar.
- Reply with your next message to her only. Markdown and $...$ maths are fine.

Extra questions. When she is struggling on a chain question (the app shows misses, or a long time on it), do not just encourage her. Ask ONE easier question of your own that leads towards it: smaller numbers, a special case, or the same idea on a different example. Check her answer here in the chat, and build up with one or two more if she needs them. Then send her back to the app's question, which she answers herself. Never answer the app's question for her.

Skipping a chain. She may NOT skip a chain because she says it is easy or boring. If she wants to skip it, or she is clearly flying, test her: use the "check" action and, in the same message, set one small coding task that needs the idea this chain is building (10 to 25 lines, any language, plain logic). She pastes her code into this chat. Judge it kindly: the idea must be right and the code basically correct on an ordinary case. Ignore input and output format, speed, style and small slips, and you may ask one short follow-up about an edge case. If she has shown she knows it, use the "pass" action. If not, tell her plainly what is missing and she carries on with the chain. Tasks and Toolbox pages need no test: "next" is fine when she asks.

You also run the sitting, and you decide things yourself; you do not wait to be asked. You may take ONE action with a message, by ending your reply with a last line of exactly this form:
ACTION: {"do": "..."}
The actions:
- {"do": "break", "minutes": 5}   start her break now (the clock stops; she presses "I am back"). Use it when she is tired, going in circles, or has gone 45 minutes without one. Do not merely suggest a break when she needs one: start it.
- {"do": "next"}   leave what she is on and open the next thing in the plan. Use it when she has been stuck long after real help, or (for a task or Toolbox page) when she asks to move. On a chain the app refuses it unless she is really stuck: skipping a chain goes through the test.
- {"do": "goto", "kind": "chain|tool|task", "id": "<id from the catalogue>"}   open that now. What she was on goes back to the front of the plan, so she returns to it after. Use it to send her to something easier or to the thing her mistake shows she is missing, or when she asks for a particular thing.
- {"do": "plan", "items": [{"kind": "...", "id": "..."}]}   replace everything still planned (not the thing she is on). Use it when she changes what she wants from today, or when the plan is clearly too easy or too hard for how she is doing.
- {"do": "check"}   start the skip test for the chain she is on (set the coding task in the same message).
- {"do": "pass"}   she passed the skip test: the chain is marked as known and the next thing opens. Only after she has pasted code that shows it.
Rules for actions: take one only when it helps her, and always say in your message what you are doing and why, in one plain sentence, before the ACTION line. Never act while she is in the middle of answering something she is close to. Ids must come from the catalogue at the end. No action is the normal case.'''


def catalogue(service, store):
    """Everything a sitting can be made of, one line each, for the planner. Hidden names are included (and marked) only so
    that her request can be matched; the reply is checked for them before she sees it."""
    content = service.content
    derived = service.derived(store)
    solved = {r['task'] for r in store.all('SELECT task FROM tasks_done')}
    area = {a['id']: a['title'] for a in content.areas}
    lines, secret = ['CHAINS (kind "chain"): a guided derivation of one idea'], []
    for i in [*content.order, *[p['id'] for p in content.patterns]]:
        if i not in content.chains:
            continue
        info = content.ideas[i]
        state = 'done' if i in derived else 'started' if service.done_steps(store, i) else 'open' if service.chain_open(i, derived) else 'locked'
        hidden = i not in derived
        if hidden:
            secret.append(info['name'])
        lines.append(f'{i} | {area.get(info["area"], "")} | {info["name"]}{" (name hidden)" if hidden else ""} | {state}')
    lines += ['', 'TOOLBOX PAGES (kind "tool"): a standard technique explained, then she writes it']
    lines += [f'{t["id"]} | {t["title"]} | {"done" if t["task"] in solved else "open"}' for t in content.tools.values()]
    lines += ['', 'TASKS (kind "task"): a program she writes and the app judges. Track says what it is: ladder and transfer need an idea of her own, predictions are mock regional problems.']
    for t in content.tasks.values():
        if t.get('track') == 'toolbox':
            continue
        extra = f' rung {t["rung"]}' if t.get('rung') else f' {t["level"]}' if t.get('level') else ''
        lines.append(f'{t["id"]} | {t.get("track", "core")}{extra} | {t["title"]} | {"done" if t["id"] in solved else "open"}')
    return '\n'.join(lines), secret


def plan_prompt(service, store, goal, minutes, area=()):
    text, secret = catalogue(service, store)
    record = f'{len(service.derived(store))} chains derived, {store.one("SELECT COUNT(*) FROM tasks_done")[0]} tasks accepted so far.'
    return '\n'.join([PLANNER, '', 'WHAT SHE SAID SHE WANTS TODAY', goal.strip() or '(nothing in particular: choose for her)', '', f'TIME: {minutes} minutes', f'HER RECORD: {record}',
                      ('SHE NAMED A WHOLE AREA. Its unfinished chains, in order, are: ' + ', '.join(i['id'] for i in area) + '. Plan exactly these unless her words ask for something else too.') if area else '',
                      '', 'THE CATALOGUE', text]), secret


def read_plan(service, store, reply, secret):
    """Turn the planner's reply into a plan. Anything that is not in the app is dropped; a leaked hidden name blanks the sentence."""
    import json, re
    found = re.search(r'\{.*\}', reply, re.S)
    try:
        data = json.loads(found.group(0)) if found else {}
    except ValueError:
        data = {}
    clean = lambda s: '' if any(n.casefold() in str(s).casefold() for n in secret) else str(s)
    plan, seen_ids = [], set()
    for item in data.get('plan', []) if isinstance(data.get('plan'), list) else []:
        good = valid_item(service, item if isinstance(item, dict) else {})
        if good and good['id'] not in seen_ids and not _complete(service, store, good):
            seen_ids.add(good['id'])
            plan.append({**good, 'why': clean(item.get('why', ''))[:300]})
    return plan[:PLAN_MAX], clean(data.get('say', ''))[:3000]


def add_chat(store, who, text, at=None):
    state = store.get(KEY)
    if not state:
        return
    state.setdefault('chat', []).append({'who': who, 'text': str(text)[:8000], 'at': moment(at).isoformat()})
    state['chat'] = state['chat'][-80:]
    if who == 'tutor':
        state['pending'] = None
    store.set(KEY, state)


def voice_prompt(service, store, context, unasked='', at=None):
    """The prompt for the tutor's next message: who it is, her goal and plan, where she is (context), and the talk so far."""
    at = moment(at)
    state = store.get(KEY)
    parts = [VOICE, '', 'WHAT SHE SAID SHE WANTS TODAY', state.get('goal') or '(nothing in particular)']
    now_on = describe(service, store, state['stage'])['title'] if state.get('stage') else 'nothing: the plan is used up'
    parts += ['', 'THE SITTING', f'{_mins(_worked(state, at))} of {state["minutes"]} minutes worked. Finished so far: ' + (', '.join(f'{d["title"]} ({d["outcome"]})' for d in state['done']) or 'nothing yet')
              + f'. On now: {now_on}. Still planned: ' + (', '.join(describe(service, store, i)['title'] for i in state.get('plan', [])) or 'nothing more') + '.']
    parts += ['', 'WHERE SHE IS RIGHT NOW (the rules in this part apply to it)', context or '(between things)']
    said = state.get('chat', [])[-24:]
    who = {'tutor': 'You: ', 'me': 'She: ', 'note': '(The app did this on your instruction: '}
    parts += ['', 'THE CONVERSATION SO FAR'] + ([who[m['who']] + m['text'] + (')' if m['who'] == 'note' else '') for m in said] or ['(nothing yet)'])
    if unasked:
        parts += ['', 'SHE HAS NOT ASKED ANYTHING. You are speaking up on your own because: ' + unasked, 'Decide what she needs and do it; take an action if one is called for. Keep the message to two or three sentences (a question of your own for her may be a little longer), ending with one question or one concrete thing to do.']
    parts += ['', 'THE CATALOGUE (for actions only; "name hidden" names must never appear in your message)', catalogue(service, store)[0]]
    return '\n'.join(parts)


TESTED_OUT = '(tested out)'


def looks_like_code(text):
    """Loose on purpose: a few lines with the punctuation of a program."""
    return text.count('\n') >= 2 and sum(text.count(c) for c in '(){}[]=;:') >= 6


def ask_check(service, store, at=None):
    """She asks to skip the chain she is on. Returns True if a test can be set (a chain is open and nothing is pending)."""
    at = moment(at)
    state = store.get(KEY)
    if not state or not state.get('stage') or state['stage']['kind'] != 'chain' or _on_break(state) or state.get('pending'):
        return False
    state['check'] = {'id': state['stage']['id'], 'at': at.isoformat()}
    state.setdefault('chat', []).append({'who': 'me', 'text': 'I think I already know this chain and want to skip it. Test me.', 'at': at.isoformat()})
    store.set(KEY, state)
    return True


def split_action(reply):
    """Take the ACTION line off the end of a reply. Returns (the message, the action or None)."""
    import json, re
    found = re.search(r'\n?\s*ACTION:\s*(\{.*\})\s*$', reply, re.S)
    if not found:
        return reply.strip(), None
    try:
        action = json.loads(found.group(1))
    except ValueError:
        action = None
    return reply[:found.start()].strip(), action if isinstance(action, dict) else None


def act(service, store, action, at=None):
    """Carry out what the talking tutor decided. Everything here can be undone by her with one button, and nothing
    is ever locked. Returns a line for the conversation saying what was done, or None if nothing was."""
    at = moment(at)
    state = store.get(KEY)
    if not state or not isinstance(action, dict) or _on_break(state):
        return None
    do, note = action.get('do'), None
    steer = lambda: state.update(steer={'n': state.get('steer', {}).get('n', 0) + 1, 'href': describe(service, store, state['stage'])['href']}) if state.get('stage') else None
    if do == 'break':
        state['breaks'].append([at.isoformat(), None])
        state['offered'] = None
        note = 'The tutor started a break. The clock is stopped; press "I am back" when you are.'
    elif do == 'check' and state.get('stage') and state['stage']['kind'] == 'chain':
        state['check'] = {'id': state['stage']['id'], 'at': at.isoformat()}
        note = 'Skip test started. Write the code the tutor asks for and paste it here. It does not have to be perfect.'
    elif do == 'pass' and state.get('stage') and state['stage']['kind'] == 'chain':
        check, idea = state.get('check') or {}, state['stage']['id']
        showed = [m for m in state.get('chat', []) if m['who'] == 'me' and m['at'] >= check.get('at', '9') and looks_like_code(m['text'])]
        if check.get('id') != idea or not showed:
            return None                                       # no test was set, or no code was shown: nothing is waved through
        for step in service.content.chains[idea]['steps']:
            store.run('INSERT OR IGNORE INTO steps_done VALUES(?,?,?,?)', (idea, step['id'], at.isoformat(), TESTED_OUT))
        store.run('INSERT OR IGNORE INTO discoveries VALUES(?,?)', (idea, at.isoformat()))
        state['check'] = None
        _close_stage(service, store, state, 'tested out', at)
        _next_stage(service, store, state, at)
        steer()
        note = 'You passed the skip test: ' + service.content.ideas[idea]['name'] + ' is marked as known.' + (' Next: ' + describe(service, store, state['stage'])['title'] + '.' if state.get('stage') else '')
    elif do == 'next' and state.get('stage'):
        if state['stage']['kind'] == 'chain':
            sig = _signals(service, store, state, at)
            if sig['wrong'] < 3 and sig['on_step'] < 12 * 60:
                return None                                   # not stuck: a chain is left through the skip test, not by asking
        _close_stage(service, store, state, 'moved on', at)
        _next_stage(service, store, state, at)
        steer()
        note = 'The tutor moved you on' + (' to: ' + describe(service, store, state['stage'])['title'] if state.get('stage') else '') + '. What you left stays where it is.'
    elif do == 'goto':
        item = valid_item(service, action)
        current = state.get('stage')
        if item and not _complete(service, store, item) and not (current and current['id'] == item['id']):
            if item['kind'] == 'chain' and not (service.chain_open(item['id'], service.derived(store)) or service.done_steps(store, item['id'])):
                return None                                   # it cannot be opened yet
            state['plan'] = [i for i in state.get('plan', []) if i['id'] != item['id']]
            if current:
                if not _complete(service, store, current):
                    state['plan'].insert(0, {'kind': current['kind'], 'id': current['id']})   # she comes back to it afterwards
                _close_stage(service, store, state, 'set aside', at)
            state['stage'] = {**item, 'since': at.isoformat()}
            steer()
            note = 'The tutor opened: ' + describe(service, store, item)['title'] + '. What you were on comes back right after it.'
    elif do == 'plan' and isinstance(action.get('items'), list):
        current = state['stage']['id'] if state.get('stage') else None
        items, seen_ids = [], {current}
        for raw in action['items']:
            item = valid_item(service, raw if isinstance(raw, dict) else {})
            if item and item['id'] not in seen_ids and not _complete(service, store, item):
                seen_ids.add(item['id'])
                items.append(item)
        if items:
            state['plan'] = items[:PLAN_MAX]
            note = 'The tutor changed the plan. Still to come: ' + ', '.join(describe(service, store, i)['title'] for i in state['plan'][:6]) + ('…' if len(state['plan']) > 6 else '') + '.'
    if not note:
        return None
    state.setdefault('chat', []).append({'who': 'note', 'text': note, 'at': at.isoformat()})
    store.set(KEY, state)
    return note


def wants_voice(service, store, at=None):
    """Whether the talking tutor should speak without being asked, and why. Marks it so the same moment is not voiced twice."""
    at = moment(at)
    state = store.get(KEY)
    if not state or state.get('pending') or _on_break(state) or not state.get('stage'):
        return None
    if state.get('voiced_at') and (at - _t(state['voiced_at'])).total_seconds() < VOICE_GAP:
        return None
    stage, sig = state['stage'], _signals(service, store, state, at)
    coach = _coach(sig)
    key, why = None, None
    if state.get('voiced') is None or not str(state['voiced']).startswith(stage['id'] + '|'):
        key, why = stage['id'] + '|start', 'she has just started this. Tell her in a sentence what it is for in today\'s plan and how to begin.'
    elif state.get('offered'):
        key, why = 'break|' + state['last_break'], 'she is due a break and has just finished something (' + state['offered'] + '). Unless she is in full flow and doing well, start the break now with the action.'
    elif _worked(state, at) >= state['minutes'] * 60:
        key, why = 'over', 'the time she set is up. Tell her in two sentences what she got done today and that she can end the sitting or carry on; do not push either way.'
    elif coach and coach[0] == 'stuck':
        key, why = f'{stage["id"]}|stuck|{sig.get("step") or len(sig.get("verdicts", []))}', 'the app sees she is stuck: ' + coach[1] + ' Give her an easier question of your own to get her moving.'
    elif stage['kind'] == 'chain' and sig['wrong'] == 2:
        key, why = f'{stage["id"]}|miss|{sig["step"]}', 'she has missed the question she is on twice. Give her one easier question of your own that leads towards it.'
    elif stage['kind'] == 'chain' and sig['clean'] >= 5:
        key, why = f'{stage["id"]}|flying', f'she has answered {sig["clean"]} questions in a row on the first try. Decide whether this chain is below her: if so, offer the skip test (the check action with a small coding task).'
    elif sig['on_stage'] >= LONG[stage['kind']]:
        key, why = f'{stage["id"]}|long', f'she has been on this for {_mins(sig["on_stage"])} minutes. Decide: shrink it with a question of your own, send her to something easier first (goto), or move her on.'
    if not key or key == state.get('voiced'):
        return None
    state['voiced'], state['voiced_at'] = key, at.isoformat()
    store.set(KEY, state)
    return why


def recap(service, store, state, at):
    """What happened in the sitting, counted from the record."""
    start, stop = state['started'], state['ended'] or at.isoformat()
    span = (start, stop)
    right = store.one('SELECT COUNT(*) FROM steps_done WHERE at>=? AND at<=? AND answer NOT IN (?,?)', (*span, '(skipped)', TESTED_OUT))[0]
    wrong = store.one('SELECT COUNT(*) FROM step_attempts WHERE correct=0 AND at>=? AND at<=?', span)[0]
    accepted = store.one('SELECT COUNT(*) FROM tasks_done WHERE at>=? AND at<=?', span)[0]
    rejected = store.one("SELECT COUNT(*) FROM task_tries WHERE verdict NOT IN ('AC','CE') AND at>=? AND at<=?", span)[0]
    helped = store.one('SELECT COUNT(*) FROM nudges WHERE at>=? AND at<=?', span)[0]
    worst = store.one('SELECT idea, step, COUNT(*) AS n FROM step_attempts WHERE correct=0 AND at>=? AND at<=? GROUP BY idea, step ORDER BY n DESC LIMIT 1', span)
    hardest = None
    if worst and worst['n'] >= 3 and worst['idea'] in service.content.chains:
        number = next((k + 1 for k, s in enumerate(service.content.chains[worst['idea']]['steps']) if s['id'] == worst['step']), None)
        where = describe(service, store, {'kind': 'chain', 'id': worst['idea']})
        hardest = {'title': where['title'], 'href': where['href'], 'question': number, 'misses': worst['n']}
    unfinished = next((d for d in state['done'] if d['outcome'] != 'done'), None)   # the first thing she left open
    return {'at': start, 'minutes': state['minutes'], 'worked': round(_worked(state, at)), 'breaks': len(state['breaks']), 'break_seconds': round(_break_seconds(state, at)),
            'stages': [{'label': d['label'], 'title': d['title'], 'href': d['href'], 'outcome': d['outcome'], 'seconds': d['seconds']} for d in state['done']],
            'right': right, 'wrong': wrong, 'accepted': accepted, 'rejected': rejected, 'helped': helped, 'hardest': hardest,
            'next': {'title': unfinished['title'], 'href': unfinished['href']} if unfinished else None}
