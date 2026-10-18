# Task 1 — reject empty titles

`add()` currently accepts any string. It must reject blank input.

## Requirement
`add(title)` raises `ValueError` when `title` is empty or whitespace-only.
A failed call must not create a task.

## Acceptance criteria
- `add("")` raises `ValueError`; `add("   ")` raises `ValueError`.
- `all_tasks()` is unchanged after a rejected call.
- `add("ok")` still works.
- Add a test to `run_tests.py`, register it in `__main__` with `print("ok empty_title")`.
- `python3 run_tests.py` prints `ALL OK`.
