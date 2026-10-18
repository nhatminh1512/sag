#!/usr/bin/env python3
"""sag — setup once per repo, then `cd <repo> && sag` to run the agent pipeline.

Subcommands:
  sag setup     interactive setup (detects CLIs, test command, writes .sag/)
  sag check     preflight: CLIs, config, skills, guardrails
  sag report    summarize the latest (or a given) run
  sag demo      dry-run the pipeline with a sample task (no model calls)
  sag           run the pipeline (prompts for a task if none given)
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import orchestrator as orch  # noqa: E402

SAG = ".sag"
STEPS = orch.STEPS

# default per-step CLI (the "per-CLI setup")
DEFAULTS = {
    "plan":       {"cli": "claude", "permission": "acceptEdits"},
    "write-test": {"cli": "grok",   "permission": "auto"},
    "execute":    {"cli": "dsh",    "permission": "auto", "model": "deepseek-flash"},
    "review":     {"cli": "claude", "permission": "acceptEdits"},
    "verify":     {"cli": "grok",   "permission": "auto"},
    "remember":   {"cli": "none"},
    "improve":    {"cli": "claude", "permission": "acceptEdits"},
}
CLIS = ("claude", "grok", "dsh")

GUARDRAILS = {
    "max_skill_chars": 6000,
    "test_must_be_red": True,
    "executor_sees_review": False,
    "commit_requires_human": True,
}


# --------------------------------------------------------------------------- helpers
def run(cmd: list[str], cwd: Path | None = None) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=30)
        return p.returncode, (p.stdout + p.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, f"{type(exc).__name__}: {exc}"


def git_root(start: Path) -> Path | None:
    rc, out = run(["git", "rev-parse", "--show-toplevel"], cwd=start)
    return Path(out).resolve() if rc == 0 and out else None


def find_project(start: Path) -> tuple[Path, Path] | None:
    """Walk up from cwd to the nearest .sag/config.json. Returns (repo, config_path)."""
    for d in [start, *start.parents]:
        c = d / SAG / "config.json"
        if c.exists():
            return d, c
    return None


def detect_clis() -> dict[str, str]:
    return {name: (shutil.which(name) or "") for name in CLIS}


def pick(cli: str, avail: dict[str, str]) -> str:
    if avail.get(cli):
        return cli
    for alt in CLIS:
        if avail.get(alt):
            return alt
    return "none"


def detect_test_cmd(repo: Path) -> str:
    tr = repo / "test_regressions.py"
    if tr.exists():
        py = ".venv/bin/python" if (repo / ".venv/bin/python").exists() else "python3"
        return f"{py} test_regressions.py"
    pkg = repo / "package.json"
    if pkg.exists():
        try:
            if "test" in json.loads(pkg.read_text()).get("scripts", {}):
                return "npm test"
        except (json.JSONDecodeError, OSError):
            pass
    for f in ("pytest.ini", "pyproject.toml", "setup.cfg", "tox.ini"):
        p = repo / f
        if p.exists():
            try:
                if "pytest" in p.read_text(errors="ignore"):
                    return "python3 -m pytest -q"
            except OSError:
                pass
    if (repo / "tests").is_dir():
        return "python3 -m pytest -q"
    return "python3 -m pytest -q"


def ask(prompt: str, default: str, choices: list[str] | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    if choices:
        suffix += f" ({'/'.join(choices)})"
    try:
        v = input(f"{prompt}{suffix}: ").strip()
    except EOFError:
        return default
    return v or default


def load_project() -> tuple[Path, dict]:
    found = find_project(Path.cwd())
    if not found:
        sys.exit("no .sag/config.json here — run `sag setup` in this repo first")
    repo, cfg_path = found
    return repo, json.loads(cfg_path.read_text())


def banner() -> str:
    return "sag — plan → test → execute → review → verify → remember → improve"


# --------------------------------------------------------------------------- setup
def cmd_setup(args) -> int:
    repo = git_root(Path.cwd()) or Path.cwd()
    sag = repo / SAG
    print(banner())
    print(f"repo: {repo}")
    print()

    av = detect_clis()
    print("CLIs:")
    for name, path in av.items():
        print(f"  {name:6} {'✓ ' + path if path else '✗ not found'}")
    print()

    test_cmd = args.test_cmd or detect_test_cmd(repo)
    if not args.yes:
        test_cmd = ask("test command", test_cmd)

    steps: dict[str, dict] = {}
    for step in STEPS:
        d = DEFAULTS[step]
        cli = d["cli"] if d["cli"] == "none" else pick(d["cli"], av)
        if not args.yes:
            avail = [c for c in CLIS if av[c]] or ["none"]
            cli = ask(f"{step:10} cli", cli, avail)
            if cli not in CLIS and cli != "none":
                print(f"  (unknown cli {cli!r}; keeping {pick(d['cli'], av)})")
                cli = pick(d["cli"], av)
        entry = {"cli": cli}
        if d.get("permission") and cli != "none":
            entry["permission"] = d["permission"]
        if d.get("model") and cli == d["cli"]:
            entry["model"] = d["model"]
        steps[step] = entry

    if sag.exists() and (sag / "config.json").exists() and not args.force:
        ans = "y" if args.yes else ask(".sag already exists — overwrite config", "n", ["y", "n"])
        if ans != "y":
            print("kept existing config; nothing written")
            return 0

    sag.mkdir(parents=True, exist_ok=True)
    cfg = {
        "version": 1,
        "repo": str(repo),
        "domain": repo.name,
        "test_cmd": test_cmd,
        "steps": steps,
        "gates": [] if args.no_gates else ["execute"],
        "timeout_s": 900,
        "harness_dir": f"{SAG}/harness",
        "runs_dir": f"{SAG}/runs",
        "memory_dir": f"{SAG}/memory",
        "library_dir": f"{SAG}/library",
    }
    (sag / "config.json").write_text(json.dumps(cfg, indent=2) + "\n")

    # the project owns its harness: copy the factory skills once, then edit freely
    shutil.copytree(HERE / "skills", sag / "harness" / "skills", dirs_exist_ok=True)

    for name in ("decisions", "lessons", "context", "improvements"):
        p = sag / "memory" / f"{name}.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists():
            p.write_text(f"# {name}\n")
    (sag / "runs").mkdir(exist_ok=True)
    (sag / "library").mkdir(exist_ok=True)
    (sag / "guardrails.json").write_text(json.dumps(GUARDRAILS, indent=2) + "\n")
    (sag / ".gitignore").write_text("runs/\n__pycache__/\n")
    (sag / "README.md").write_text(
        "# .sag — project harness\n\n"
        "Setup once with `sag setup`. Daily use:\n\n"
        "```bash\ncd <repo>\nsag\n```\n\n"
        "- `harness/skills/<step>/SKILL.md` — edit to change that agent's behaviour\n"
        "- `runs/<id>/` — one directory per run (plan, diff, review, verify, ...)\n"
        "- `memory/` — decisions, lessons, context, improvements\n"
        "- `guardrails.json` — caps checked by `sag check`\n"
        "- `library/` — adopted harnesses + lessons per domain\n"
    )

    print()
    print(f"✓ wrote {SAG}/config.json")
    print(f"✓ installed harness skills ({len(STEPS)})")
    print("✓ memory, runs, library, guardrails")
    print()
    print("Next: `sag check`, then `sag`")
    return 0


# --------------------------------------------------------------------------- check
def cmd_check(args) -> int:
    repo, cfg = load_project()
    errs: list[str] = []
    warns: list[str] = []

    if git_root(repo) != repo:
        errs.append("not a git repository root (the pipeline expects git)")

    for step, s in cfg.get("steps", {}).items():
        cli = s.get("cli")
        if cli in (None, "none"):
            continue
        if not shutil.which(cli):
            errs.append(f"{step}: cli {cli!r} not on PATH")

    tc = cfg.get("test_cmd", "").strip()
    if not tc:
        errs.append("test_cmd is empty")
    else:
        exe = tc.split()[0]
        if exe.startswith(".venv/") or exe.startswith("./"):
            if not (repo / exe).exists():
                errs.append(f"test_cmd: {exe} does not exist")
        elif not shutil.which(exe):
            errs.append(f"test_cmd: {exe} not on PATH")

    hd = repo / cfg.get("harness_dir", f"{SAG}/harness")
    for step in STEPS:
        p = hd / "skills" / step / "SKILL.md"
        if not p.exists():
            errs.append(f"missing skill: {p.relative_to(repo)}")
        elif not p.read_text().startswith("---"):
            warns.append(f"skill {step}: no frontmatter")

    g = {}
    gp = repo / SAG / "guardrails.json"
    if gp.exists():
        g = json.loads(gp.read_text())
    cap = g.get("max_skill_chars", 6000)
    for p in (hd / "skills").glob("*/SKILL.md"):
        n = len(p.read_text())
        if n > cap:
            errs.append(f"{p.parent.name}/SKILL.md is {n} chars (cap {cap})")

    # executor must not see a grader verdict from an earlier run
    for r in sorted((repo / SAG / "runs").glob("*")):
        if (r / "verify.json").exists() and g.get("executor_sees_review") is False:
            pass  # run dirs are per-run; nothing to do, documented invariant

    for e in errs:
        print(f"FAIL: {e}")
    for w in warns:
        print(f"WARN: {w}")
    if errs:
        print(f"\n{len(errs)} issue(s). Fix them, then re-run `sag check`.")
        return 1
    print(f"Ready: {repo.name} · {len([s for s in cfg['steps'].values() if s.get('cli') not in (None,'none')])} agents · test: {tc}")
    print("Model access is not exercised; the first real run is the first model call.")
    return 0


# --------------------------------------------------------------------------- run
def cmd_run(args) -> int:
    repo, cfg = load_project()
    task = args.task
    if not task and args.run_id:
        tf = repo / SAG / "runs" / args.run_id / "task.txt"
        task = tf.read_text().strip() if tf.exists() else ""
    if not task and not args.baseline_run:
        try:
            task = input("task: ").strip()
        except EOFError:
            sys.exit("need a task")
    if not task and not args.baseline_run:
        sys.exit("empty task")
    steps = [s.strip() for s in args.steps.split(",")] if args.steps else STEPS
    for s in steps:
        if s not in STEPS:
            sys.exit(f"unknown step {s!r}; choose from {', '.join(STEPS)}")
    probe_steps = [s.strip() for s in args.probe_steps.split(",")] if args.probe_steps else None
    if args.k and args.k > 1:
        import recursion
        return recursion.run_with_recursion(cfg, task, repo, repo / SAG, args.k,
                                            args.mode, probe_steps, args.full_probe,
                                            args.baseline_run)
    return orch.run_pipeline(cfg, task, repo, repo / SAG, steps, args.auto,
                             args.dry_run, args.run_id)


# --------------------------------------------------------------------------- report
def cmd_report(args) -> int:
    repo, cfg = load_project()
    base = repo / SAG / "runs"
    if not base.exists():
        print("no runs yet")
        return 0
    if args.run_id:
        r = base / args.run_id
    else:
        runs = sorted(p for p in base.iterdir() if p.is_dir())
        if not runs:
            print("no runs yet")
            return 0
        r = runs[-1]
    if not r.exists():
        sys.exit(f"no such run: {r.name}")

    print(f"run {r.name} · {repo}")
    task = (r / "task.txt")
    if task.exists():
        print(f"task: {task.read_text().strip()[:200]}")
    print()
    for name in ("plan.md", "test-plan.md", "review.md", "verify.json", "improve.md"):
        p = r / name
        if not p.exists():
            continue
        print(f"── {name} " + "─" * 40)
        txt = p.read_text()
        print(txt[:2500] + ("\n…" if len(txt) > 2500 else ""))
        print()
    log = r / "log.jsonl"
    if log.exists():
        print("── steps " + "─" * 40)
        for line in log.read_text().splitlines():
            try:
                d = json.loads(line)
                print(f"  {d['step']:10} rc={d['rc']} {d['seconds']}s")
            except (json.JSONDecodeError, KeyError):
                pass
    return 0


def cmd_demo(args) -> int:
    repo, cfg = load_project()
    print("demo: dry-run, no model calls")
    return orch.run_pipeline(cfg, "demo: add GET /ping returning {\"pong\": true}",
                             repo, repo / SAG, STEPS, True, True)


# --------------------------------------------------------------------------- cli
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sag", description=banner())
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("setup", help="interactive setup for this repo")
    s.add_argument("--yes", "-y", action="store_true", help="accept every default")
    s.add_argument("--force", action="store_true", help="overwrite an existing .sag config")
    s.add_argument("--test-cmd", help="override the detected test command")
    s.add_argument("--no-gates", action="store_true", help="run without human gates")

    sub.add_parser("check", help="preflight the project harness")

    r = sub.add_parser("report", help="summarize a run")
    r.add_argument("--run-id", help="run id (default: latest)")

    sub.add_parser("demo", help="dry-run with a sample task")
    return p


def main() -> int:
    argv = sys.argv[1:]
    # `sag "task"` and `sag` run the pipeline; known words are subcommands
    if argv and argv[0] in ("setup", "init"):
        a = build_parser().parse_args(["setup", *argv[1:]])
        return cmd_setup(a)
    if argv and argv[0] == "check":
        build_parser().parse_args(["check", *argv[1:]])
        return cmd_check(None)
    if argv and argv[0] == "report":
        a = build_parser().parse_args(["report", *argv[1:]])
        return cmd_report(a)
    if argv and argv[0] == "demo":
        build_parser().parse_args(["demo", *argv[1:]])
        return cmd_demo(None)
    if argv and argv[0] in ("-h", "--help", "help"):
        build_parser().print_help()
        return 0

    # default: run
    ap = argparse.ArgumentParser(prog="sag", description="run the pipeline in this repo")
    ap.add_argument("task", nargs="?", help="what to build (prompted if omitted)")
    ap.add_argument("--auto", action="store_true", help="skip human gates")
    ap.add_argument("--steps", help="comma list, e.g. plan,write-test")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--run-id", help="resume an existing run")
    ap.add_argument("--k", type=int, default=1,
                    help="task-level recursion budget (1 = no recursion)")
    ap.add_argument("--mode", choices=("parallel", "sequential"), default="parallel",
                    help="parallel explores k candidates; sequential refines in rounds")
    ap.add_argument("--probe-steps", help="comma list of steps to re-run in a probe")
    ap.add_argument("--full-probe", action="store_true",
                    help="probe plan..verify instead of only the affected steps")
    ap.add_argument("--baseline-run", help="reuse an existing run directory as the baseline")
    return cmd_run(ap.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
