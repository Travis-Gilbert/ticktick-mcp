"""TickTick MCP Server — general-purpose task management for Claude.

Provides 13 tools for interacting with the TickTick Open API v1.
Designed for use as a stdio MCP server in Claude Desktop or Claude Code.

Usage:
    python -m ticktick_mcp          # stdio transport (default)
    uv run python -m ticktick_mcp   # via uv
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from mcp.server.fastmcp import FastMCP

from ticktick_mcp.client import TickTickClient, TickTickAPIError
from ticktick_mcp.formatting import (
    format_json,
    format_project_md,
    format_projects_md,
    format_task_md,
    format_tasks_md,
    truncate_response,
)
from ticktick_mcp.models import (
    BatchCreateTasksInput,
    CompleteTaskInput,
    CreateProjectInput,
    CreateTaskInput,
    DeleteProjectInput,
    DeleteTaskInput,
    GetProjectInput,
    GetTaskInput,
    ListProjectsInput,
    MoveTaskInput,
    ResponseFormat,
    SearchTasksInput,
    UpdateProjectInput,
    UpdateTaskInput,
)


# ---------------------------------------------------------------------------
# Lifespan — shared TickTick client
# ---------------------------------------------------------------------------

@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[dict]:
    """Create a single TickTickClient at startup, close on shutdown."""
    client = TickTickClient()
    try:
        yield {"ticktick": client}
    finally:
        await client.close()


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "ticktick_mcp",
    instructions=(
        "General-purpose TickTick MCP for task and project management. "
        "Tools are prefixed with 'ticktick_' and support both Markdown "
        "and JSON response formats. Use ticktick_list_projects to discover "
        "project IDs, then use other tools with those IDs."
    ),
    lifespan=app_lifespan,
)


# ---------------------------------------------------------------------------
# Error handler
# ---------------------------------------------------------------------------

def _handle_error(e: Exception) -> str:
    """Convert exceptions to LLM-friendly error messages."""
    if isinstance(e, TickTickAPIError):
        if e.status_code == 401:
            return (
                "Error: Authentication failed. Your TickTick access token may be "
                "expired or invalid. Get a new token at https://developer.ticktick.com"
            )
        if e.status_code == 403:
            return "Error: Permission denied. Check your OAuth scopes include 'tasks:write'."
        if e.status_code == 404:
            return (
                "Error: Resource not found. Check that the project_id and task_id are correct. "
                "Use ticktick_list_projects to find valid project IDs."
            )
        if e.status_code == 429:
            return "Error: Rate limit exceeded. Wait a moment before retrying."
        return f"Error: TickTick API returned status {e.status_code}: {e.detail}"
    if isinstance(e, ValueError):
        return f"Error: Invalid input — {e}"
    return f"Error: {type(e).__name__} — {e}"


def _get_client(ctx) -> TickTickClient:
    """Extract the TickTick client from request context."""
    return ctx.request_context.lifespan_context["ticktick"]


# ===================================================================
# PROJECT TOOLS
# ===================================================================


@mcp.tool(
    name="ticktick_list_projects",
    annotations={
        "title": "List TickTick Projects",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def ticktick_list_projects(params: ListProjectsInput, ctx=None) -> str:
    """List all TickTick projects/lists for the authenticated user.

    Returns project names, IDs, colors, and view modes. Use this first
    to discover project IDs needed by other tools.

    Args:
        params: Contains response_format ('markdown' or 'json').

    Returns:
        Markdown-formatted project list, or JSON array of project objects.

    Examples:
        - "Show me all my TickTick lists" → call with default params
        - "Get my projects as JSON" → call with response_format="json"
    """
    try:
        client = _get_client(ctx)
        projects = await client.get_projects()
        if params.response_format == ResponseFormat.JSON:
            return truncate_response(format_json(projects))
        return truncate_response(format_projects_md(projects))
    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="ticktick_get_project",
    annotations={
        "title": "Get TickTick Project with Tasks",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def ticktick_get_project(params: GetProjectInput, ctx=None) -> str:
    """Get a TickTick project and all its tasks.

    Returns the project metadata plus every task in the project,
    including subtasks, priorities, dates, and tags.

    Args:
        params: Contains project_id and response_format.

    Returns:
        Markdown or JSON with project info and task list.

    Examples:
        - "Show me everything in my Work project" → call with project_id
        - "Get tasks in list 696d539b..." → call with that project_id
    """
    try:
        client = _get_client(ctx)
        data = await client.get_project_with_data(params.project_id)
        if params.response_format == ResponseFormat.JSON:
            return truncate_response(format_json(data))

        project = data.get("project", data)
        tasks = data.get("tasks", [])
        name = project.get("name", "Unknown")
        result = format_projects_md([project]) + "\n\n" + format_tasks_md(tasks, name)
        return truncate_response(result)
    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="ticktick_create_project",
    annotations={
        "title": "Create TickTick Project",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def ticktick_create_project(params: CreateProjectInput, ctx=None) -> str:
    """Create a new TickTick project/list.

    Args:
        params: Contains name (required), plus optional color, view_mode, kind.

    Returns:
        Markdown or JSON with the created project's details including its new ID.

    Examples:
        - "Create a project called Groceries" → name="Groceries"
        - "Make a kanban board for Sprint 3" → name="Sprint 3", view_mode="kanban"
    """
    try:
        client = _get_client(ctx)
        body: dict = {"name": params.name}
        if params.color:
            body["color"] = params.color
        if params.view_mode:
            body["viewMode"] = params.view_mode.value
        if params.kind:
            body["kind"] = params.kind.value

        result = await client.create_project(body)
        return f"Project created successfully.\n\n{format_project_md(result)}"
    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="ticktick_update_project",
    annotations={
        "title": "Update TickTick Project",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def ticktick_update_project(params: UpdateProjectInput, ctx=None) -> str:
    """Update an existing TickTick project's properties.

    Only the fields you provide will be changed; others remain untouched.

    Args:
        params: Contains project_id (required) and optional name, color, view_mode, kind, sort_order.

    Returns:
        Markdown showing the updated project.

    Examples:
        - "Rename my project to 'Q2 Goals'" → project_id=..., name="Q2 Goals"
        - "Change the color to red" → project_id=..., color="#FF0000"
    """
    try:
        client = _get_client(ctx)
        body: dict = {}
        if params.name is not None:
            body["name"] = params.name
        if params.color is not None:
            body["color"] = params.color
        if params.view_mode is not None:
            body["viewMode"] = params.view_mode.value
        if params.kind is not None:
            body["kind"] = params.kind.value
        if params.sort_order is not None:
            body["sortOrder"] = params.sort_order

        if not body:
            return "Error: No fields to update. Provide at least one of: name, color, view_mode, kind, sort_order."

        result = await client.update_project(params.project_id, body)
        return f"Project updated successfully.\n\n{format_project_md(result)}"
    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="ticktick_delete_project",
    annotations={
        "title": "Delete TickTick Project",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def ticktick_delete_project(params: DeleteProjectInput, ctx=None) -> str:
    """Permanently delete a TickTick project and all its tasks.

    WARNING: This is irreversible. All tasks in the project will be deleted.

    Args:
        params: Contains project_id to delete.

    Returns:
        Confirmation message.
    """
    try:
        client = _get_client(ctx)
        await client.delete_project(params.project_id)
        return f"Project `{params.project_id}` deleted successfully."
    except Exception as e:
        return _handle_error(e)


# ===================================================================
# TASK TOOLS
# ===================================================================


@mcp.tool(
    name="ticktick_get_task",
    annotations={
        "title": "Get TickTick Task",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def ticktick_get_task(params: GetTaskInput, ctx=None) -> str:
    """Get a single TickTick task by its project ID and task ID.

    Returns full task details including title, content, priority,
    dates, tags, and subtasks.

    Args:
        params: Contains project_id, task_id, and response_format.

    Returns:
        Markdown or JSON with complete task details.

    Examples:
        - "Show me task abc123 in project 696d..." → project_id, task_id
    """
    try:
        client = _get_client(ctx)
        task = await client.get_task(params.project_id, params.task_id)
        if params.response_format == ResponseFormat.JSON:
            return format_json(task)
        return format_task_md(task)
    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="ticktick_search_tasks",
    annotations={
        "title": "Search TickTick Tasks",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def ticktick_search_tasks(params: SearchTasksInput, ctx=None) -> str:
    """Search for tasks within a TickTick project.

    Fetches all tasks in the project and filters locally by text query,
    priority, and completion status. The TickTick API does not have a
    native search endpoint, so this tool handles filtering client-side.

    Args:
        params: Contains project_id (required), plus optional query, priority,
                include_completed, and response_format.

    Returns:
        Markdown or JSON list of matching tasks.

    Examples:
        - "Find tasks about 'voiceover' in project X" → project_id=X, query="voiceover"
        - "Show high-priority tasks" → project_id=X, priority=5
        - "List all tasks including completed" → include_completed=True
    """
    try:
        client = _get_client(ctx)
        data = await client.get_project_with_data(params.project_id)
        tasks = data.get("tasks", [])
        project_name = data.get("project", {}).get("name", "")

        # Filter by completion status
        if not params.include_completed:
            tasks = [t for t in tasks if t.get("status", 0) != 2]

        # Filter by text query (case-insensitive)
        if params.query:
            q = params.query.lower()
            tasks = [
                t for t in tasks
                if q in (t.get("title", "").lower())
                or q in (t.get("content", "").lower())
            ]

        # Filter by priority
        if params.priority is not None:
            tasks = [t for t in tasks if t.get("priority", 0) == params.priority.value]

        if params.response_format == ResponseFormat.JSON:
            return truncate_response(format_json({"count": len(tasks), "tasks": tasks}))
        return truncate_response(format_tasks_md(tasks, project_name))
    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="ticktick_create_task",
    annotations={
        "title": "Create TickTick Task",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def ticktick_create_task(params: CreateTaskInput, ctx=None) -> str:
    """Create a new task in a TickTick project.

    Supports all task properties: title, content, priority, dates,
    tags, subtasks, recurrence, and reminders.

    Args:
        params: Contains title and project_id (required), plus many optional fields.

    Returns:
        Markdown showing the created task with its new ID.

    Examples:
        - "Add 'Buy milk' to my Groceries list" → title="Buy milk", project_id=...
        - "Create a high-priority task due tomorrow" → title=..., priority=5, due_date=...
        - "Add a task with subtasks" → title=..., subtasks=[{title: "Step 1"}, ...]
    """
    try:
        client = _get_client(ctx)
        body = _build_task_body(params)
        result = await client.create_task(body)
        return f"Task created successfully.\n\n{format_task_md(result)}"
    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="ticktick_update_task",
    annotations={
        "title": "Update TickTick Task",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def ticktick_update_task(params: UpdateTaskInput, ctx=None) -> str:
    """Update an existing TickTick task.

    Only the fields you provide will be changed. You must always provide
    both task_id and project_id.

    Args:
        params: Contains task_id and project_id (required), plus optional fields to update.

    Returns:
        Markdown showing the updated task.

    Examples:
        - "Change the title to 'Revised script'" → task_id=..., project_id=..., title="Revised script"
        - "Set priority to high" → task_id=..., project_id=..., priority=5
        - "Add a due date" → task_id=..., project_id=..., due_date="2026-03-15T09:00:00+0000"
    """
    try:
        client = _get_client(ctx)
        body: dict = {"id": params.task_id, "projectId": params.project_id}
        if params.title is not None:
            body["title"] = params.title
        if params.content is not None:
            body["content"] = params.content
        if params.priority is not None:
            body["priority"] = params.priority.value
        if params.due_date is not None:
            body["dueDate"] = params.due_date
        if params.start_date is not None:
            body["startDate"] = params.start_date
        if params.is_all_day is not None:
            body["isAllDay"] = params.is_all_day
        if params.time_zone is not None:
            body["timeZone"] = params.time_zone
        if params.tags is not None:
            body["tags"] = params.tags
        if params.subtasks is not None:
            body["items"] = [
                {"title": s.title, "status": s.status, **({"sortOrder": s.sort_order} if s.sort_order is not None else {})}
                for s in params.subtasks
            ]
        if params.repeat_flag is not None:
            body["repeatFlag"] = params.repeat_flag
        if params.reminders is not None:
            body["reminders"] = params.reminders

        result = await client.update_task(params.task_id, body)
        return f"Task updated successfully.\n\n{format_task_md(result)}"
    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="ticktick_complete_task",
    annotations={
        "title": "Complete TickTick Task",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def ticktick_complete_task(params: CompleteTaskInput, ctx=None) -> str:
    """Mark a TickTick task as completed.

    Args:
        params: Contains project_id and task_id.

    Returns:
        Confirmation message.

    Examples:
        - "Mark task abc123 as done" → project_id=..., task_id="abc123"
    """
    try:
        client = _get_client(ctx)
        await client.complete_task(params.project_id, params.task_id)
        return f"Task `{params.task_id}` completed successfully."
    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="ticktick_delete_task",
    annotations={
        "title": "Delete TickTick Task",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def ticktick_delete_task(params: DeleteTaskInput, ctx=None) -> str:
    """Permanently delete a TickTick task.

    WARNING: This is irreversible. The task and its subtasks will be removed.

    Args:
        params: Contains project_id and task_id.

    Returns:
        Confirmation message.
    """
    try:
        client = _get_client(ctx)
        await client.delete_task(params.project_id, params.task_id)
        return f"Task `{params.task_id}` deleted successfully."
    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="ticktick_batch_create_tasks",
    annotations={
        "title": "Batch Create TickTick Tasks",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def ticktick_batch_create_tasks(params: BatchCreateTasksInput, ctx=None) -> str:
    """Create multiple TickTick tasks at once in a single API call.

    All tasks are created in the same project. More efficient than
    creating tasks one by one when you have several to add.

    Args:
        params: Contains project_id and a list of task definitions (max 50).

    Returns:
        Summary of created tasks.

    Examples:
        - "Add these 5 tasks to my Sprint list" → project_id=..., tasks=[...]
    """
    try:
        client = _get_client(ctx)
        task_bodies = []
        for task in params.tasks:
            body = _build_task_body(task)
            body["projectId"] = params.project_id  # Override with top-level
            task_bodies.append(body)

        results = await client.batch_create_tasks(task_bodies)
        count = len(results) if isinstance(results, list) else 0
        return f"Batch created {count} tasks in project `{params.project_id}`."
    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="ticktick_move_task",
    annotations={
        "title": "Move TickTick Task",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def ticktick_move_task(params: MoveTaskInput, ctx=None) -> str:
    """Move a task from one project to another.

    Fetches the task, updates its projectId, and saves it to the new project.

    Args:
        params: Contains task_id, from_project_id, and to_project_id.

    Returns:
        Confirmation with the task's new location.

    Examples:
        - "Move task abc123 from Inbox to Work" → task_id, from_project_id, to_project_id
    """
    try:
        client = _get_client(ctx)
        # Fetch the current task
        task = await client.get_task(params.from_project_id, params.task_id)
        # Update with new project ID
        body = {
            "id": params.task_id,
            "projectId": params.to_project_id,
            "title": task.get("title", ""),
        }
        result = await client.update_task(params.task_id, body)
        title = result.get("title", task.get("title", "?"))
        return f"Task '{title}' moved from project `{params.from_project_id}` to `{params.to_project_id}`."
    except Exception as e:
        return _handle_error(e)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _build_task_body(params: CreateTaskInput) -> dict:
    """Build a TickTick API task body from CreateTaskInput."""
    body: dict = {
        "title": params.title,
        "projectId": params.project_id,
    }
    if params.content:
        body["content"] = params.content
    if params.priority and params.priority.value != 0:
        body["priority"] = params.priority.value
    if params.due_date:
        body["dueDate"] = params.due_date
    if params.start_date:
        body["startDate"] = params.start_date
    if params.is_all_day is not None:
        body["isAllDay"] = params.is_all_day
    if params.time_zone:
        body["timeZone"] = params.time_zone
    if params.tags:
        body["tags"] = params.tags
    if params.subtasks:
        body["items"] = [
            {"title": s.title, "status": s.status, **({"sortOrder": s.sort_order} if s.sort_order is not None else {})}
            for s in params.subtasks
        ]
    if params.repeat_flag:
        body["repeatFlag"] = params.repeat_flag
    if params.reminders:
        body["reminders"] = params.reminders
    return body
