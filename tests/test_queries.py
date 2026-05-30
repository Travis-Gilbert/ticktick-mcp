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


# ---------------------------------------------------------------------------
# filter_by_tags
# ---------------------------------------------------------------------------

def test_filter_by_tags_any():
    from ticktick_mcp.queries import filter_by_tags
    tasks = [
        {"id": "1", "title": "a", "tags": ["launch", "blocker"]},
        {"id": "2", "title": "b", "tags": ["chore"]},
        {"id": "3", "title": "c"},  # no tags field
    ]
    result = filter_by_tags(tasks, ["blocker"], match="any")
    assert [t["id"] for t in result] == ["1"]


def test_filter_by_tags_all():
    from ticktick_mcp.queries import filter_by_tags
    tasks = [
        {"id": "1", "title": "a", "tags": ["launch", "blocker"]},
        {"id": "2", "title": "b", "tags": ["launch"]},
    ]
    result = filter_by_tags(tasks, ["launch", "blocker"], match="all")
    assert [t["id"] for t in result] == ["1"]


def test_filter_by_tags_case_and_hash_insensitive():
    from ticktick_mcp.queries import filter_by_tags
    tasks = [{"id": "1", "title": "a", "tags": ["Blocker"]}]
    # Leading '#' and case are ignored on both the query and the task side.
    assert filter_by_tags(tasks, ["#blocker"]) == tasks
    assert filter_by_tags(tasks, ["BLOCKER"]) == tasks


def test_filter_by_tags_empty_returns_input():
    from ticktick_mcp.queries import filter_by_tags
    tasks = [{"id": "1", "title": "a", "tags": ["x"]}]
    assert filter_by_tags(tasks, []) is tasks


# ---------------------------------------------------------------------------
# group_by_horizon
# ---------------------------------------------------------------------------

def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S+0000")


def test_group_by_horizon_one_bucket_each_and_excludes_completed():
    from datetime import timedelta
    from ticktick_mcp.queries import group_by_horizon
    now = datetime.now(timezone.utc)
    overdue_task = {"id": "ov", "title": "overdue", "status": 0,
                    "dueDate": _iso(now - timedelta(days=3))}
    week_task = {"id": "wk", "title": "this week", "status": 0,
                 "dueDate": _iso(now + timedelta(days=3))}
    later_task = {"id": "lt", "title": "later", "status": 0,
                  "dueDate": _iso(now + timedelta(days=30))}
    no_date_task = {"id": "nd", "title": "no date", "status": 0}
    done_task = {"id": "dn", "title": "done", "status": 2,
                 "dueDate": _iso(now - timedelta(days=1))}

    buckets = group_by_horizon(
        [overdue_task, week_task, later_task, no_date_task, done_task]
    )

    assert [t["id"] for t in buckets["overdue"]] == ["ov"]
    assert [t["id"] for t in buckets["this_week"]] == ["wk"]
    assert [t["id"] for t in buckets["later"]] == ["lt"]
    assert [t["id"] for t in buckets["no_date"]] == ["nd"]

    all_ids = [t["id"] for bucket in buckets.values() for t in bucket]
    # Completed task is excluded from every bucket.
    assert "dn" not in all_ids
    # Each active task lands in exactly one bucket.
    assert sorted(all_ids) == ["lt", "nd", "ov", "wk"]
