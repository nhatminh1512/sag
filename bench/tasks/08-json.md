# Task 8 — stable JSON export

`to_json()` currently emits compact JSON with no ordering guarantee.

## Requirement
`to_json(indent=2)` returns JSON with `indent=2`, tasks sorted by id, and
`ensure_ascii=False`. Default behaviour may stay compact, but the indented form
must be stable.

## Acceptance criteria
- Output parses with `json.loads` and ids are ascending.
- `indent=2` produces newlines; a non-ASCII title survives unescaped.
- Calling it twice returns byte-identical output.
- Add a test to `run_tests.py`, registered in `__main__` with `print("ok to_json")`.
- `python3 run_tests.py` prints `ALL OK`.
