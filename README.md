# derive

A local trainer for competitive programming where results are derived, not told.

- **Chains.** A chain is a run of small questions, each checked by the app. You are not told where it leads; the name of the result appears only when the last step is right ("you have just derived Fermat's little theorem"). A wrong answer never opens the next question, and a nudge is always a smaller question, never the answer.
- **The map.** 50 ideas and the connections between them. An idea has no name on the map until you have derived it; a connection is explained only when both ends are derived.
- **Real problems.** Problems from real judges, handed out with no topic. You record your approach before any help; a solve counts only when the judge accepted it, read from your public submission list.
- **Evidence.** Derived, applied, recognised cold, and combined are counted separately. An idea you needed help with comes back later inside a different problem.

## Run

Needs Python 3.11+ and a C++ compiler. Nothing to install.

```sh
./launch.sh
```

It opens http://127.0.0.1:8770 and listens on this computer only. `--port N`, `--no-browser` and `--data FOLDER` are accepted. Your record is one SQLite file in `.data/`.

## What is in it now

| Part | State |
|---|---|
| Map | 50 ideas, 46 connections |
| Chains | 12 written (112 steps): remainders, multiplication mod a prime, Fermat, inverses, gcd by subtraction, Euclid, Bézout, divisor counts, parity, invariants mod m, monovariants, contribution counting |
| Real problems | none yet (see below) |
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
content/problems.json              real problems (linked, never copied)
derive/checks.py                   answer checking (numbers, lists, formulas, counterexamples)
derive/evidence.py                 the four kinds of evidence, the working level, returns
derive/grader.py                   proof grading through the local claude command
derive/sync.py                     reading public submission lists (Codeforces, AtCoder)
derive/runner.py                   sandboxed runs of your code
derive/web.py, derive/static/      the local server and pages
```

The front-end bundles in `derive/static/vendor/` (editor, maths) are built with `npm install && npm run build`; Node is needed only to rebuild them.
