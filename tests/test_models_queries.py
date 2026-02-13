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
