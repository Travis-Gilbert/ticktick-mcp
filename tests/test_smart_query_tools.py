"""Integration-style tests for smart query tools (overdue, due_today, engaged).

These mock the TickTick API client and test that the server tool functions
correctly fetch, filter, and format task data.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock


def _make_mock_ctx(projects, project_data_map):
    """Build a mock FastMCP context with stubbed V1 client."""
    mock_client = MagicMock()
    mock_client.get_projects = AsyncMock(return_value=projects)
    mock_client.get_project_with_data = AsyncMock(
        side_effect=lambda pid: project_data_map.get(pid, {"tasks": []})
    )
    ctx = MagicMock()
    ctx.request_context.lifespan_context = {
        "ticktick": mock_client,
        "ticktick_v2": None,
    }
    return ctx


@pytest.mark.asyncio
async def test_ticktick_get_overdue_tasks():
    from ticktick_mcp.server import ticktick_get_overdue_tasks
    from ticktick_mcp.models import GetOverdueTasksInput

    projects = [{"id": "p1", "name": "Work"}]
    data = {
        "p1": {
            "project": {"id": "p1", "name": "Work"},
            "tasks": [
                {
                    "id": "t1",
                    "title": "Old task",
                    "dueDate": "2026-01-01T09:00:00+0000",
                    "priority": 5,
                    "status": 0,
                    "projectId": "p1",
                },
                {
                    "id": "t2",
                    "title": "Future task",
                    "dueDate": "2099-01-01T09:00:00+0000",
                    "priority": 0,
                    "status": 0,
                    "projectId": "p1",
                },
            ],
        }
    }
    ctx = _make_mock_ctx(projects, data)
    result = await ticktick_get_overdue_tasks.fn(GetOverdueTasksInput(), ctx)
    assert "Old task" in result
    assert "Future task" not in result


@pytest.mark.asyncio
async def test_ticktick_get_overdue_tasks_json():
    from ticktick_mcp.server import ticktick_get_overdue_tasks
    from ticktick_mcp.models import GetOverdueTasksInput, ResponseFormat

    projects = [{"id": "p1", "name": "Inbox"}]
    data = {
        "p1": {
            "project": {"id": "p1", "name": "Inbox"},
            "tasks": [
                {
                    "id": "t1",
                    "title": "Overdue thing",
                    "dueDate": "2026-01-01T09:00:00+0000",
                    "priority": 3,
                    "status": 0,
                    "projectId": "p1",
                },
            ],
        }
    }
    ctx = _make_mock_ctx(projects, data)
    result = await ticktick_get_overdue_tasks.fn(
        GetOverdueTasksInput(response_format=ResponseFormat.JSON), ctx
    )
    assert '"count"' in result
    assert "Overdue thing" in result


@pytest.mark.asyncio
async def test_ticktick_get_overdue_empty():
    from ticktick_mcp.server import ticktick_get_overdue_tasks
    from ticktick_mcp.models import GetOverdueTasksInput

    projects = [{"id": "p1", "name": "Work"}]
    data = {
        "p1": {
            "project": {"id": "p1", "name": "Work"},
            "tasks": [
                {
                    "id": "t1",
                    "title": "Future task",
                    "dueDate": "2099-01-01T09:00:00+0000",
                    "priority": 0,
                    "status": 0,
                    "projectId": "p1",
                },
            ],
        }
    }
    ctx = _make_mock_ctx(projects, data)
    result = await ticktick_get_overdue_tasks.fn(GetOverdueTasksInput(), ctx)
    # Should handle empty result gracefully (no crash)
    assert isinstance(result, str)
