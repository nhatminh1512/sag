#!/usr/bin/env python3
"""Benchmark: a single coding agent vs the sag pipeline on the same tasks.

Each task gets two fresh copies of base/. Arm "single" runs one Claude call that
plans, writes the test, implements, and runs the suite. Arm "sag" runs the five
delivery steps of the pipeline. A separate judge — blind to the arm — reads the
task, the final diff and the test output, then returns a verdict.

A false pass is: the arm claims success (suite green for "single", verify pass
for "sag") while the judge says the task is not actually done or tested.

Usage:
    python3 bench/run.py --tasks 1 --workers 1
    python3 bench/run.py --workers 2
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BASE = ROOT / "base"
TASKS_DIR = ROOT / "tasks"
RUNS = ROOT / "runs"
RESULTS = ROOT / "results"
SAG = ROOT.parent / "sag.py"
SKILLS = ROOT.parent / "skills"

STEPS = "plan,write-test,execute,review,verify"
_lock = threading.Lock()


def sh(cmd: list[str], cwd: Path, timeout: int, input_text: str | None = None) -> tuple[int, str, float]:
    t0 = time.time()
    try:
        p = subprocess.run(cmd, cwd=str(cwd), input=input_text, capture_output=True,
                           text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or ""), time.time() - t0
    except subprocess.TimeoutExpired as exc:
        parts = []
        for chunk in (exc.stdout, exc.stderr):
            if chunk:
                parts.append(chunk.decode("utf-8", "replace") if isinstance(chunk, bytes) else chunk)
        out = "".join(parts)
        return 124, out + f"\n[timeout after {timeout}s]", time.time() - t0
    except OSError as exc:
        return 127, f"{type(exc).__name__}: {exc}", time.time() - t0


def make_repo(task_name: str, arm: str) -> Path:
    dst = RUNS / f"{task_name}-{arm}" / "repo"
    if dst.parent.exists():
        shutil.rmtree(dst.parent)
    dst.parent.mkdir(parents=True)
    shutil.copytree(BASE, dst)
    for cmd in (["git", "init", "-q"], ["git", "add", "-A"],
                ["git", "-c", "user.email=b@b", "-c", "user.name=bench",
                 "commit", "-qm", "base"]):
        sh(cmd, dst, 60)
    return dst


def setup_sag(repo: Path) -> Path:
    sag = repo / ".sag"
    sag.mkdir()
    cfg = {
        "version": 1,
        "repo": str(repo),
        "test_cmd": "python3 run_tests.py",
        "steps": {
            "plan": {"cli": "claude", "permission": "acceptEdits"},
            "write-test": {"cli": "claude", "permission": "acceptEdits"},
            "execute": {"cli": "claude", "permission": "acceptEdits"},
            "review": {"cli": "claude", "permission": "acceptEdits"},
            "verify": {"cli": "claude", "permission": "acceptEdits"},
            "remember": {"cli": "none"},
            "improve": {"cli": "none"},
        },
        "gates": [],
        "timeout_s": 900,
        "harness_dir": ".sag/harness",
        "runs_dir": ".sag/runs",
        "memory_dir": ".sag/memory",
    }
    (sag / "config.json").write_text(json.dumps(cfg, indent=2) + "\n")
    shutil.copytree(SKILLS, sag / "harness" / "skills")
    (sag / "memory").mkdir()
    return sag


def run_single(spec: str, repo: Path) -> dict:
    prompt = f"""You are a coding agent working in this repository.

TASK:
{spec}

Do all of it yourself: plan, write the test, implement, and run the tests.
Add the test to `run_tests.py` and register it in the `if __name__ == "__main__":`
block, following the task's instructions. Run `python3 run_tests.py` until it
prints `ALL OK`. When finished, print DONE.
"""
    rc, out, dt = sh(["claude", "-p", "--permission-mode", "acceptEdits"],
                     repo, 600, prompt)
    trc, tout, _ = sh(["python3", "run_tests.py"], repo, 120)
    return {"claim": trc == 0, "agent_rc": rc, "agent_out": out[-3000:],
            "test_rc": trc, "test_output": tout[-4000:], "seconds": round(dt, 1)}


def run_sag(spec: str, repo: Path) -> dict:
    setup_sag(repo)
    rc, out, dt = sh(["python3", str(SAG), "--steps", STEPS, "--auto", spec],
                     repo, 1800)
    runs = sorted(p for p in (repo / ".sag" / "runs").glob("*") if p.is_dir())
    run_dir = runs[-1] if runs else None
    claim = False
    if run_dir and (run_dir / "verify.json").exists():
        try:
            claim = bool(json.loads((run_dir / "verify.json").read_text()).get("pass"))
        except (json.JSONDecodeError, OSError):
            claim = False
    trc, tout, _ = sh(["python3", "run_tests.py"], repo, 120)
    return {"claim": claim, "agent_rc": rc, "agent_out": out[-3000:],
            "test_rc": trc, "test_output": tout[-4000:], "seconds": round(dt, 1),
            "run_dir": str(run_dir) if run_dir else ""}


def judge(spec: str, repo: Path, test_output: str) -> dict:
    sh(["git", "add", "-A"], repo, 60)
    _, diff, _ = sh(["git", "diff", "--cached"], repo, 60)
    prompt = f"""You are an independent reviewer. You did not write this code.

TASK:
{spec}

DIFF:
{diff[:40000] or "(no changes)"}

TEST OUTPUT:
{test_output[:4000]}

Answer three questions:
1. Does the diff implement every requirement in the task?
2. Does the test output show a test that actually asserts the required behaviour
   (not merely a green suite, and not a test that never runs)?
3. Are there blocking bugs, regressions, or scope violations?

Reply with JSON only, no prose:
{{"implements": true|false, "test_covers": true|false, "blocking_issues": ["..."], "verdict": "pass"|"fail"}}
Use "pass" only when implements and test_covers are both true and there are no
blocking issues.
"""
    rc, out, dt = sh(["claude", "-p", "--permission-mode", "plan"], repo, 300, prompt)
    for cand in reversed(re.findall(r"\{.*?\}", out, re.S)):
        try:
            data = json.loads(cand)
        except json.JSONDecodeError:
            continue
        if "verdict" in data:
            return {"implements": bool(data.get("implements")),
                    "test_covers": bool(data.get("test_covers")),
                    "blocking_issues": data.get("blocking_issues", []),
                    "verdict": str(data.get("verdict", "fail")),
                    "seconds": round(dt, 1)}
    return {"implements": False, "test_covers": False,
            "blocking_issues": ["judge output was not parseable"],
            "verdict": "fail", "seconds": round(dt, 1), "raw": out[-1000:]}


def run_one(task_path: Path, arm: str) -> dict:
    spec = task_path.read_text()
    name = task_path.stem
    repo = make_repo(name, arm)
    res = run_single(spec, repo) if arm == "single" else run_sag(spec, repo)
    verdict = judge(spec, repo, res["test_output"])
    markers = re.findall(r'print\("ok ([a-z0-9_]+)"\)', spec)
    wired = all(f"ok {m}" in res["test_output"] for m in markers) if markers else None
    false_pass = bool(res["claim"]) and (verdict["verdict"] != "pass" or wired is False)
    rec = {"task": name, "arm": arm, "claim": res["claim"], "wired": wired,
           "false_pass": false_pass, "judge": verdict,
           "agent_rc": res["agent_rc"], "test_rc": res["test_rc"],
           "seconds": res["seconds"]}
    with _lock:
        RESULTS.mkdir(exist_ok=True)
        with (RESULTS / "runs.jsonl").open("a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"  {name:24} {arm:6} claim={str(res['claim']):5} "
              f"judge={verdict['verdict']:4} false_pass={false_pass}", flush=True)
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", help="comma list of task numbers, e.g. 1,3,5")
    ap.add_argument("--arms", default="single,sag")
    ap.add_argument("--workers", type=int, default=2)
    args = ap.parse_args()

    tasks = sorted(TASKS_DIR.glob("*.md"))
    if args.tasks:
        wanted = {t.strip().zfill(2) for t in args.tasks.split(",")}
        tasks = [t for t in tasks if t.name[:2] in wanted]
    arms = [a.strip() for a in args.arms.split(",") if a.strip()]

    RUNS.mkdir(exist_ok=True)
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "runs.jsonl").unlink(missing_ok=True)

    jobs = [(t, a) for t in tasks for a in arms]
    print(f"{len(jobs)} jobs · tasks={len(tasks)} arms={arms} workers={args.workers}")
    recs = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(run_one, t, a): (t, a) for t, a in jobs}
        for fut in as_completed(futs):
            try:
                recs.append(fut.result())
            except Exception as exc:  # a crashed job is a result too
                t, a = futs[fut]
                rec = {"task": t.stem, "arm": a, "claim": False, "false_pass": False,
                       "judge": {"verdict": "error", "blocking_issues": [str(exc)]}}
                recs.append(rec)
                print(f"  {t.stem} {a} ERROR {exc}")

    summary = {}
    for arm in arms:
        rows = [r for r in recs if r["arm"] == arm]
        claims = sum(1 for r in rows if r["claim"])
        fps = sum(1 for r in rows if r["false_pass"])
        summary[arm] = {"n": len(rows), "claims": claims, "false_passes": fps,
                        "unwired_tests": sum(1 for r in rows if r.get("wired") is False),
                        "false_pass_rate": round(fps / claims, 3) if claims else None}
    (RESULTS / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print("\n" + json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
