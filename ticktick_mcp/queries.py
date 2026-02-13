"""Cross-project query helpers for smart task filtering.

These functions operate on lists of task dicts returned by the TickTick API.
They are pure functions (no I/O) for easy testing.
"""

from __future__ import annotations

from datetime import datetime, timezone, date, timedelta


def parse_date(date_str: str | None) -> datetime | None:
    """Parse a TickTick date string to datetime. Returns None if unparseable."""
    if not date_str:
        return None
    try:
        # TickTick uses format like "2026-02-13T09:00:00+0000"
        # Also handles "2026-02-13T09:00:00.000+0000"
        cleaned = date_str.replace(".000", "")
        if cleaned.endswith("+0000") or cleaned.endswith("-0000"):
            cleaned = cleaned[:-5] + "+00:00"
        return datetime.fromisoformat(cleaned)
    except (ValueError, TypeError):
        return None


def is_active(task: dict) -> bool:
    """Check if task is not completed (status != 2)."""
    return task.get("status", 0) != 2


def filter_overdue_tasks(tasks: list[dict]) -> list[dict]:
    """Return active tasks with due dates in the past."""
    now = datetime.now(timezone.utc)
    result = []
    for t in tasks:
        if not is_active(t):
            continue
        due = parse_date(t.get("dueDate"))
        if due and due < now:
            result.append(t)
    return sort_by_priority_then_date(result)


def filter_due_today(tasks: list[dict]) -> list[dict]:
    """Return active tasks due today."""
    today = date.today()
    result = []
    for t in tasks:
        if not is_active(t):
            continue
        due = parse_date(t.get("dueDate"))
        if due and due.date() == today:
            result.append(t)
    return sort_by_priority_then_date(result)


def filter_due_this_week(tasks: list[dict]) -> list[dict]:
    """Return active tasks due within the next 7 days (excluding today)."""
    now = datetime.now(timezone.utc)
    today = now.date()
    week_end = today + timedelta(days=7)
    result = []
    for t in tasks:
        if not is_active(t):
            continue
        due = parse_date(t.get("dueDate"))
        if due and today < due.date() <= week_end:
            result.append(t)
    return sort_by_priority_then_date(result)


def filter_completed_since(tasks: list[dict], since: datetime) -> list[dict]:
    """Return tasks completed after the given datetime."""
    result = []
    for t in tasks:
        if t.get("status") != 2:
            continue
        completed = parse_date(t.get("completedTime"))
        if completed and completed >= since:
            result.append(t)
    return result


def filter_engaged(tasks: list[dict]) -> list[dict]:
    """GTD 'Engaged' list: high priority OR overdue."""
    now = datetime.now(timezone.utc)
    result = []
    for t in tasks:
        if not is_active(t):
            continue
        is_high = t.get("priority", 0) >= 5
        due = parse_date(t.get("dueDate"))
        is_overdue = due is not None and due < now
        if is_high or is_overdue:
            result.append(t)
    return sort_by_priority_then_date(result)


def sort_by_priority_then_date(tasks: list[dict]) -> list[dict]:
    """Sort tasks by priority (desc) then due date (asc, None last)."""
    def sort_key(t):
        priority = -(t.get("priority", 0))
        due = parse_date(t.get("dueDate"))
        date_key = due.isoformat() if due else "9999"
        return (priority, date_key)
    return sorted(tasks, key=sort_key)


def search_tasks(tasks: list[dict], query: str) -> list[dict]:
    """Case-insensitive search in task title and content."""
    q = query.lower()
    return [
        t for t in tasks
        if q in t.get("title", "").lower()
        or q in t.get("content", "").lower()
    ]
