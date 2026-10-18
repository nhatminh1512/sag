# Task 7 — tasks due soon

Add `due_soon(days, today=None)`.

## Requirement
Return not-done tasks whose `due` is a valid `YYYY-MM-DD` date on or before
`today + days`. Missing or invalid `due` values are ignored. `today` defaults
to `date.today()` and may be a `date`.

## Acceptance criteria
- A task due today is included for `days=0`; one due tomorrow is not.
- A done task is excluded even if its due date qualifies.
- `due=None` and `due="not-a-date"` are ignored, not errors.
- Add a test to `run_tests.py`, registered in `__main__` with `print("ok due_soon")`.
- `python3 run_tests.py` prints `ALL OK`.
