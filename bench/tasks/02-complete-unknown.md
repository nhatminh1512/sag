# Task 2 — complete() on a missing id

`complete(99)` currently raises `TypeError` because `find()` returns `None`.

## Requirement
`complete(task_id)` raises `KeyError` whose message contains `no task 99`
when the id does not exist. Completing an existing task still works.

## Acceptance criteria
- `complete(99)` raises `KeyError`, and `"no task 99"` is in `str(exc)`.
- `complete(1)` on an existing task still marks it done.
- Add a test to `run_tests.py`, registered in `__main__` with `print("ok complete_unknown")`.
- `python3 run_tests.py` prints `ALL OK`.
