#!/usr/bin/env python3
"""factory — plan → write-test → execute → review → verify → remember → improve.

Architecture follows Lauren Tan / the Grok team's "AI team" model:

  * one Chief-of-Staff process (this file) that ONLY routes work, never codes
  * every step is a named agent with its own role and its own memory files
  * a fixed SOP pipeline, with file handoff between steps (no prompt stuffing)
  * self-check before handoff (plan lists files+criteria, tests must run red,
    executor must run the suite, verifier grades against the rubric)
  * a lead that delegates, and a human gate before irreversible actions
  * gradual autonomy: run step by step, keep the transcripts, improve the SOP

CLI one-shot modes used:
  claude -p --permission-mode <mode>      (prompt on stdin)
  grok   -p "<prompt>" --always-approve
  dsh    headless -                       (prompt on stdin)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import clis

ROOT = Path(__file__).resolve().parent
STEPS = ["plan", "write-test", "execute", "review", "verify", "remember", "improve"]
STATE_DIR = ROOT  # overridden by run_pipeline (per-project .sag dir)
HARNESS_DIR = ROOT  # overridden by cfg["harness_dir"] (per-project harness)
LAST_RUN_DIR: Path | None = None  # set by run_pipeline, read by sag/recursion


# --------------------------------------------------------------------------- utils
def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_config(path: str | Path | None = None) -> dict:
    p = Path(path).expanduser() if path else (ROOT / "config.json")
    return json.loads(p.read_text())


def load_env() -> dict:
    """Merge ~/.hermes/.env into a copy of the environment (no secrets printed)."""
    env = dict(os.environ)
    p = Path.home() / ".hermes" / ".env"
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return env


def run(cmd: list[str], cwd: Path, timeout: int, env: dict, stdin_text: str | None = None):
    t0 = time.time()
    try:
        p = subprocess.run(
            cmd, cwd=str(cwd), env=env, input=stdin_text,
            capture_output=True, text=True, timeout=timeout,
        )
        return p.returncode, (p.stdout or "") + (p.stderr or ""), time.time() - t0
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or "") + (e.stderr or "")
        return 124, out + f"\n[timeout after {timeout}s]", time.time() - t0
    except FileNotFoundError as e:
        return 127, f"[missing CLI] {e}", time.time() - t0


def run_agent(step: str, cfg: dict, prompt: str, repo: Path, run_dir: Path) -> tuple[int, str, float]:
    spec = cfg["steps"][step]
    cli = spec.get("cli", "none")
    if cli == "none":
        return 0, "", 0.0
    timeout = int(cfg.get("timeout_s", 900))
    env = load_env()
    (run_dir / "prompts").mkdir(exist_ok=True)
    (run_dir / "prompts" / f"{step}.md").write_text(prompt)
    try:
        argv, stdin_text = clis.build(spec, prompt, spec.get("model"))
    except ValueError as exc:
        return 2, f"[cli error] {exc}", 0.0
    (run_dir / "prompts" / f"{step}.argv.json").write_text(json.dumps(argv, indent=2) + "\n")
    return run(argv, repo, timeout, env, stdin_text=stdin_text)


def git_diff(repo: Path) -> str:
    rc, out, _ = run(["git", "diff", "--binary", "HEAD"], repo, 60, load_env())
    # include untracked files so a new test file shows up
    rc2, out2, _ = run(["git", "status", "--porcelain"], repo, 60, load_env())
    return (out or "") + "\n# git status --porcelain\n" + (out2 or "")


# --------------------------------------------------------------------------- prompts
def skill(step: str) -> str:
    """Load the step's SKILL.md (frontmatter stripped) — the agent's role card."""
    p = HARNESS_DIR / "skills" / step / "SKILL.md"
    if not p.exists():
        p = ROOT / "skills" / step / "SKILL.md"
    if not p.exists():
        return f"You are the {step.upper()} agent."
    t = p.read_text()
    return re.sub(r"^---\n.*?\n---\n", "", t, count=1, flags=re.S).strip()


def prompt_plan(task: str, repo: Path) -> str:
    return f"{skill('plan')}\n\nRepository: {repo}\n\nTASK:\n{task}\n"


def prompt_write_test(task: str, plan_md: str, test_cmd: str) -> str:
    return (f"{skill('write-test')}\n\nTASK:\n{task}\n\n"
            f"THE PLAN (authoritative):\n{plan_md}\n\n"
            f"REPO TEST COMMAND: {test_cmd}\n")


def prompt_execute(task: str, test_cmd: str) -> str:
    return (f"{skill('execute')}\n\nTASK:\n{task}\n\n"
            f"REPO TEST COMMAND: {test_cmd}\n")


def prompt_review(task: str, diff: str, plan_md: str) -> str:
    return (f"{skill('review')}\n\nTASK:\n{task}\n\nPLAN:\n{plan_md}\n\n"
            f"DIFF + STATUS:\n{diff[:60000]}\n")


def prompt_verify(task: str, plan_md: str, test_output: str, review_md: str) -> str:
    return (f"{skill('verify')}\n\nTASK:\n{task}\n\nPLAN:\n{plan_md}\n\n"
            f"TEST OUTPUT:\n{test_output[:40000]}\n\n"
            f"REVIEW:\n{review_md[:20000]}\n")


def prompt_improve(task: str, run_dir: Path) -> str:
    arts = {}
    for name in ("plan.md", "test-plan.md", "execution.md", "review.md", "verify.md"):
        p = run_dir / name
        if p.exists():
            arts[name] = p.read_text()[:20000]
    body = "\n\n".join(f"=== {k} ===\n{v}" for k, v in arts.items())
    return f"{skill('improve')}\n\nTASK:\n{task}\n\nARTIFACTS:\n{body}\n"


# --------------------------------------------------------------------------- steps
def do_plan(cfg, task, repo, run_dir, auto):
    rc, out, dt = run_agent("plan", cfg, prompt_plan(task, repo), repo, run_dir)
    log(run_dir, "plan", rc, dt, out)
    plan = repo / "plan.md"
    if not plan.exists():
        return False, "planner did not write plan.md"
    txt = plan.read_text()
    missing = [s for s in ("## Goal", "## Steps", "## Files") if s not in txt]
    if "## Feature criteria" not in txt and "## Acceptance Criteria" not in txt:
        missing.append("## Feature criteria")
    if missing:
        return False, f"plan.md missing sections: {missing}"
    (run_dir / "plan.md").write_text(txt)
    return True, out


def do_write_test(cfg, task, repo, run_dir, auto):
    plan_md = (repo / "plan.md").read_text() if (repo / "plan.md").exists() else ""
    test_cmd = cfg.get("test_cmd", "python3 -m pytest -q")
    rc, out, dt = run_agent("write-test", cfg,
                            prompt_write_test(task, plan_md, test_cmd), repo, run_dir)
    log(run_dir, "write-test", rc, dt, out)
    status = subprocess.run(["git", "status", "--porcelain"], cwd=str(repo),
                            capture_output=True, text=True, env=load_env()).stdout
    if not status.strip():
        return False, "test author made no file changes"
    tp = repo / "test-plan.md"
    (run_dir / "test-plan.md").write_text(tp.read_text() if tp.exists() else out[-8000:])
    # Self-check (principle 4): the new tests must be RED before implementation.
    trc, tout, _ = run(["bash", "-lc", test_cmd], repo, 600, load_env())
    (run_dir / "test-output-red.txt").write_text(tout)
    if trc == 0:
        return False, (f"tests PASS before execute — the new test is not wired into "
                       f"`{test_cmd}`, so it would never run. The test author must follow plan.md.")
    return True, out


def do_execute(cfg, task, repo, run_dir, auto):
    test_cmd = cfg.get("test_cmd", "python3 -m pytest -q")
    rc, out, dt = run_agent("execute", cfg, prompt_execute(task, test_cmd), repo, run_dir)
    log(run_dir, "execute", rc, dt, out)
    diff = git_diff(repo)
    (run_dir / "diff.patch").write_text(diff)
    if (repo / "execution.md").exists():
        (run_dir / "execution.md").write_text((repo / "execution.md").read_text())
    if not diff.strip():
        return False, "executor produced no diff"
    return True, out


def do_review(cfg, task, repo, run_dir, auto):
    plan_md = (repo / "plan.md").read_text() if (repo / "plan.md").exists() else ""
    diff = (run_dir / "diff.patch").read_text() if (run_dir / "diff.patch").exists() else git_diff(repo)
    rc, out, dt = run_agent("review", cfg, prompt_review(task, diff, plan_md), repo, run_dir)
    log(run_dir, "review", rc, dt, out)
    rv = repo / "review.md"
    if not rv.exists():
        return False, "reviewer did not write review.md"
    txt = rv.read_text()
    (run_dir / "review.md").write_text(txt)
    upper = txt.upper()
    # "REQUEST_CHANGES" wins even if the prose also says "I would approve …"
    if "REQUEST_CHANGES" in upper or "REQUEST CHANGES" in upper:
        return False, "review verdict: REQUEST_CHANGES"
    return bool(re.search(r"##\s*VERDICT\s*\n+\s*APPROVE", upper)), out


def do_verify(cfg, task, repo, run_dir, auto):
    test_cmd = cfg.get("test_cmd", "python3 -m pytest -q")
    rc, test_out, dt = run(["bash", "-lc", test_cmd], repo, 600, load_env())
    (run_dir / "test-output.txt").write_text(test_out)
    plan_md = (repo / "plan.md").read_text() if (repo / "plan.md").exists() else ""
    review_md = (run_dir / "review.md").read_text() if (run_dir / "review.md").exists() else ""
    rc2, out, dt2 = run_agent("verify", cfg,
                              prompt_verify(task, plan_md, test_out, review_md), repo, run_dir)
    log(run_dir, "verify", rc2, dt2, out)
    vj = repo / "verify.json"
    if not vj.exists():
        return False, "verifier did not write verify.json"
    try:
        data = json.loads(vj.read_text())
    except Exception as e:
        return False, f"verify.json invalid: {e}"
    (run_dir / "verify.json").write_text(json.dumps(data, indent=2, ensure_ascii=False))
    if (repo / "verify.md").exists():
        (run_dir / "verify.md").write_text((repo / "verify.md").read_text())
    return bool(data.get("pass")), out


def do_remember(cfg, task, repo, run_dir, auto):
    mem = STATE_DIR / "memory"
    mem.mkdir(parents=True, exist_ok=True)
    stamp = now()
    plan = (repo / "plan.md").read_text() if (repo / "plan.md").exists() else ""
    review = (run_dir / "review.md").read_text() if (run_dir / "review.md").exists() else ""
    verify = (run_dir / "verify.json").read_text() if (run_dir / "verify.json").exists() else ""
    with (mem / "decisions.md").open("a") as f:
        f.write(f"\n## {stamp} — {task[:80]}\n{plan[:2000]}\n")
    with (mem / "lessons.md").open("a") as f:
        f.write(f"\n## {stamp} — {task[:80]}\nReview: {review[:1200]}\nVerify: {verify[:800]}\n")
    (mem / "context.md").write_text(
        f"# Project context\nRepo: {repo}\nLast run: {stamp}\nTask: {task}\n"
    )
    return True, "memory written"


def do_improve(cfg, task, repo, run_dir, auto):
    rc, out, dt = run_agent("improve", cfg, prompt_improve(task, run_dir), repo, run_dir)
    log(run_dir, "improve", rc, dt, out)
    p = repo / "improve.md"
    if p.exists():
        (run_dir / "improve.md").write_text(p.read_text())
        mem = STATE_DIR / "memory"
        mem.mkdir(parents=True, exist_ok=True)
        with (mem / "improvements.md").open("a") as f:
            f.write(f"\n## {now()} — {task[:80]}\n{p.read_text()[:3000]}\n")
        return True, out
    return False, "meta-agent did not write improve.md"


IMPL = {
    "plan": do_plan,
    "write-test": do_write_test,
    "execute": do_execute,
    "review": do_review,
    "verify": do_verify,
    "remember": do_remember,
    "improve": do_improve,
}


def log(run_dir: Path, step: str, rc: int, dt: float, out: str):
    rec = {"ts": now(), "step": step, "rc": rc, "seconds": round(dt, 1),
           "tail": out[-3000:]}
    with (run_dir / "log.jsonl").open("a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# --------------------------------------------------------------------------- main
def run_pipeline(cfg, task, repo, state_dir, steps, auto, dry_run=False, run_id=None) -> int:
    """Run the pipeline. Used by both `python3 orchestrator.py` and the `sag` CLI."""
    global STATE_DIR, HARNESS_DIR, LAST_RUN_DIR
    STATE_DIR = Path(state_dir).expanduser().resolve()
    hd = cfg.get("harness_dir")
    if hd:
        HARNESS_DIR = (Path(hd) if Path(hd).is_absolute() else repo / hd).resolve()
    else:
        HARNESS_DIR = ROOT
    runs_dir = STATE_DIR / "runs"
    if run_id:
        run_dir = runs_dir / run_id
    else:
        base = datetime.now().strftime("%Y%m%d-%H%M%S")
        run_dir = runs_dir / base
        n = 2
        while run_dir.exists():
            run_dir = runs_dir / f"{base}-{n}"
            n += 1
    run_dir.mkdir(parents=True, exist_ok=True)
    LAST_RUN_DIR = run_dir
    # snapshot the harness this run uses — evidence for task-level recursion
    if (HARNESS_DIR / "skills").exists():
        shutil.copytree(HARNESS_DIR / "skills", run_dir / "harness" / "skills",
                        dirs_exist_ok=True)
    (run_dir / "task.txt").write_text(task)

    print(f"factory run {run_dir.name} · repo {repo}")
    print(f"steps: {' → '.join(steps)}\n")

    for step in steps:
        print(f"── {step} " + "─" * max(0, 50 - len(step)))
        if step in cfg.get("gates", []) and not auto and not dry_run:
            try:
                ans = input(f"gate: run '{step}'? [y/N] ").strip().lower()
            except EOFError:
                print("\n(no TTY for the human gate — pass --auto to continue) — stopping")
                return 0
            if ans != "y":
                print("stopped at gate")
                return 0
        if dry_run:
            print("(dry-run) would run", step)
            continue
        ok, out = IMPL[step](cfg, task, repo, run_dir, auto)
        print(("✓" if ok else "✗"), step, "done" if ok else f"failed: {out[:200]}")
        if not ok:
            print(f"\nRun dir: {run_dir}")
            return 1

    print(f"\nAll steps done. Artifacts: {run_dir}")
    print("Human sign-off before `git commit` / merge — review plan.md, review.md, verify.json.")
    return 0


def main():
    ap = argparse.ArgumentParser(description="plan→test→execute→review→verify→remember→improve")
    ap.add_argument("task", nargs="?", help="what to build")
    ap.add_argument("--repo", help="override repo path")
    ap.add_argument("--config", help="config.json path (default: factory/config.json)")
    ap.add_argument("--state-dir", help="where runs/ and memory/ live (default: factory/)")
    ap.add_argument("--auto", action="store_true", help="skip human gates")
    ap.add_argument("--steps", help="comma list, e.g. plan,write-test")
    ap.add_argument("--run-id", help="resume an existing run")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cfg = load_config(args.config)
    repo = Path(args.repo or cfg["repo"]).expanduser().resolve()
    steps = [s.strip() for s in args.steps.split(",")] if args.steps else STEPS
    state_dir = Path(args.state_dir) if args.state_dir else ROOT
    task = args.task
    if not task and args.run_id:
        tf = state_dir / "runs" / args.run_id / "task.txt"
        task = tf.read_text() if tf.exists() else ""
    if not task:
        sys.exit("need a task (or resume with --run-id on a run that has task.txt)")
    return run_pipeline(cfg, task, repo, state_dir, steps, args.auto,
                        args.dry_run, args.run_id)


if __name__ == "__main__":
    sys.exit(main())
