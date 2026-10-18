# Task 3 — stats() reports the wrong total

`stats()["total"]` is currently `len(_tasks) - 1`.

## Requirement
`stats()["total"]` must equal the number of tasks.

## Acceptance criteria
- After `reset()`: `stats() == {"total": 0, "done": 0}`.
- With 3 tasks: total is 3; after completing 1, done is 1.
- Add a test to `run_tests.py`, registered in `__main__` with `print("ok stats_total")`.
- `python3 run_tests.py` prints `ALL OK`.
