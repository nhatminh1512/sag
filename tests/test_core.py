"""Small, dependency-free tests for the pipeline's pure parts.

Run with:  python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import orchestrator as O  # noqa: E402
import recursion as R  # noqa: E402


def make_run(root: Path, name: str, *, verify_pass: bool, review: str, tests: str) -> Path:
    d = root / name
    d.mkdir(parents=True)
    (d / "verify.json").write_text(json.dumps({
        "pass": verify_pass,
        "criteria": [{"criterion": "c", "met": True, "evidence": "e"}] * 5,
        "reasons": [] if verify_pass else ["review requested changes"],
    }))
    (d / "review.md").write_text(f"## Verdict\n\n{review}\n")
    (d / "test-output.txt").write_text(tests)
    return d


class ScoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_false_pass_scores_below_consistent_fail(self) -> None:
        # verify says pass while review requests changes -> the expensive failure
        false_pass = make_run(self.root, "false_pass", verify_pass=True,
                              review="REQUEST_CHANGES", tests="ALL OK")
        consistent = make_run(self.root, "consistent", verify_pass=False,
                              review="REQUEST_CHANGES", tests="ALL OK")
        a, b = R._score(false_pass), R._score(consistent)
        self.assertFalse(a["consistent"])
        self.assertTrue(b["consistent"])
        self.assertGreater(b["score"], a["score"])

    def test_clean_approval_scores_highest(self) -> None:
        clean = make_run(self.root, "clean", verify_pass=True,
                         review="APPROVE", tests="ALL OK")
        self.assertEqual(R._score(clean)["score"], 8.5)

    def test_compose_keeps_baseline_on_tie(self) -> None:
        a = {"label": "base", "score": {"score": 5.0}}
        b = {"label": "p1", "score": {"score": 5.0}}
        self.assertEqual(R.compose([a, b])["label"], "base")

    def test_compose_picks_higher_score(self) -> None:
        a = {"label": "base", "score": {"score": 3.5}}
        b = {"label": "p1", "score": {"score": 6.5}}
        self.assertEqual(R.compose([a, b])["label"], "p1")

    def test_score_missing_run_is_zero(self) -> None:
        self.assertEqual(R._score(self.root / "nope")["score"], 0.0)


class ExpandTests(unittest.TestCase):
    def test_verify_pulls_in_review(self) -> None:
        self.assertEqual(R.expand_steps(["verify"]), ["review", "verify"])

    def test_write_test_runs_to_verify(self) -> None:
        self.assertEqual(R.expand_steps(["write-test"]),
                         ["write-test", "execute", "review", "verify"])

    def test_empty_defaults_to_review_and_verify(self) -> None:
        self.assertEqual(R.expand_steps([]), ["review", "verify"])

    def test_earliest_affected_step_wins(self) -> None:
        self.assertEqual(R.expand_steps(["review", "verify"]),
                         ["review", "verify"])


class SkillTests(unittest.TestCase):
    def test_every_step_has_a_role_card(self) -> None:
        for step in O.STEPS:
            body = O.skill(step)
            self.assertTrue(body.strip(), f"{step} skill is empty")
            self.assertFalse(body.startswith("---"), f"{step} frontmatter was not stripped")

    def test_role_cards_are_small(self) -> None:
        for step in O.STEPS:
            self.assertLess(len(O.skill(step)), 6000, f"{step} skill is over the cap")


if __name__ == "__main__":
    unittest.main()
