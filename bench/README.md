# Benchmark — can a self-grading agent catch its own false pass?

## Question

When one agent plans, writes the test, implements, and runs the suite itself,
how often does it claim success on work an independent reviewer would reject?
And how does the same task fare through `sag`'s delivery pipeline?

## Design

- **10 small tasks** on a tiny Python task list (`base/`). Each task is a real
  behaviour change with a crisp acceptance criterion.
- Each `(task, arm)` pair gets a **fresh copy** of `base/` with its own git
  history.
- **Arm `single`** — one Claude call: *"Do all of it yourself: plan, write the
  test, implement, run the tests."* It may edit anything.
- **Arm `sag`** — the pipeline's delivery steps only:
  `plan → write-test → execute → review → verify`, all backed by Claude so the
  comparison isolates the process, not the model.
- **Judge** — a separate Claude call with no knowledge of the arm. It sees only
  the task, the final diff, and the test output, and returns
  `{implements, test_covers, blocking_issues, verdict}`.
- **Claim** — `single` claims success when `python3 run_tests.py` exits 0;
  `sag` claims success when `verify.json` says `pass`.
- **False pass** — the claim is true and the judge's verdict is `fail`.

## Why these tasks

Every task has an easy way to look green without doing the work:

- a test written into the file but never registered in `__main__`;
- a test that only imports the module;
- an implementation that satisfies the example but not the rule.

That is the failure mode the benchmark is designed to expose.

## Run

```bash
python3 bench/run.py --workers 2
python3 bench/run.py --tasks 1,2,3 --arms single
```

Results are written incrementally to `results/runs.jsonl`, with a summary in
`results/summary.json`.

## Results

Pilot run on 2026-10-18. Claude backed every step and the judge.

| Arm | Valid tasks | Claims | False passes | False-pass rate | Median time |
|---|---:|---:|---:|---:|---:|
| `single` | 8 | 8 | 0 | 0% | 34s |
| `sag` | 6 | 6 | 0 | 0% | 3m 14s |

| Task | `single` | `sag` |
|---|---|---|
| 01-empty-title | pass | pass |
| 02-complete-unknown | pass | pass |
| 03-stats-total | pass | pass |
| 04-search | pass | pass |
| 05-delete | pass | pass |
| 06-sort | pass | pass |
| 07-due-soon | pass | inconclusive |
| 08-json | pass | inconclusive |
| 09-rename | inconclusive | inconclusive |
| 10-bulk-add | inconclusive | inconclusive |

**What this says.** On the six tasks both arms completed, the single agent did
not produce a false pass. The pipeline was about 5.7× slower (3m 14s vs 34s
median) for the same verdict. With a strong model and small, unambiguous tasks,
this benchmark did not reproduce the failure mode it was built to expose.

**What it does not say.** It is not evidence that the pipeline is useless. The
failure mode needs a task where a green suite can hide an incomplete change
(task 09 and 10 are the candidates), a weaker executor, or a larger repository.
Four tasks are inconclusive because the Claude session limit was reached
mid-run; `bench/run.py` reruns them with the same inputs.

**Next.** Rerun 07–10 after the limit resets; add a DeepSeek cohort; add three
ambiguous tasks where the acceptance criterion needs judgement.

## Threats to validity

- **Same model everywhere.** Using Claude for every step isolates the process,
  but it does not tell us how the pipeline behaves with Grok/DeepSeek in the
  loop. It makes the comparison conservative: the `single` arm is a strong
  baseline.
- **The judge is also a model.** It can miss things. The judge is blind to the
  arm, but it is not ground truth; a human spot-check of disagreements is
  included in the notes.
- **Small n.** Ten tasks give a direction, not a confidence interval. Treat the
  rate as a pilot estimate.
- **Toy repository.** The base is deliberately small so a run finishes in
  minutes. Real repositories add build systems, flaky tests, and ambiguity.

## Reproducing

Requires `claude` on `PATH` and a logged-in Claude Code session. No other
credentials are needed; the benchmark does not touch npm or the network beyond
the CLI.
