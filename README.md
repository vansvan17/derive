# derive

A local trainer for competitive programming where results are derived, not told.

- **Chains.** A chain is a run of small questions, each checked by the app. You are not told where it leads; the name of the result appears only when the last step is right ("you have just derived Fermat's little theorem"). A wrong answer never opens the next question, and a nudge is always a smaller question, never the answer.
- **Hard parts.** Every chain ends with questions where nothing points at the idea: count the reachable states, classify every n, solve a contest-level instance. A "Skip the warm-up" link jumps straight to them.
- **The map.** 72 ideas and the connections between them. An idea has no name on the map until you have derived it; a connection is explained only when both ends are derived.
- **Puzzles.** Short single-question puzzles on invariants, games and bits, each with one checked answer and the reason shown afterwards.
- **Real problems.** Recent Codeforces problems rated 1600 to 2500, handed out with no topic. You record your approach before any help; a solve counts only when the judge accepted it, read from your public submission list.
- **Contest mode.** A past Codeforces round against the clock for one to three handles, scored the ICPC way, with help locked while it runs, labels for every wrong submission afterwards, and an upsolve list.
- **A tutor on request.** "Ask a tutor" builds a prompt for exactly where you are, to paste into ChatGPT or, optionally, to run through a local Codex command. While something is unfinished the tutor is told to lead with questions only.
- **Evidence.** Derived, applied, recognised cold, and combined are counted separately. An idea you needed help with comes back later inside a different problem.

## Run

Needs Python 3.11+ and a C++ compiler. Nothing to install.

```sh
./launch.sh
```

It opens http://127.0.0.1:8770 and listens on this computer only. `--port N`, `--no-browser` and `--data FOLDER` are accepted. Your record is one SQLite file in `.data/`.

## Where your data lives

Nothing leaves your computer except the calls listed below, and there is no account and no server.

- **The course** (ideas, chains, puzzles, problems) is plain JSON under `content/`, in this repository.
- **Your record** (answers, proofs, attempts, contest runs, settings) is one SQLite file, `.data/learner.db`, next to the code. It is ignored by git, so it is never committed or pushed. Copy that file to back it up or move it to another computer; delete it to start again; `--data FOLDER` keeps a separate record somewhere else.
- **Outgoing calls**: your public submission list on Codeforces or AtCoder (only the handle you typed is sent); and, only if you switch them on in Settings, the local `claude` command for proof grading and the local `codex` command for the tutor.

## What is in it now

| Part | State |
|---|---|
| Map | 72 ideas in 12 areas |
| Chains | 44 (565 steps), each with a hard part; most end with CSES practice tasks |
| Puzzles | 127, in four sets: hard, invariants, games, bits |
| Real problems | 29, rated 1600 to 2500, each read with its editorial before being added |
| Proof grading | optional, through the Claude Code command on this machine; off until switched on in Settings |

## Checking the content

```sh
python3 tools/verify_content.py            # every stored answer recomputed by brute force
python3 tools/verify_content.py --links    # also re-read each problem's page and rating
python3 -m unittest discover -s tests
```

Every machine-checked step carries its own brute-force `verify` code; the verifier fails if the stored answer differs, if the checker rejects it, or if the checker accepts a wrong one. A chain that names its result before the end is a fault.

## Layout

```text
content/ideas.json, links.json     the map
content/chains/<idea>.json         one chain per idea
content/puzzles.json               the puzzle sets
content/practice.json              CSES tasks offered after a chain
content/problems.json              real problems (linked, never copied)
derive/checks.py                   answer checking (numbers, lists, formulas, counterexamples)
derive/evidence.py                 the four kinds of evidence, the working level, returns
derive/grader.py                   proof grading through the local claude command
derive/sync.py                     reading public submission lists (Codeforces, AtCoder)
derive/runner.py                   sandboxed runs of your code
derive/contest.py                  contest mode: timing and ICPC scoring from the judge
derive/tutor.py                    tutor prompts, and the optional local codex call
derive/web.py, derive/static/      the local server and pages
```

The front-end bundles in `derive/static/vendor/` (editor, maths) are built with `npm install && npm run build`; Node is needed only to rebuild them.

## Licence

MIT. See `LICENSE`.
