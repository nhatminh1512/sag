# Task 5 — delete a task

Add `delete(task_id)`.

## Requirement
Remove the task and return it. If the id does not exist, raise `KeyError`
containing `no task <id>`.

## Acceptance criteria
- `delete(1)` returns the removed task; `find(1)` is then `None`; the list shrinks by one.
- `delete(99)` raises `KeyError` containing `no task 99`.
- Add a test to `run_tests.py`, registered in `__main__` with `print("ok delete")`.
- `python3 run_tests.py` prints `ALL OK`.
