# Task 4 — search by title

Add `search(q)`.

## Requirement
Return the tasks whose title contains `q`, case-insensitive, in id order.
A blank or whitespace-only query returns all tasks.

## Acceptance criteria
- `search("DOC")` matches `"write docs"`.
- Results are ordered by id.
- `search("")` and `search("   ")` return all tasks.
- No mutation of the task list.
- Add a test to `run_tests.py`, registered in `__main__` with `print("ok search")`.
- `python3 run_tests.py` prints `ALL OK`.
