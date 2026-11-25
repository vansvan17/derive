"""The learner's record: one SQLite file, separate from the course content.

Content (ideas, chains, problems) is read-only JSON in git. Everything the
learner does is written here, so content can change without touching history.
"""
from __future__ import annotations
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

SCHEMA = '''
-- every answer typed into a chain step, right or wrong
CREATE TABLE IF NOT EXISTS step_attempts(id INTEGER PRIMARY KEY, at TEXT NOT NULL, idea TEXT NOT NULL,
  step TEXT NOT NULL, answer TEXT NOT NULL, correct INTEGER NOT NULL);
-- a step that has been answered correctly (the gate that lets the next step show)
CREATE TABLE IF NOT EXISTS steps_done(idea TEXT NOT NULL, step TEXT NOT NULL, at TEXT NOT NULL,
  answer TEXT NOT NULL, PRIMARY KEY(idea, step));
-- smaller questions opened on a step or a problem ("scope" is chain or problem)
CREATE TABLE IF NOT EXISTS nudges(scope TEXT NOT NULL, owner TEXT NOT NULL, step TEXT NOT NULL,
  level INTEGER NOT NULL, at TEXT NOT NULL, PRIMARY KEY(scope, owner, step, level));
-- an idea whose whole chain is finished: its name may now be shown
CREATE TABLE IF NOT EXISTS discoveries(idea TEXT PRIMARY KEY, at TEXT NOT NULL);
-- written proofs and what the grader said about them
CREATE TABLE IF NOT EXISTS proofs(id INTEGER PRIMARY KEY, at TEXT NOT NULL, scope TEXT NOT NULL, owner TEXT NOT NULL,
  step TEXT NOT NULL, text TEXT NOT NULL, status TEXT NOT NULL, feedback TEXT NOT NULL DEFAULT '{}', graded_at TEXT);
-- one row per real problem the learner has opened
CREATE TABLE IF NOT EXISTS attempts(problem TEXT PRIMARY KEY, opened_at TEXT NOT NULL, approach TEXT, cue TEXT,
  committed_at TEXT, editorial_at TEXT, gave_up_at TEXT, solved_at TEXT, verdict_source TEXT, submission TEXT,
  cold INTEGER, cause TEXT, notes TEXT NOT NULL DEFAULT '', returned_for TEXT);
-- saved code, per problem, language and file (solution, brute force, generator)
CREATE TABLE IF NOT EXISTS code(owner TEXT NOT NULL, language TEXT NOT NULL, file TEXT NOT NULL, code TEXT NOT NULL,
  updated TEXT NOT NULL, PRIMARY KEY(owner, language, file));
-- an idea that must come back inside a different problem, and when
CREATE TABLE IF NOT EXISTS returns(id INTEGER PRIMARY KEY, idea TEXT NOT NULL, due TEXT NOT NULL, reason TEXT NOT NULL,
  created TEXT NOT NULL, done_at TEXT, done_by TEXT);
-- background runs of the learner's code and proof grading
CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL, created TEXT NOT NULL,
  updated TEXT NOT NULL, payload TEXT NOT NULL, result TEXT);
-- each time a tutor was asked for (a copied prompt or Codex); "gated" means the step or problem was unfinished, so it counts as help
CREATE TABLE IF NOT EXISTS tutor_uses(id INTEGER PRIMARY KEY, at TEXT NOT NULL, scope TEXT NOT NULL, owner TEXT NOT NULL,
  step TEXT NOT NULL, outlet TEXT NOT NULL, gated INTEGER NOT NULL);
-- contest mode: one row per timed run of a real round; "board" is the last score read from the judge
CREATE TABLE IF NOT EXISTS contests(id INTEGER PRIMARY KEY, contest INTEGER NOT NULL, started_at TEXT NOT NULL, minutes INTEGER NOT NULL,
  handles TEXT NOT NULL, board TEXT NOT NULL, checked_at TEXT, ended_at TEXT);
-- what went wrong in each wrong submission of a run, as labelled afterwards
CREATE TABLE IF NOT EXISTS contest_mistakes(run INTEGER NOT NULL, submission TEXT NOT NULL, label TEXT NOT NULL, at TEXT NOT NULL,
  PRIMARY KEY(run, submission));
-- puzzles: every answer given, and how each puzzle ended (solved, with how many wrong tries first, or shown)
CREATE TABLE IF NOT EXISTS puzzle_tries(id INTEGER PRIMARY KEY, at TEXT NOT NULL, puzzle TEXT NOT NULL, answer TEXT NOT NULL, correct INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS puzzles_done(puzzle TEXT PRIMARY KEY, at TEXT NOT NULL, wrong INTEGER NOT NULL, shown INTEGER NOT NULL);
-- implement tasks: every judged submission, and the tasks that have been accepted
CREATE TABLE IF NOT EXISTS task_tries(id INTEGER PRIMARY KEY, at TEXT NOT NULL, task TEXT NOT NULL, verdict TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tasks_done(task TEXT PRIMARY KEY, at TEXT NOT NULL, tries INTEGER NOT NULL);
-- break it: every input tried against a wrong solution, and the ones that were broken (with the input that did it)
CREATE TABLE IF NOT EXISTS break_tries(id INTEGER PRIMARY KEY, at TEXT NOT NULL, item TEXT NOT NULL, input TEXT NOT NULL, broken INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS breaks_done(item TEXT PRIMARY KEY, at TEXT NOT NULL, tries INTEGER NOT NULL, nudges INTEGER NOT NULL, input TEXT NOT NULL);
-- the source the judge accepted, per task and language (the editor's saved code can be changed afterwards; this cannot)
CREATE TABLE IF NOT EXISTS accepted_code(task TEXT NOT NULL, language TEXT NOT NULL, code TEXT NOT NULL, at TEXT NOT NULL, PRIMARY KEY(task, language));
-- recognise: what she said cracks a statement, how long she took, and how she rated herself against the stored observations
CREATE TABLE IF NOT EXISTS recognitions(id INTEGER PRIMARY KEY, at TEXT NOT NULL, problem TEXT NOT NULL, guess TEXT NOT NULL, seconds INTEGER NOT NULL,
  rating TEXT, rated_at TEXT);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
'''


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.folder / 'learner.db', timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript(SCHEMA)
        # added later: the idea whose finished chain a problem was opened from (the topic was known, so the solve is not cold)
        if 'topic_known' not in {r[1] for r in self.db.execute('PRAGMA table_info(attempts)')}:
            self.db.execute('ALTER TABLE attempts ADD COLUMN topic_known TEXT')
        if 'move' not in {r[1] for r in self.db.execute('PRAGMA table_info(attempts)')}:
            # the move that cracks the problem, whether she made it herself (1/0), and her one-sentence lesson
            self.db.execute('ALTER TABLE attempts ADD COLUMN move TEXT')
            self.db.execute('ALTER TABLE attempts ADD COLUMN move_made INTEGER')
            self.db.execute("ALTER TABLE attempts ADD COLUMN lesson TEXT NOT NULL DEFAULT ''")
        self.db.commit()

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def run(self, sql, args=()):
        cursor = self.db.execute(sql, args)
        self.db.commit()
        return cursor

    def one(self, sql, args=()):
        return self.db.execute(sql, args).fetchone()

    def all(self, sql, args=()):
        return self.db.execute(sql, args).fetchall()

    def get(self, key, default=None):
        row = self.one('SELECT value FROM settings WHERE key=?', (key,))
        return json.loads(row[0]) if row else default

    def set(self, key, value):
        self.run('INSERT OR REPLACE INTO settings VALUES(?,?)', (key, json.dumps(value)))
