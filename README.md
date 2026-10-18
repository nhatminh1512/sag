# sag

**One command per repo for a multi-agent coding pipeline.**

```bash
cd my-repo
sag
```

`sag` takes one task and runs it through seven named agents — plan, write-test,
execute, review, verify, remember, improve — each backed by a different CLI
(Claude Code, Grok, or DeepSeek Harness). Every handoff is a file on disk, every
step has a self-check, and the harness itself can be improved by running the
same task through candidate harnesses and keeping the one that behaves best.

```
plan ──▶ write-test ──▶ execute ──▶ review ──▶ verify ──▶ remember ──▶ improve
Claude     Grok          DeepSeek    Claude     Grok       code         Claude
plan.md    tests (RED)   diff.patch  review.md  verify.json memory/      improve.md
```

---

## Why another agent pipeline

Three failure modes motivated it:

1. **One agent grades its own work.** A single agent that plans, writes, tests,
   and reviews will pass its own mistakes. `sag` separates the roles: the test
   author is independent of the executor, and the reviewer is independent of both.
2. **The test never runs.** A test written into a folder the repo's runner does
   not execute still looks green. `write-test` must prove the suite is **RED**
   before `execute` starts.
3. **The reviewer's verdict never reaches the verifier.** A verifier that only
   reads the test output can report `pass: true` while the reviewer is asking
   for changes. `verify` reads `review.md` and must fail on any open blocking
   issue.

---

## Architecture

### The seven steps

| # | Step | Agent | Output | Self-check before handing off |
|---|---|---|---|---|
| 1 | `plan` | Claude, read-only | `plan.md` — goal, steps, files, feature criteria, regression criteria, risks | every required section present; criteria are testable |
| 2 | `write-test` | Grok, independent of the executor | test + `test-plan.md` | the repo's real test command must **fail** (test is wired in and RED) |
| 3 | `execute` | DeepSeek Harness | code + `diff.patch` + `execution.md` | the diff is non-empty and the suite passes |
| 4 | `review` | Claude, fresh context | `review.md` — `APPROVE` or `REQUEST_CHANGES` | verdict + blocking issues with `file:line` |
| 5 | `verify` | Grok + the real test run | `verify.json` — per-criterion evidence | verdict must agree with review; a `REQUEST_CHANGES` review forces `pass: false` |
| 6 | `remember` | deterministic | `memory/decisions.md`, `lessons.md`, `context.md` | runs without a model call |
| 7 | `improve` | Claude, meta-agent | `improve.md`, `memory/improvements.md` | concrete SOP edits, not generalities |

### Handoff is files, not transcripts

Each step reads the previous step's artifacts from disk. No prompt carries a
whole conversation: `plan.md`, `test-plan.md`, `diff.patch`, `review.md`, and
`verify.json` are the interface. The prompt for each agent is a short role card
plus a pointer to those files.

### Human gates

By default the pipeline stops **before `execute`**, after the plan and the RED
tests exist, so you can read them and decide. `--auto` skips the gate. `sag`
never runs `git commit` or merges: the final action stays manual.

### Per-repo harness

`sag setup` writes `.sag/` inside the repo:

```
.sag/
  config.json          step → CLI / permission / model, test command, gates
  harness/skills/      one SKILL.md per step (the project owns its copy)
  guardrails.json      max skill size, test-must-be-red, no grader leakage
  memory/              decisions, lessons, context, improvements
  runs/<id>/           one directory per run — the evidence
  library/             adopted harnesses + lessons, per domain
```

Editing `.sag/harness/skills/verify/SKILL.md` changes how *this* repo verifies
and nothing else. The harness is a versioned artifact, not hidden prompt text.

---

## The harness model

A harness is everything around the model that lets it act as an agent. Following
[Harness²](https://github.com/google-research/harness2), `sag` keeps eight
editable components as separate surfaces instead of one prompt blob:

| Component | Where it lives in `sag` |
|---|---|
| System prompt | the per-step `SKILL.md` body injected into the prompt |
| Guardrails | `guardrails.json` + the self-checks in `orchestrator.py` |
| Memory | `.sag/memory/` (decisions, lessons, context, improvements) |
| Tool guidance | the CLI invocation contract in `orchestrator.py` (`claude -p`, `grok -p`, `dsh headless`) |
| Subagents | one named agent per step |
| Skills | `.sag/harness/skills/<step>/SKILL.md` |
| Scripts | `sag.py`, `orchestrator.py`, `recursion.py` |
| Plugins | whatever each CLI loads from its own environment (not isolated by default) |

Two consequences worth knowing:

- **Skills are injected, not discovered.** The orchestrator reads the role card,
  strips the frontmatter, and appends the task-specific context. There is no
  hidden skill auto-trigger inside the pipeline.
- **The CLI still loads its own world.** `claude` and `grok` read their user
  plugins, MCP servers, and skills unless you pass isolation flags. `dsh` is
  narrower: it loads only the plugins in its active profile.

---

## Two levels of recursion

### Task-level: Propose → Probe → Compose

```bash
sag --k 2
```

1. **Propose** — an editor agent reads the run's evidence (`review.md`,
   `verify.json`, `test-output.txt`, `improve.md`) and edits **at most one**
   skill. The contract is *omitted-is-inherited*: only what the evidence
   justifies changes. It writes `proposal.md` with change, evidence, hypothesis,
   and the affected steps.
2. **Probe** — the candidate harness is applied to the same task and the
   affected steps are re-run: from the earliest affected step through `verify`.
   A review/verify probe reuses the baseline diff; a write-test/execute probe
   starts from a clean `git worktree` at `HEAD`.
3. **Compose** — the winner is chosen by behaviour, not by the proposal's claim:

   ```
   score = tests_ok×3 + review_approve×2 + consistent×3 + criteria_met×0.1
   consistent = verify.pass == (review.approve and tests_ok)
   ```

   A verifier that says `pass` while the reviewer says `REQUEST_CHANGES` scores
   **lower** than one that agrees. Ties keep the baseline.

The winning harness is adopted (with a backup), and a failed probe never breaks
the run.

### Harnessing-level: reflect into a library

After adoption, `sag` stores the full winning harness plus an `EXPERIENCE.md`
(cue, change, evidence) under `.sag/library/<domain>/<task>/`. The next task in
the same domain can read what worked before. The library holds the whole tree,
never a summary.

---

## Methodology and prior art

`sag` is an independent implementation. It borrows **ideas**, not code, from:

### Lauren Tan's "AI team" architecture

| Principle | How `sag` implements it |
|---|---|
| 1. A chief of staff receives everything | `sag.py` / `orchestrator.py` receive the task, route, gate — and never write code |
| 2. Name + role + memory per agent | seven named steps, a role card each, shared `memory/` |
| 3. Repetitive work becomes an SOP | the fixed pipeline; the handoff contract is a set of files |
| 4. Self-check before submitting | plan sections, RED test, non-empty diff, review verdict, verify evidence |
| 5. The lead delegates, it does not work | the orchestrator only routes and gates |
| 6. Gradual autonomy | a human gate before `execute`; commit/merge stays manual; the meta-agent proposes SOP edits |

### Harness² (Google Research, Apache-2.0)

- **Eight harness components** — used as the layout above.
- **Task-level recursion** — Propose / Probe / Compose from behavioural
  contrasts, no ground-truth feedback required.
- **Harnessing-level recursion** — a persistent, per-domain library of adopted
  harnesses and evidence-backed lessons.
- **Evidence on disk, prompt as a pointer** — artifacts are never truncated to
  fit a prompt.
- **Omitted-is-inherited, validate before adoption, fall back to the current
  harness** on an invalid proposal.
- **CLI shape** — `setup → check → run → report`, with a credential-free demo.

### GSD

- Setup once per project, then a single command in that directory:
  `cd repo && sag`, the same rhythm as `claude` or `grok`.

---

## Install

Requirements:

- Python 3.10+
- At least one of: `claude`, `grok`, `dsh` on `PATH`
- A git repository to work in

```bash
git clone git@github.com:nhatminh1512/sag.git
cd sag
ln -sf "$PWD/sag.py" ~/.local/bin/sag
chmod +x sag.py
sag --help
```

The CLIs keep their own credentials (`~/.claude/.credentials.json`, Grok login,
`DEEPSEEK_API_KEY`). `sag` does not store secrets.

---

## Quick start

```bash
cd ~/code/my-project
sag setup          # once: detects the CLIs, the test command, writes .sag/
sag check          # preflight
sag                # prompts for a task, then runs the pipeline
```

Non-interactive:

```bash
sag "Add a GET /health endpoint returning {\"ok\": true}" --auto
```

Review the result:

```bash
sag report
```

Try it without spending tokens:

```bash
sag demo           # dry-run of the whole flow
```

---

## Commands

| Command | What it does |
|---|---|
| `sag setup` | Interactive setup for this repo. `--yes`, `--force`, `--test-cmd "..."`, `--no-gates` |
| `sag check` | Preflight: git, CLIs, test command, seven skills, guardrail caps |
| `sag` | Prompt for a task and run all seven steps |
| `sag "task"` | Run with the task given |
| `sag --auto` | Skip human gates |
| `sag --steps plan,write-test` | Run a subset |
| `sag --dry-run` | Print the flow, no model calls |
| `sag --run-id <id>` | Continue an existing run (task read from its `task.txt`) |
| `sag report [--run-id <id>]` | Summarize a run |
| `sag demo` | Dry-run with a sample task |
| `sag --k 2` | Task-level recursion: baseline + one propose/probe/compose |
| `sag --k N --mode sequential` | Refine over several rounds |
| `sag --k 2 --baseline-run <dir>` | Reuse an existing run as the baseline |
| `sag --k 2 --probe-steps review,verify` | Force the probe's step list |
| `sag --k 2 --full-probe` | Probe `plan → verify` on a clean worktree (expensive) |

---

## Configuration

`.sag/config.json`:

```json
{
  "repo": "/abs/path/to/repo",
  "domain": "my-project",
  "test_cmd": ".venv/bin/python test_regressions.py",
  "steps": {
    "plan":       {"cli": "claude", "permission": "acceptEdits"},
    "write-test": {"cli": "grok",   "permission": "auto"},
    "execute":    {"cli": "dsh",    "permission": "auto", "model": "deepseek-flash"},
    "review":     {"cli": "claude", "permission": "acceptEdits"},
    "verify":     {"cli": "grok",   "permission": "auto"},
    "remember":   {"cli": "none"},
    "improve":    {"cli": "claude", "permission": "acceptEdits"}
  },
  "gates": ["execute"],
  "timeout_s": 900,
  "harness_dir": ".sag/harness",
  "runs_dir": ".sag/runs",
  "memory_dir": ".sag/memory",
  "library_dir": ".sag/library"
}
```

- `test_cmd` is the repo's **real** test command. It is what proves the test is
  RED before `execute` and green after it.
- `cli` is `claude`, `grok`, `dsh`, or `none`.
- `permission` is passed to `claude` (`acceptEdits` for steps that must write
  files; `plan` is read-only).
- `gates` lists the steps that stop for a human.

---

## Repository layout

```
sag.py                 CLI: setup / check / run / report / demo
orchestrator.py        seven steps, prompts, agent invocation, gates
recursion.py           task-level recursion: propose / probe / compose / reflect
skills/<step>/SKILL.md one role card per step
config.example.json    a complete example configuration
tests/test_core.py     dependency-free tests for scoring and skill loading
```

Run the tests:

```bash
python3 -m unittest discover -s tests -v
```

---

## Design decisions

- **Capacity of an agent = one CLI call per step.** There is no hidden retry
  loop around a model; retries are explicit and logged.
- **The test author and the executor are different models.** Grok writes the
  test, DeepSeek implements it, Claude reviews the diff. Independence is the
  point.
- **The executor never sees the reviewer's verdict.** Grader verdicts stay out
  of the executor's context so a later run cannot learn to game the grader.
- **Ties keep the baseline.** A harness edit must win on evidence to be adopted.
- **No auto-commit.** The pipeline produces artifacts; the human ships them.

## Limitations

- Sequential, one task at a time.
- Adapters only for the headless modes of `claude`, `grok`, and `dsh`.
- A probe re-runs real model calls, so recursion costs money and time. With the
  default assignment, `write-test` (Grok) is the slow step — budget ~15 minutes.
- The library is local to the repo; it is not shared across projects.
- The CLIs load their own plugins and skills unless you isolate them; that is
  convenient, but it makes runs less deterministic.

---

## License

MIT — see [LICENSE](LICENSE).

Credits: the harness model and the two-level recursion are inspired by
[Harness²](https://github.com/google-research/harness2) (Google Research,
Apache-2.0); the agent-team operating principles come from Lauren Tan's talk on
building AI teams. No code from those projects is included here.
