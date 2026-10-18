# Task 9 — rename a task

Add `rename(task_id, title)`.

## Requirement
Set the title to the stripped value and return the task. Reject an empty or
whitespace-only title with `ValueError`. Missing id raises `KeyError`
containing `no task <id>`.

## Acceptance criteria
- `rename(1, "  new  ")` sets the title to `"new"` and returns the task.
- `rename(1, "   ")` raises `ValueError` and leaves the title unchanged.
- `rename(99, "x")` raises `KeyError` containing `no task 99`.
- Add a test to `run_tests.py`, registered in `__main__` with `print("ok rename")`.
- `python3 run_tests.py` prints `ALL OK`.
