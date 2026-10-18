# Task 6 — deterministic ordering

Add `sorted_tasks()`.

## Requirement
Return a new list ordered by `priority` ascending (1 first), ties broken by
`id` ascending. Do not mutate `_tasks`.

## Acceptance criteria
- Priorities `[3, 1, 2]` with ids `[1, 2, 3]` come out as ids `[2, 3, 1]`.
- Two tasks with the same priority keep id order.
- `all_tasks()` order is unchanged after the call.
- Add a test to `run_tests.py`, registered in `__main__` with `print("ok sort")`.
- `python3 run_tests.py` prints `ALL OK`.
