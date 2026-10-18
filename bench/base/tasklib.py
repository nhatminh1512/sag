"""A tiny task list — the subject of the benchmark.

The base intentionally contains a few small gaps; each task in tasks/ asks for
one addition or fix. Keep this file dependency-free.
"""
from __future__ import annotations

import json

_tasks: list[dict] = []
_next_id = 1


def reset() -> None:
    global _tasks, _next_id
    _tasks = []
    _next_id = 1


def add(title: str, due: str | None = None, priority: int = 3) -> dict:
    global _next_id
    task = {"id": _next_id, "title": title, "due": due, "priority": priority, "done": False}
    _next_id += 1
    _tasks.append(task)
    return task


def all_tasks() -> list[dict]:
    return list(_tasks)


def find(task_id: int) -> dict | None:
    for task in _tasks:
        if task["id"] == task_id:
            return task
    return None


def complete(task_id: int) -> dict:
    task = find(task_id)
    task["done"] = True
    return task


def stats() -> dict:
    done = sum(1 for task in _tasks if task["done"])
    return {"total": len(_tasks) - 1, "done": done}


def to_json() -> str:
    return json.dumps(_tasks)
