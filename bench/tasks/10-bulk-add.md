# Task 10 — atomic bulk add

Add `bulk_add(titles)`.

## Requirement
Add every title, or none: if any title is empty/whitespace-only, raise
`ValueError` and leave the task list exactly as it was. Return the added tasks
in input order.

## Acceptance criteria
- `bulk_add(["a", "b"])` adds two tasks and returns them.
- `bulk_add(["ok", "  "])` raises `ValueError`; `all_tasks()` is unchanged.
- Ids are sequential across the batch.
- Add a test to `run_tests.py`, registered in `__main__` with `print("ok bulk_add")`.
- `python3 run_tests.py` prints `ALL OK`.
