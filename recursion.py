#!/usr/bin/env python3
"""Task-level recursion for `sag`: Propose → Probe → Compose, then reflect.

Borrowed from Harness² (google-research/harness2):
  * the proposer emits an edit to the harness (omitted-is-inherited),
  * the probe executes the same task under the candidate harness,
  * the composer picks between baseline and candidates from behaviour, not claims,
  * reflection stores the adopted harness + the lesson in a per-domain library.

A probe re-runs only the steps affected by the edit (from the earliest affected
step through `verify`), so a verify-only edit costs one judge call, not a full run.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import orchestrator as orch

PROBEABLE = ["plan", "write-test", "execute", "review", "verify"]
SKIP_DIRS = {".venv", ".git", "node_modules", "__pycache__", ".mypy_cache", ".pytest_cache"}


# --------------------------------------------------------------------------- utils
def _now() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _slug(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9._-]+", "-", s.strip()).strip("-").lower()
    return (s[:60] or "task")


def _copy(src: Path, dst: Path, ignore_backups: bool = False) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    if ignore_backups:
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns("backups"))
    else:
        shutil.copytree(src, dst)


def _evidence(run_dir: Path) -> str:
    """The run's artifacts, as a short pointer + the key tails (evidence on disk)."""
    parts = [f"Run directory: {run_dir}", "Read the files there before deciding.", ""]
    for name, tail in (("plan.md", 4000), ("test-plan.md", 3000),
                       ("review.md", 4000), ("verify.json", 3000),
                       ("test-output.txt", 3000), ("improve.md", 4000)):
        p = run_dir / name
        if p.exists():
            parts += [f"=== {name} ===", p.read_text()[-tail:], ""]
    return "\n".join(parts)


def _score(run_dir: Path | None) -> dict:
    s = {"pass": False, "approve": False, "test_ok": False, "criteria": 0, "score": 0.0}
    if not run_dir or not Path(run_dir).exists():
        return s
    v = Path(run_dir) / "verify.json"
    if v.exists():
        try:
            d = json.loads(v.read_text())
            s["pass"] = bool(d.get("pass"))
            s["criteria"] = sum(1 for c in d.get("criteria", []) if c.get("met"))
        except (json.JSONDecodeError, OSError):
            pass
    r = Path(run_dir) / "review.md"
    if r.exists():
        up = r.read_text().upper()
        s["approve"] = "APPROVE" in up and "REQUEST_CHANGES" not in up
    t = Path(run_dir) / "test-output.txt"
    if t.exists():
        body = t.read_text().lower()
        s["test_ok"] = "all ok" in body or "passed" in body
    s["consistent"] = s["pass"] == (s["approve"] and s["test_ok"])
    s["score"] = round(s["test_ok"] * 3 + s["approve"] * 2 + s["consistent"] * 3
                       + min(s["criteria"], 5) * 0.1, 2)
    return s


def _ignore(dirpath: str, names: list[str]) -> list[str]:
    out = [n for n in names if n in SKIP_DIRS]
    if Path(dirpath).name == ".sag":
        out += [n for n in names if n in ("runs", "memory", "library")]
    return out


# --------------------------------------------------------------------------- propose
def propose(cfg: dict, repo: Path, state_dir: Path, run_dir: Path,
            label: str, focus: str) -> dict:
    pdir = run_dir / "recursion" / label
    pdir.mkdir(parents=True, exist_ok=True)
    # the baseline run's own harness is the thing being edited (not today's .sag/)
    base_harness = run_dir / "harness"
    if not (base_harness / "skills").exists():
        base_harness = state_dir / "harness"
    _copy(base_harness, pdir / "harness")

    prompt = f"""{orch.skill('improve')}

# TASK-LEVEL PROBE — {focus}

The current harness is in `./harness` (skills under `./harness/skills/`).

EVIDENCE FROM THE RUN:
{_evidence(run_dir)}

Priority rule: if the evidence shows `verify.json` contradicting the independent
review verdict (e.g. verify says pass while review says REQUEST_CHANGES), fix
the `verify` skill first — a grader that disagrees with another grader is the
most expensive failure here.

Edit AT MOST ONE skill file under `./harness/skills/` to fix the biggest failure
the evidence shows. Contract: omitted-is-inherited — change only what the
evidence justifies, keep the file's frontmatter valid, and do not touch code.

Then write `proposal.md` with EXACTLY:
## Change
(file and the exact rule you changed)
## Evidence
(quote the run moment that justifies it — do not speculate)
## Hypothesis
(what behaviour should change on the next execution)
## Affected steps
(comma list from: plan, write-test, execute, review, verify)

Do not edit anything outside `./harness/` and `./proposal.md`.
"""
    cfg2 = dict(cfg)
    cfg2["steps"] = dict(cfg.get("steps", {}))
    cfg2["steps"].setdefault("propose", cfg2["steps"].get("improve", {"cli": "claude", "permission": "acceptEdits"}))
    rc, out, dt = orch.run_agent("propose", cfg2, prompt, pdir, pdir)
    orch.log(run_dir, f"propose-{label}", rc, dt, out)

    prop = pdir / "proposal.md"
    if not prop.exists():
        return {"label": label, "dir": pdir, "ok": False, "error": "proposer wrote no proposal.md"}
    txt = prop.read_text()
    m = re.search(r"##\s*Affected steps\s*\n+(.+)", txt, re.I)
    affected = [s.strip() for s in re.split(r"[,\s]+", m.group(1)) if s.strip()] if m else []
    affected = [s for s in affected if s in PROBEABLE]
    changed = _changed(pdir / "harness", base_harness)
    return {"label": label, "dir": pdir, "ok": bool(changed), "affected": affected,
            "changed": changed, "proposal": txt}


def _changed(a: Path, b: Path) -> list[str]:
    out = []
    fa = {p.relative_to(a): p.read_text(errors="replace") for p in a.rglob("*") if p.is_file()}
    fb = {p.relative_to(b): p.read_text(errors="replace") for p in b.rglob("*") if p.is_file()}
    for rel in sorted(set(fa) | set(fb)):
        if fa.get(rel) != fb.get(rel):
            out.append(str(rel))
    return out


# --------------------------------------------------------------------------- probe
def expand_steps(affected: list[str]) -> list[str]:
    """Re-run from the earliest affected step through verify; verify needs a review."""
    if not affected:
        affected = ["verify"]
    i = min(PROBEABLE.index(s) for s in affected)
    steps = PROBEABLE[i:]
    if "verify" in steps and "review" not in steps:
        steps = ["review"] + steps
    return steps


def _prepare_probe_repo(repo: Path, probe_repo: Path, steps: list[str]) -> None:
    """A verify-only probe runs on the current tree; a behavioural probe starts at HEAD."""
    if probe_repo.exists():
        shutil.rmtree(probe_repo, ignore_errors=True)
        subprocess.run(["git", "worktree", "prune"], cwd=repo, capture_output=True)

    made = False
    behavioral = any(s in steps for s in ("write-test", "execute"))
    if behavioral:
        r = subprocess.run(["git", "worktree", "add", "--detach", str(probe_repo), "HEAD"],
                           cwd=repo, capture_output=True, text=True)
        made = r.returncode == 0
    if not made:
        shutil.copytree(repo, probe_repo, ignore=_ignore)

    venv = repo / ".venv"
    if venv.exists() and not (probe_repo / ".venv").exists():
        (probe_repo / ".venv").symlink_to(venv, target_is_directory=True)

    if not (probe_repo / ".git").exists():
        for cmd in (["git", "init", "-q"], ["git", "add", "-A"],
                    ["git", "-c", "user.email=a@b", "-c", "user.name=sag",
                     "commit", "-qm", "probe baseline"]):
            subprocess.run(cmd, cwd=probe_repo, capture_output=True)


def probe(cfg: dict, task: str, repo: Path, state_dir: Path, run_dir: Path,
          prop: dict, steps: list[str]) -> dict:
    pdir = prop["dir"]
    probe_repo = pdir / "repo"
    _prepare_probe_repo(repo, probe_repo, steps)

    # the candidate harness
    _copy(pdir / "harness", probe_repo / ".sag" / "harness")

    # carry generated artifacts the probe will not regenerate
    if (run_dir / "plan.md").exists():
        (probe_repo / "plan.md").write_text((run_dir / "plan.md").read_text())

    # seed the probe run dir: a verify-only probe reuses the baseline review/diff
    run_id = f"probe-{prop['label']}"
    prun = probe_repo / ".sag" / "runs" / run_id
    prun.mkdir(parents=True, exist_ok=True)
    for f in ("review.md", "diff.patch", "test-plan.md"):
        src = run_dir / f
        if src.exists():
            (prun / f).write_text(src.read_text())

    rc = 0
    orch.LAST_RUN_DIR = prun
    orch.HARNESS_DIR = probe_repo / ".sag" / "harness"
    orch.STATE_DIR = probe_repo / ".sag"
    (prun / "task.txt").write_text(task)
    # Run the probe steps even when an intermediate step requests changes:
    # the point is to see whether verify catches what review caught.
    for step in steps:
        try:
            ok, out = orch.IMPL[step](cfg, task, probe_repo, prun, True)
        except Exception as exc:  # a broken probe is evidence, not a crash
            ok, out = False, f"{type(exc).__name__}: {exc}"
        print(("✓" if ok else "✗"), step, "done" if ok else f"failed: {out[:160]}")
        if not ok:
            rc = 1
    sc = _score(prun)
    (pdir / "score.json").write_text(json.dumps(
        {"label": prop["label"], "steps": steps, "rc": rc, **sc}, indent=2))
    return {"label": prop["label"], "run_dir": prun, "score": sc, "rc": rc,
            "harness": pdir / "harness", "dir": pdir,
            "proposal": prop.get("proposal", "")}


# --------------------------------------------------------------------------- compose
def compose(results: list[dict]) -> dict:
    """Highest behaviour score wins; ties keep the earlier (baseline-first) entry."""
    best = results[0]
    for r in results[1:]:
        if r["score"]["score"] > best["score"]["score"]:
            best = r
    return best


def adopt(state_dir: Path, winner: dict) -> Path:
    """Copy the winning harness over the project's, keeping a backup."""
    src = winner.get("harness") or winner.get("dir", Path()) / "harness"
    dst = state_dir / "harness"
    if not Path(src).exists():
        return dst
    backup = state_dir / "harness" / "backups" / _now()
    backup.parent.mkdir(parents=True, exist_ok=True)
    if (dst / "skills").exists():
        shutil.copytree(dst / "skills", backup, dirs_exist_ok=True)
    shutil.copytree(Path(src) / "skills", dst / "skills", dirs_exist_ok=True)
    return dst


def reflect(state_dir: Path, task: str, baseline: dict, winner: dict,
            results: list[dict], cfg: dict) -> Path:
    domain = cfg.get("domain") or "default"
    d = state_dir / "library" / _slug(domain) / _slug(task)
    d.mkdir(parents=True, exist_ok=True)
    _copy(state_dir / "harness", d / "harness", ignore_backups=True)

    def fmt(s: dict) -> str:
        return (f"pass={s['pass']} approve={s['approve']} tests={s['test_ok']} "
                f"consistent={s.get('consistent', False)}")

    change = ""
    m = re.search(r"##\s*Change\s*\n+(.+)", winner.get("proposal", "") or "", re.I)
    if m:
        change = m.group(1).strip()[:400]
    lines = [
        f"# {task}", "",
        f"- run: {_now()}",
        f"- baseline: {baseline['score']['score']} ({fmt(baseline['score'])})",
        "",
        "## Candidates", "",
    ]
    for r in results[1:]:
        lines.append(f"- **{r['label']}**: {r['score']['score']} ({fmt(r['score'])})")
    lines += [
        "", f"## Adopted: {winner['label']}", "",
        "## Transferable lesson", "",
        f"- **cue**: domain `{domain}`, when the baseline shows {_diagnosis(baseline)}",
        f"- **change**: {change or _lesson(winner, baseline)}",
        f"- **evidence**: score {winner['score']['score']} vs {baseline['score']['score']}",
    ]
    (d / "EXPERIENCE.md").write_text("\n".join(lines) + "\n")
    _rebuild_index(state_dir / "library" / _slug(domain), domain)
    return d


def _diagnosis(b: dict) -> str:
    s = b["score"]
    if not s["pass"]:
        return "a failing verify"
    if not s["approve"]:
        return "a review that requested changes"
    if not s["test_ok"]:
        return "a red test suite"
    return "no obvious failure"


def _lesson(w: dict, b: dict) -> str:
    if w["label"] == "base":
        return "no candidate beat the current harness; keep it and change nothing without new evidence"
    return f"{w['label']} scored {w['score']['score']} vs {b['score']['score']}; its edit is the one that paid off"


def _rebuild_index(domain_dir: Path, domain: str) -> None:
    rows = [f"# Library — {domain}", "",
            "Full adopted harness + the evidence-backed lesson for each task.", ""]
    for e in sorted(p for p in domain_dir.iterdir() if p.is_dir()):
        rows.append(f"- [{e.name}]({e.name}/EXPERIENCE.md)")
    (domain_dir / "INDEX.md").write_text("\n".join(rows) + "\n")


# --------------------------------------------------------------------------- run
def run_with_recursion(cfg: dict, task: str, repo: Path, state_dir: Path,
                       k: int, mode: str, probe_steps: list[str] | None,
                       full_probe: bool = False,
                       baseline_run: str | None = None) -> int:
    print(f"recursion: k={k} mode={mode}")
    orch.HARNESS_DIR = state_dir / "harness"
    orch.STATE_DIR = state_dir
    if baseline_run:
        base_run = Path(baseline_run).expanduser().resolve()
        if not (base_run / "task.txt").exists():
            print(f"not a run directory: {base_run}")
            return 1
        if not task:
            task = (base_run / "task.txt").read_text().strip()
        baseline = {"label": "base", "run_dir": base_run, "score": _score(base_run), "harness": None}
        results = [baseline]
        print(f"baseline: {base_run.name} (score {baseline['score']['score']})")
    else:
        rc = orch.run_pipeline(cfg, task, repo, state_dir, orch.STEPS, auto=True)
        base_run = orch.LAST_RUN_DIR
        baseline = {"label": "base", "run_dir": base_run, "score": _score(base_run), "harness": None}
        results = [baseline]
        if rc != 0:
            print("baseline run failed — recursion needs a completed baseline")
            return rc

    rounds = 1 if mode == "sequential" else max(1, k - 1)
    for i in range(1, rounds + 1):
        focus = "invariant — fix the harness rule, not the task facts" if i % 2 else \
                f"domain-specific — guidance for {repo.name}"
        print(f"\n── propose {i} ({focus}) " + "─" * 20)
        prop = propose(cfg, repo, state_dir, base_run, f"p{i}", focus)
        if not prop["ok"]:
            print(f"✗ proposal rejected: {prop.get('error') or 'no skill changed'}")
            continue
        steps = probe_steps or (PROBEABLE if full_probe else expand_steps(prop["affected"]))
        print(f"  changed: {', '.join(prop['changed'])}")
        print(f"  probing: {', '.join(steps)}")
        pr = probe(cfg, task, repo, state_dir, base_run, prop, steps)
        results.append(pr)
        print(f"  score {pr['score']['score']} (pass={pr['score']['pass']} "
              f"approve={pr['score']['approve']} tests={pr['score']['test_ok']})")
        if mode == "sequential" and pr["score"]["score"] > baseline["score"]["score"]:
            adopt(state_dir, pr)
            baseline = pr

    winner = compose(results)
    print(f"\ncompose: winner = {winner['label']} "
          f"(score {winner['score']['score']} vs base {baseline['score']['score']})")
    if winner["label"] != "base":
        adopt(state_dir, winner)
        print("adopted the winning harness into .sag/harness")
    exp = reflect(state_dir, task, baseline, winner, results, cfg)
    print(f"library: {exp}")
    return 0
