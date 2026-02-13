"""Tests for the daily standup and weekly review tools.

Mocks the TickTick client and verifies the standup output
contains the expected sections (overdue, due today, etc.).
"""

import pytest
from unittest.mock import AsyncMock, MagicMock


def _make_mock_ctx_with_tasks(project_task_pairs):
    """Build a mock context from (project_id, project_name, tasks) triples."""
    projects = [
        {"id": pid, "name": pname, "closed": False}
        for pid, pname, _ in project_task_pairs
    ]
    data_map = {}
    for pid, pname, tasks in project_task_pairs:
        data_map[pid] = {
            "project": {"id": pid, "name": pname},
            "tasks": tasks,
        }

    mock_client = MagicMock()
    mock_client.get_projects = AsyncMock(return_value=projects)
    mock_client.get_project_with_data = AsyncMock(
        side_effect=lambda pid: data_map.get(pid, {"tasks": []})
    )
    ctx = MagicMock()
    ctx.request_context.lifespan_context = {
        "ticktick": mock_client,
        "ticktick_v2": None,
    }
    return ctx


@pytest.mark.asyncio
async def test_daily_standup_returns_sections():
    from ticktick_mcp.server import ticktick_daily_standup
    from ticktick_mcp.models import DailyStandupInput

    ctx = _make_mock_ctx_with_tasks([
        (
            "p1",
            "Work",
            [
                {
                    "id": "t1",
                    "title": "Overdue task",
                    "dueDate": "2026-01-01T09:00:00+0000",
                    "priority": 5,
                    "status": 0,
                    "projectId": "p1",
                },
            ],
        ),
    ])
    result = await ticktick_daily_standup.fn(DailyStandupInput(), ctx)
    # Standup should contain section headers and the overdue task
    assert "Overdue" in result or "OVERDUE" in result or "overdue" in result
    assert "Overdue task" in result


@pytest.mark.asyncio
async def test_daily_standup_empty_projects():
    from ticktick_mcp.server import ticktick_daily_standup
    from ticktick_mcp.models import DailyStandupInput

    ctx = _make_mock_ctx_with_tasks([("p1", "Empty", [])])
    result = await ticktick_daily_standup.fn(DailyStandupInput(), ctx)
    # Should succeed without error, even with no tasks
    assert isinstance(result, str)


@pytest.mark.asyncio
async def test_daily_standup_is_string():
    from ticktick_mcp.server import ticktick_daily_standup
    from ticktick_mcp.models import DailyStandupInput

    ctx = _make_mock_ctx_with_tasks([
        (
            "p1",
            "Work",
            [
                {
                    "id": "t2",
                    "title": "Normal task",
                    "dueDate": "2099-01-01T09:00:00+0000",
                    "priority": 1,
                    "status": 0,
                    "projectId": "p1",
                },
            ],
        ),
    ])
    result = await ticktick_daily_standup.fn(DailyStandupInput(), ctx)
    assert isinstance(result, str)
    assert len(result) > 0
