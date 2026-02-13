"""Pydantic input models for TickTick MCP tools.

Every tool uses a Pydantic BaseModel for input validation.
Field constraints catch bad input before it hits the API.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ResponseFormat(str, Enum):
    """Output format for tool responses."""
    MARKDOWN = "markdown"
    JSON = "json"


class ProjectViewMode(str, Enum):
    """TickTick project view modes."""
    LIST = "list"
    KANBAN = "kanban"
    TIMELINE = "timeline"


class ProjectKind(str, Enum):
    """TickTick project kinds."""
    TASK = "TASK"
    NOTE = "NOTE"


class TaskPriority(int, Enum):
    """TickTick task priority levels."""
    NONE = 0
    LOW = 1
    MEDIUM = 3
    HIGH = 5


# ---------------------------------------------------------------------------
# Shared model config
# ---------------------------------------------------------------------------

_STRICT_CONFIG = ConfigDict(
    str_strip_whitespace=True,
    validate_assignment=True,
    extra="forbid",
)


# ---------------------------------------------------------------------------
# Project models
# ---------------------------------------------------------------------------

class ListProjectsInput(BaseModel):
    """Input for listing all projects."""
    model_config = _STRICT_CONFIG

    response_format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="Output format: 'markdown' (human-readable) or 'json' (machine-readable)",
    )


class GetProjectInput(BaseModel):
    """Input for getting a project with its tasks."""
    model_config = _STRICT_CONFIG

    project_id: str = Field(
        ...,
        description="TickTick project/list ID (e.g., '696d539b8f08e340f3116156')",
        min_length=1,
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="Output format: 'markdown' or 'json'",
    )


class CreateProjectInput(BaseModel):
    """Input for creating a new project."""
    model_config = _STRICT_CONFIG

    name: str = Field(
        ...,
        description="Project name (e.g., 'Work Tasks', 'Shopping List')",
        min_length=1,
        max_length=200,
    )
    color: Optional[str] = Field(
        default=None,
        description="Hex color code (e.g., '#4772FA')",
        pattern=r"^#[0-9a-fA-F]{6}$",
    )
    view_mode: ProjectViewMode = Field(
        default=ProjectViewMode.LIST,
        description="View mode: 'list', 'kanban', or 'timeline'",
    )
    kind: ProjectKind = Field(
        default=ProjectKind.TASK,
        description="Project kind: 'TASK' or 'NOTE'",
    )


class UpdateProjectInput(BaseModel):
    """Input for updating an existing project."""
    model_config = _STRICT_CONFIG

    project_id: str = Field(..., description="Project ID to update", min_length=1)
    name: Optional[str] = Field(default=None, description="New project name", min_length=1, max_length=200)
    color: Optional[str] = Field(default=None, description="New hex color (e.g., '#FF0000')", pattern=r"^#[0-9a-fA-F]{6}$")
    view_mode: Optional[ProjectViewMode] = Field(default=None, description="New view mode")
    kind: Optional[ProjectKind] = Field(default=None, description="New kind")
    sort_order: Optional[int] = Field(default=None, description="Sort order (integer)")


class DeleteProjectInput(BaseModel):
    """Input for deleting a project."""
    model_config = _STRICT_CONFIG

    project_id: str = Field(..., description="Project ID to delete", min_length=1)


# ---------------------------------------------------------------------------
# Task models
# ---------------------------------------------------------------------------

class GetTaskInput(BaseModel):
    """Input for getting a single task."""
    model_config = _STRICT_CONFIG

    project_id: str = Field(..., description="Project ID containing the task", min_length=1)
    task_id: str = Field(..., description="Task ID to retrieve", min_length=1)
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN, description="Output format")


class SearchTasksInput(BaseModel):
    """Input for searching tasks within a project."""
    model_config = _STRICT_CONFIG

    project_id: str = Field(
        ...,
        description="Project ID to search within",
        min_length=1,
    )
    query: Optional[str] = Field(
        default=None,
        description="Text to search for in task titles and content (case-insensitive)",
    )
    priority: Optional[TaskPriority] = Field(
        default=None,
        description="Filter by priority: 0=none, 1=low, 3=medium, 5=high",
    )
    include_completed: bool = Field(
        default=False,
        description="Include completed tasks in results (default: only active tasks)",
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="Output format",
    )


class SubtaskInput(BaseModel):
    """A subtask (checklist item) within a task."""
    model_config = _STRICT_CONFIG

    title: str = Field(..., description="Subtask title", min_length=1, max_length=500)
    status: int = Field(
        default=0,
        description="Completion status: 0=normal, 1=completed",
        ge=0,
        le=1,
    )
    sort_order: Optional[int] = Field(default=None, description="Sort order")


class CreateTaskInput(BaseModel):
    """Input for creating a new task."""
    model_config = _STRICT_CONFIG

    title: str = Field(
        ...,
        description="Task title (e.g., 'Buy groceries', 'Review PR #42')",
        min_length=1,
        max_length=500,
    )
    project_id: str = Field(
        ...,
        description="Project ID to create the task in",
        min_length=1,
    )
    content: Optional[str] = Field(
        default=None,
        description="Task body/notes (supports markdown)",
        max_length=5000,
    )
    priority: TaskPriority = Field(
        default=TaskPriority.NONE,
        description="Priority: 0=none, 1=low, 3=medium, 5=high",
    )
    due_date: Optional[str] = Field(
        default=None,
        description="Due date in ISO format: 'yyyy-MM-ddTHH:mm:ssZ' (e.g., '2026-03-15T09:00:00+0000')",
    )
    start_date: Optional[str] = Field(
        default=None,
        description="Start date in ISO format: 'yyyy-MM-ddTHH:mm:ssZ'",
    )
    is_all_day: Optional[bool] = Field(
        default=None,
        description="Whether this is an all-day task",
    )
    time_zone: Optional[str] = Field(
        default=None,
        description="Time zone (e.g., 'America/New_York', 'America/Detroit')",
    )
    tags: Optional[list[str]] = Field(
        default=None,
        description="List of tag names (e.g., ['work', 'urgent'])",
    )
    subtasks: Optional[list[SubtaskInput]] = Field(
        default=None,
        description="Checklist items / subtasks",
    )
    repeat_flag: Optional[str] = Field(
        default=None,
        description="Recurrence in iCalendar RFC 5545 format (e.g., 'RRULE:FREQ=DAILY;INTERVAL=1')",
    )
    reminders: Optional[list[str]] = Field(
        default=None,
        description="Reminder triggers in iCalendar format (e.g., ['TRIGGER:PT0S', 'TRIGGER:P0DT9H0M0S'])",
    )

    @field_validator("due_date", "start_date")
    @classmethod
    def validate_date_format(cls, v: str | None) -> str | None:
        if v is not None and "T" not in v:
            raise ValueError(
                f"Date must be in ISO format 'yyyy-MM-ddTHH:mm:ssZ' (e.g., '2026-03-15T09:00:00+0000'), got: {v}"
            )
        return v


class UpdateTaskInput(BaseModel):
    """Input for updating an existing task."""
    model_config = _STRICT_CONFIG

    task_id: str = Field(..., description="Task ID to update", min_length=1)
    project_id: str = Field(..., description="Project ID containing the task", min_length=1)
    title: Optional[str] = Field(default=None, description="New task title", min_length=1, max_length=500)
    content: Optional[str] = Field(default=None, description="New task body/notes", max_length=5000)
    priority: Optional[TaskPriority] = Field(default=None, description="New priority: 0=none, 1=low, 3=medium, 5=high")
    due_date: Optional[str] = Field(default=None, description="New due date (ISO format)")
    start_date: Optional[str] = Field(default=None, description="New start date (ISO format)")
    is_all_day: Optional[bool] = Field(default=None, description="Whether this is an all-day task")
    time_zone: Optional[str] = Field(default=None, description="Time zone")
    tags: Optional[list[str]] = Field(default=None, description="New tags list")
    subtasks: Optional[list[SubtaskInput]] = Field(default=None, description="New subtasks list (replaces existing)")
    repeat_flag: Optional[str] = Field(default=None, description="New recurrence rule (iCalendar format)")
    reminders: Optional[list[str]] = Field(default=None, description="New reminders (iCalendar format)")

    @field_validator("due_date", "start_date")
    @classmethod
    def validate_date_format(cls, v: str | None) -> str | None:
        if v is not None and "T" not in v:
            raise ValueError(
                f"Date must be in ISO format 'yyyy-MM-ddTHH:mm:ssZ', got: {v}"
            )
        return v


class CompleteTaskInput(BaseModel):
    """Input for completing a task."""
    model_config = _STRICT_CONFIG

    project_id: str = Field(..., description="Project ID containing the task", min_length=1)
    task_id: str = Field(..., description="Task ID to complete", min_length=1)


class DeleteTaskInput(BaseModel):
    """Input for deleting a task."""
    model_config = _STRICT_CONFIG

    project_id: str = Field(..., description="Project ID containing the task", min_length=1)
    task_id: str = Field(..., description="Task ID to delete", min_length=1)


class BatchCreateTasksInput(BaseModel):
    """Input for batch-creating multiple tasks."""
    model_config = _STRICT_CONFIG

    project_id: str = Field(
        ...,
        description="Project ID to create all tasks in",
        min_length=1,
    )
    tasks: list[CreateTaskInput] = Field(
        ...,
        description="List of tasks to create (each needs at least a title)",
        min_length=1,
        max_length=50,
    )

    @field_validator("tasks")
    @classmethod
    def override_project_ids(cls, v: list[CreateTaskInput], info) -> list[CreateTaskInput]:
        """Ensure all tasks use the top-level project_id."""
        # This validator runs after individual task validation.
        # The top-level project_id is applied in the tool handler.
        return v


class MoveTaskInput(BaseModel):
    """Input for moving a task between projects."""
    model_config = _STRICT_CONFIG

    task_id: str = Field(..., description="Task ID to move", min_length=1)
    from_project_id: str = Field(..., description="Current project ID", min_length=1)
    to_project_id: str = Field(..., description="Destination project ID", min_length=1)
