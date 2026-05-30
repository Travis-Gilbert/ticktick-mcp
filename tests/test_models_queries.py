import pytest
from pydantic import ValidationError


def test_get_tasks_due_today_input_defaults():
    from ticktick_mcp.models import GetTasksDueTodayInput, ResponseFormat
    params = GetTasksDueTodayInput()
    assert params.response_format == ResponseFormat.MARKDOWN


def test_get_overdue_tasks_input_defaults():
    from ticktick_mcp.models import GetOverdueTasksInput
    params = GetOverdueTasksInput()
    assert params.include_no_date is False


def test_search_all_tasks_input_requires_query():
    from ticktick_mcp.models import SearchAllTasksInput
    with pytest.raises(ValidationError):
        SearchAllTasksInput()

    params = SearchAllTasksInput(query="voiceover")
    assert params.query == "voiceover"
    assert params.include_completed is False


def test_get_engaged_tasks_input():
    from ticktick_mcp.models import GetEngagedTasksInput
    params = GetEngagedTasksInput()
    assert params.response_format.value == "markdown"


def test_plan_day_input():
    from ticktick_mcp.models import PlanDayInput
    params = PlanDayInput(available_hours=6.0)
    assert params.available_hours == 6.0


def test_launch_dashboard_input_defaults():
    from ticktick_mcp.models import LaunchDashboardInput, ResponseFormat
    params = LaunchDashboardInput(project_ids=["p1"])
    assert params.match == "any"
    assert params.tags is None
    assert params.include_completed_today is False
    assert params.response_format == ResponseFormat.MARKDOWN


def test_launch_dashboard_input_requires_non_empty_project_ids():
    from ticktick_mcp.models import LaunchDashboardInput
    with pytest.raises(ValidationError):
        LaunchDashboardInput()
    with pytest.raises(ValidationError):
        LaunchDashboardInput(project_ids=[])


def test_batch_move_input_builds_nested_task_moves():
    from ticktick_mcp.models import BatchMoveInput, TaskMove
    params = BatchMoveInput(moves=[
        {"task_id": "t1", "from_project_id": "a", "to_project_id": "b"},
    ])
    assert len(params.moves) == 1
    assert isinstance(params.moves[0], TaskMove)
    assert params.moves[0].to_project_id == "b"


def test_batch_move_input_rejects_empty():
    from ticktick_mcp.models import BatchMoveInput
    with pytest.raises(ValidationError):
        BatchMoveInput(moves=[])
