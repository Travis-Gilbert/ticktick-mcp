"""Tests for the launch dashboard tool and the hardened batch-move path.

The dashboard test mocks the V1 client and checks tag filtering + horizon
grouping. The move_tasks tests cover both the dedicated-endpoint path and the
verified fallback, including the case where a move silently fails to take.
"""

from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S+0000")


@pytest.mark.asyncio
async def test_launch_dashboard_filters_by_tag_and_groups_by_horizon():
    from ticktick_mcp.server import ticktick_launch_dashboard
    from ticktick_mcp.models import LaunchDashboardInput

    now = datetime.now(timezone.utc)
    projects = [{"id": "p1", "name": "Product A"}, {"id": "p2", "name": "Product B"}]
    data = {
        "p1": {"project": {"id": "p1", "name": "Product A"}, "tasks": [
            {"id": "t1", "title": "Blocker bug", "status": 0, "priority": 5,
             "projectId": "p1", "tags": ["blocker"],
             "dueDate": _iso(now - timedelta(days=2))},
            {"id": "t2", "title": "Untagged chore", "status": 0, "projectId": "p1"},
        ]},
        "p2": {"project": {"id": "p2", "name": "Product B"}, "tasks": [
            {"id": "t3", "title": "Future blocker", "status": 0, "priority": 3,
             "projectId": "p2", "tags": ["blocker"],
             "dueDate": _iso(now + timedelta(days=30))},
        ]},
    }
    mock_client = MagicMock()
    mock_client.get_projects = AsyncMock(return_value=projects)
    mock_client.get_project_with_data = AsyncMock(
        side_effect=lambda pid: data.get(pid, {"tasks": []})
    )
    ctx = MagicMock()
    ctx.request_context.lifespan_context = {"ticktick": mock_client}

    result = await ticktick_launch_dashboard.fn(
        LaunchDashboardInput(project_ids=["p1", "p2"], tags=["blocker"]), ctx
    )

    assert "Blocker bug" in result        # overdue + tagged
    assert "Future blocker" in result     # later + tagged
    assert "Untagged chore" not in result # filtered out by tag
    assert "Overdue" in result and "Later" in result
    # Only the two requested projects are fetched.
    assert mock_client.get_project_with_data.await_count == 2


@pytest.mark.asyncio
async def test_move_tasks_dedicated_endpoint_success():
    from ticktick_mcp.client import TickTickClient

    client = TickTickClient(access_token="test")
    client._request = AsyncMock(return_value=None)
    try:
        results = await client.move_tasks(
            [{"taskId": "t1", "fromProjectId": "a", "toProjectId": "b"}]
        )
    finally:
        await client.close()

    assert results == [
        {"taskId": "t1", "fromProjectId": "a", "toProjectId": "b", "moved": True}
    ]
    client._request.assert_awaited_once()


@pytest.mark.asyncio
async def test_move_tasks_falls_back_and_verifies_success():
    from ticktick_mcp.client import TickTickClient, TickTickAPIError

    client = TickTickClient(access_token="test")
    client._request = AsyncMock(side_effect=TickTickAPIError(404, "no such endpoint"))

    async def get_task(pid, tid):
        return {"id": tid, "title": "Move me", "projectId": pid}

    client.get_task = AsyncMock(side_effect=get_task)
    client.update_task = AsyncMock(return_value={})
    try:
        results = await client.move_tasks(
            [{"taskId": "t1", "fromProjectId": "a", "toProjectId": "b"}]
        )
    finally:
        await client.close()

    r = results[0]
    assert r["moved"] is True
    assert r["title"] == "Move me"
    client.update_task.assert_awaited_once()


@pytest.mark.asyncio
async def test_move_tasks_fallback_detects_silent_noop():
    from ticktick_mcp.client import TickTickClient, TickTickAPIError

    client = TickTickClient(access_token="test")
    client._request = AsyncMock(side_effect=TickTickAPIError(404, "no endpoint"))

    async def get_task(pid, tid):
        # Task never leaves the source project; the destination re-read 404s.
        if pid == "b":
            raise TickTickAPIError(404, "not found in destination")
        return {"id": tid, "title": "Stuck", "projectId": "a"}

    client.get_task = AsyncMock(side_effect=get_task)
    client.update_task = AsyncMock(return_value={})
    try:
        results = await client.move_tasks(
            [{"taskId": "t1", "fromProjectId": "a", "toProjectId": "b"}]
        )
    finally:
        await client.close()

    r = results[0]
    assert r["moved"] is False
    assert "error" in r
