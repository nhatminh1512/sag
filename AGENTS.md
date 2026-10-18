# AGENTS.md

Instructions for coding agents working **on** this repository.

## What this repository is

`sag` is a Python CLI that orchestrates other coding-agent CLIs. It runs one
task through seven named steps — plan, write-test, execute, review, verify,
remember, improve — with file handoff and a self-check between steps.

- `sag.py` — CLI: `setup`, `check`, `run`, `report`, `demo`
- `orchestrator.py` — the seven steps, prompts, agent invocation, gates
- `clis.py` — CLI registry and argv builder (stdin/argv, model flags)
- `recursion.py` — task-level recursion: propose / probe / compose / reflect
- `skills/<step>/SKILL.md` — one role card per step
- `tests/test_core.py` — dependency-free tests

## Commands

```bash
python3 -m unittest discover -s tests -v   # tests
python3 sag.py --help                     # CLI
python3 sag.py demo                       # dry run, no model calls
npm pack --dry-run                        # npm package contents
```

## Rules

- Keep the code dependency-free (stdlib only). The npm launcher only forwards to
  `python3 sag.py`.
- Do not commit generated state: `runs/`, `memory/`, `.sag/`, `config.json`,
  `plan.md`, `test-plan.md`, `execution.md`, `review.md`, `verify.json`,
  `improve.md`, `diff.patch`, `test-output*.txt`.
- Keep each `skills/<step>/SKILL.md` under 6000 characters (guardrail).
- A step's role card is injected into the prompt; do not hard-code step prompts
  in Python.
- Model/CLI selection belongs in config (`cli`, `model`, `bin`, `base`,
  `prompt`, `model_flag`), not in `orchestrator.py`.
- Preserve the two invariants: a test must be RED before `execute`, and `verify`
  must read `review.md` and fail on open blocking issues.
- No automatic `git commit` or merge anywhere in the pipeline.

## If you change the pipeline

Update, in the same commit:

1. `skills/<step>/SKILL.md` if the step's instructions change.
2. `tests/test_core.py` if scoring, step expansion, or CLI argv changes.
3. `README.md` and `llms.txt` if commands or behaviour change.
4. `package.json` version only when publishing; `npm publish` is manual.
