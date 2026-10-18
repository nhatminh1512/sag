#!/usr/bin/env python3
"""Render results/runs.jsonl into results/RESULTS.md."""
from __future__ import annotations

import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ARMS = ["single", "sag"]


def fmt_time(seconds: float | None) -> str:
    if not seconds:
        return "—"
    seconds = int(round(seconds))
    return f"{seconds}s" if seconds < 60 else f"{seconds // 60}m {seconds % 60:02d}s"


def main() -> int:
    all_rows = [json.loads(line) for line in (ROOT / "results" / "runs.jsonl").read_text().splitlines() if line.strip()]
    for r in all_rows:
        raw = str(r.get("judge", {}).get("raw", "")).lower()
        r["status"] = "inconclusive" if "session limit" in raw else "valid"
    rows = [r for r in all_rows if r["status"] == "valid"]
    out = ["# Results", ""]

    out += ["## Summary", "",
            "| Arm | Valid tasks | Claims | False passes | False-pass rate | Unwired tests | Median time |",
            "|---|---:|---:|---:|---:|---:|---:|"]
    for arm in ARMS:
        rs = [r for r in rows if r["arm"] == arm]
        claims = sum(1 for r in rs if r["claim"])
        fps = sum(1 for r in rs if r["false_pass"])
        unwired = sum(1 for r in rs if r.get("wired") is False)
        times = [r["seconds"] for r in rs if r.get("seconds")]
        rate = f"{fps / claims:.0%}" if claims else "—"
        out.append(f"| {arm} | {len(rs)} | {claims} | {fps} | {rate} | {unwired} | "
                   f"{fmt_time(statistics.median(times) if times else None)} |")

    out += ["", "## Per task", "", "| Task | single | sag |", "|---|---|---|"]
    tasks = sorted({r["task"] for r in all_rows})
    for task in tasks:
        cells = []
        for arm in ARMS:
            r = next((x for x in all_rows if x["task"] == task and x["arm"] == arm), None)
            if r is None:
                cells.append("—")
            elif r["status"] == "inconclusive":
                cells.append("inconclusive")
            elif r["false_pass"]:
                cells.append("**false pass**")
            elif r["claim"]:
                cells.append("pass")
            else:
                cells.append("fail")
        out.append(f"| {task} | {cells[0]} | {cells[1]} |")

    disagreements = [r for r in rows if r["false_pass"]]
    out += ["", "## False passes", ""]
    if not disagreements:
        out += ["None in this run."]
    for r in disagreements:
        issues = r["judge"].get("blocking_issues") or []
        out.append(f"- **{r['task']} / {r['arm']}** — " + "; ".join(str(i) for i in issues[:3]))
        if r.get("wired") is False:
            out.append("  - the test marker never appeared in the test output (test not registered)")

    summary = {}
    for arm in ARMS:
        rs = [r for r in rows if r["arm"] == arm]
        claims = sum(1 for r in rs if r["claim"])
        fps = sum(1 for r in rs if r["false_pass"])
        times = [r["seconds"] for r in rs if r.get("seconds")]
        summary[arm] = {
            "n": len(rs),
            "claims": claims,
            "false_passes": fps,
            "false_pass_rate": round(fps / claims, 3) if claims else None,
            "unwired_tests": sum(1 for r in rs if r.get("wired") is False),
            "median_seconds": round(statistics.median(times), 1) if times else None,
        }
    (ROOT / "results" / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")

    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results" / "RESULTS.md").write_text("\n".join(out) + "\n")
    print((ROOT / "results" / "RESULTS.md").read_text())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
