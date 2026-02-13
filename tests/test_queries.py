import pytest
from datetime import datetime, timezone


def _make_task(title, due_date=None, priority=0, status=0, project_id="proj1"):
    """Helper to build a fake task dict."""
    t = {
        "id": f"task-{title.lower().replace(' ', '-')}",
        "title": title,
        "projectId": project_id,
        "priority": priority,
        "status": status,
    }
    if due_date:
        t["dueDate"] = due_date
    return t


def test_filter_overdue_tasks():
    from ticktick_mcp.queries import filter_overdue_tasks
    tasks = [
        _make_task("Old task", due_date="2026-02-01T09:00:00+0000", priority=5),
        _make_task("Future task", due_date="2099-01-01T09:00:00+0000"),
        _make_task("No date task"),
        _make_task("Done task", due_date="2026-02-01T09:00:00+0000", status=2),
    ]
    overdue = filter_overdue_tasks(tasks)
    assert len(overdue) == 1
    assert overdue[0]["title"] == "Old task"


def test_filter_due_today():
    from ticktick_mcp.queries import filter_due_today
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT")
    tasks = [
        _make_task("Today task", due_date=f"{today_str}09:00:00+0000"),
        _make_task("Tomorrow task", due_date="2099-01-01T09:00:00+0000"),
    ]
    today = filter_due_today(tasks)
    assert len(today) == 1
    assert today[0]["title"] == "Today task"


def test_sort_by_priority_then_date():
    from ticktick_mcp.queries import sort_by_priority_then_date
    tasks = [
        _make_task("Low", priority=1, due_date="2026-02-10T09:00:00+0000"),
        _make_task("High early", priority=5, due_date="2026-02-01T09:00:00+0000"),
        _make_task("High late", priority=5, due_date="2026-02-15T09:00:00+0000"),
        _make_task("Medium", priority=3),
    ]
    sorted_tasks = sort_by_priority_then_date(tasks)
    assert [t["title"] for t in sorted_tasks] == [
        "High early", "High late", "Medium", "Low"
    ]
