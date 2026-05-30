"""TickTick MCP Server — general-purpose task management for Claude.

Provides 22 tools for the TickTick Open API v1 (OAuth bearer token):
project and task CRUD, cross-project smart queries, a daily standup and
weekly review, a cross-list launch dashboard, and batch task moves.
Designed for use as a stdio MCP server in Claude Desktop or Claude Code,
and as a Streamable HTTP server on Railway for remote access.

Usage:
    python -m ticktick_mcp          # stdio transport (default)
    uv run python -m ticktick_mcp   # via uv
"""

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from typing import AsyncIterator

from fastmcp import FastMCP, Context

from ticktick_mcp.client import TickTickClient, TickTickAPIError
from ticktick_mcp.formatting import (
    format_dashboard_md,
    format_json,
    format_project_md,
    format_projects_md,
    format_task_md,
    format_tasks_md,
    truncate_response,
)
from ticktick_mcp.models import (
    BatchCreateTasksInput,
    BatchMoveInput,
    CompleteTaskInput,
    CreateProjectInput,
    CreateTaskInput,
    DailyStandupInput,
    DeleteProjectInput,
    DeleteTaskInput,
    GetEngagedTasksInput,
    GetOverdueTasksInput,
    GetProjectInput,
    GetTaskInput,
    GetTasksDueTodayInput,
    LaunchDashboardInput,
    ListProjectsInput,
    MoveTaskInput,
    PlanDayInput,
    ResponseFormat,
    SearchAllTasksInput,
    SearchTasksInput,
    UpdateProjectInput,
    UpdateTaskInput,
    WeeklyReviewInput,
)
from ticktick_mcp.queries import (
    filter_by_tags,
    filter_completed_since,
    filter_due_today,
    filter_due_this_week,
    filter_engaged,
    filter_overdue_tasks,
    group_by_horizon,
    parse_date,
    search_tasks,
    sort_by_priority_then_date,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan — shared OAuth client
# ---------------------------------------------------------------------------

@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[dict]:
    """Create the TickTick API client at startup, close it on shutdown.

    A single OAuth (bearer-token) client is reused across all tool calls.
    """
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
        "project IDs, then use other tools with those IDs. "
        "Smart query tools (due_today, overdue, engaged, search_all, plan_day) "
        "work across ALL projects automatically. "
        "ticktick_launch_dashboard rolls up tasks across a chosen set of lists "
        "by due state, optionally filtered by tag. Tags are applied and read "
        "through the task body on ticktick_create_task / ticktick_update_task."
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
async def ticktick_list_projects(params: ListProjectsInput, ctx: Context) -> str:
    """List all TickTick projects/lists for the authenticated user.

    Returns project names, IDs, colors, and view modes. Use this first
    to discover project IDs needed by other tools.

    Args:
        params: Contains response_format ('markdown' or 'json').

    Returns:
        Markdown-formatted project list, or JSON array of project objects.

    Examples:
        - "Show me all my TickTick lists" -> call with default params
        - "Get my projects as JSON" -> call with response_format="json"
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
async def ticktick_get_project(params: GetProjectInput, ctx: Context) -> str:
    """Get a TickTick project and all its tasks.

    Returns the project metadata plus every task in the project,
    including subtasks, priorities, dates, and tags.

    Args:
        params: Contains project_id and response_format.

    Returns:
        Markdown or JSON with project info and task list.

    Examples:
        - "Show me everything in my Work project" -> call with project_id
        - "Get tasks in list 696d539b..." -> call with that project_id
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
async def ticktick_create_project(params: CreateProjectInput, ctx: Context) -> str:
    """Create a new TickTick project/list.

    Args:
        params: Contains name (required), plus optional color, view_mode, kind.

    Returns:
        Markdown or JSON with the created project's details including its new ID.

    Examples:
        - "Create a project called Groceries" -> name="Groceries"
        - "Make a kanban board for Sprint 3" -> name="Sprint 3", view_mode="kanban"
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
async def ticktick_update_project(params: UpdateProjectInput, ctx: Context) -> str:
    """Update an existing TickTick project's properties.

    Only the fields you provide will be changed; others remain untouched.

    Args:
        params: Contains project_id (required) and optional name, color, view_mode, kind, sort_order.

    Returns:
        Markdown showing the updated project.

    Examples:
        - "Rename my project to 'Q2 Goals'" -> project_id=..., name="Q2 Goals"
        - "Change the color to red" -> project_id=..., color="#FF0000"
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
async def ticktick_delete_project(params: DeleteProjectInput, ctx: Context) -> str:
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
async def ticktick_get_task(params: GetTaskInput, ctx: Context) -> str:
    """Get a single TickTick task by its project ID and task ID.

    Returns full task details including title, content, priority,
    dates, tags, and subtasks.

    Args:
        params: Contains project_id, task_id, and response_format.

    Returns:
        Markdown or JSON with complete task details.

    Examples:
        - "Show me task abc123 in project 696d..." -> project_id, task_id
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
async def ticktick_search_tasks(params: SearchTasksInput, ctx: Context) -> str:
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
        - "Find tasks about 'voiceover' in project X" -> project_id=X, query="voiceover"
        - "Show high-priority tasks" -> project_id=X, priority=5
        - "List all tasks including completed" -> include_completed=True
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
async def ticktick_create_task(params: CreateTaskInput, ctx: Context) -> str:
    """Create a new task in a TickTick project.

    Supports all task properties: title, content, priority, dates,
    tags, subtasks, recurrence, and reminders.

    Args:
        params: Contains title and project_id (required), plus many optional fields.

    Returns:
        Markdown showing the created task with its new ID.

    Examples:
        - "Add 'Buy milk' to my Groceries list" -> title="Buy milk", project_id=...
        - "Create a high-priority task due tomorrow" -> title=..., priority=5, due_date=...
        - "Add a task with subtasks" -> title=..., subtasks=[{title: "Step 1"}, ...]
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
async def ticktick_update_task(params: UpdateTaskInput, ctx: Context) -> str:
    """Update an existing TickTick task.

    Only the fields you provide will be changed. You must always provide
    both task_id and project_id.

    Args:
        params: Contains task_id and project_id (required), plus optional fields to update.

    Returns:
        Markdown showing the updated task.

    Examples:
        - "Change the title to 'Revised script'" -> task_id=..., project_id=..., title="Revised script"
        - "Set priority to high" -> task_id=..., project_id=..., priority=5
        - "Add a due date" -> task_id=..., project_id=..., due_date="2026-03-15T09:00:00+0000"
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
async def ticktick_complete_task(params: CompleteTaskInput, ctx: Context) -> str:
    """Mark a TickTick task as completed.

    Args:
        params: Contains project_id and task_id.

    Returns:
        Confirmation message.

    Examples:
        - "Mark task abc123 as done" -> project_id=..., task_id="abc123"
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
async def ticktick_delete_task(params: DeleteTaskInput, ctx: Context) -> str:
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
async def ticktick_batch_create_tasks(params: BatchCreateTasksInput, ctx: Context) -> str:
    """Create multiple TickTick tasks at once in a single API call.

    All tasks are created in the same project. More efficient than
    creating tasks one by one when you have several to add.

    Args:
        params: Contains project_id and a list of task definitions (max 50).

    Returns:
        Summary of created tasks.

    Examples:
        - "Add these 5 tasks to my Sprint list" -> project_id=..., tasks=[...]
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
async def ticktick_move_task(params: MoveTaskInput, ctx: Context) -> str:
    """Move a task from one project to another.

    Thin wrapper over the batch move: submits a single move and verifies the
    task actually landed in the destination project, rather than reporting a
    silent success if the API ignored the change.

    Args:
        params: Contains task_id, from_project_id, and to_project_id.

    Returns:
        Confirmation with the task's new location, or a clear error if the
        move did not take effect.

    Examples:
        - "Move task abc123 from Inbox to Work" -> task_id, from_project_id, to_project_id
    """
    try:
        client = _get_client(ctx)
        results = await client.move_tasks([{
            "taskId": params.task_id,
            "fromProjectId": params.from_project_id,
            "toProjectId": params.to_project_id,
        }])
        r = results[0]
        if not r.get("moved"):
            return (
                f"Error: failed to move task `{params.task_id}` — "
                f"{r.get('error', 'unknown reason')}"
            )
        title = r.get("title") or params.task_id
        return f"Task '{title}' moved from project `{params.from_project_id}` to `{params.to_project_id}`."
    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="ticktick_batch_move",
    annotations={
        "title": "Batch Move TickTick Tasks",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def ticktick_batch_move(params: BatchMoveInput, ctx: Context) -> str:
    """Move multiple tasks between projects in one call (max 50).

    Uses the dedicated batch-move endpoint when available, otherwise falls
    back to a per-task move that verifies each task landed in its destination
    project. Any move that did not take effect is reported instead of being
    reported as a silent success.

    Args:
        params: Contains a list of moves (task_id, from_project_id, to_project_id).

    Returns:
        Summary of moved tasks, with any failures called out.

    Examples:
        - "Move these 5 blockers from Backlog to Sprint" -> moves=[...]
    """
    try:
        client = _get_client(ctx)
        moves = [
            {
                "taskId": m.task_id,
                "fromProjectId": m.from_project_id,
                "toProjectId": m.to_project_id,
            }
            for m in params.moves
        ]
        results = await client.move_tasks(moves)
        if params.response_format == ResponseFormat.JSON:
            return truncate_response(format_json({"count": len(results), "moves": results}))

        moved = [r for r in results if r.get("moved")]
        failed = [r for r in results if not r.get("moved")]
        lines = [f"# Batch Move — {len(moved)}/{len(results)} moved"]
        for r in moved:
            title = r.get("title") or r.get("taskId", "?")
            lines.append(f"- {title} → `{r.get('toProjectId', '?')}`")
        if failed:
            lines.append("")
            lines.append(f"## Failed ({len(failed)})")
            for r in failed:
                lines.append(
                    f"- `{r.get('taskId', '?')}` — {r.get('error', 'unknown reason')}"
                )
        return truncate_response("\n".join(lines))
    except Exception as e:
        return _handle_error(e)


# ===================================================================
# SMART QUERY TOOLS (cross-project)
# ===================================================================


async def _fetch_all_tasks(ctx) -> tuple[list[dict], dict[str, str]]:
    """Fetch all tasks from all open projects. Returns (tasks, project_name_map)."""
    client = _get_client(ctx)
    projects = await client.get_projects()
    all_tasks = []
    name_map = {}
    for p in projects:
        if p.get("closed"):
            continue
        pid = p["id"]
        name_map[pid] = p.get("name", "Unknown")
        data = await client.get_project_with_data(pid)
        tasks = data.get("tasks", [])
        for t in tasks:
            t["_project_name"] = p.get("name", "Unknown")
        all_tasks.extend(tasks)
    return all_tasks, name_map


@mcp.tool(
    name="ticktick_get_tasks_due_today",
    annotations={"title": "Tasks Due Today", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
)
async def ticktick_get_tasks_due_today(params: GetTasksDueTodayInput, ctx: Context) -> str:
    """Get all tasks due today across every open project.

    Zero-parameter convenience tool. Returns tasks sorted by priority.
    """
    try:
        all_tasks, _ = await _fetch_all_tasks(ctx)
        due_today = filter_due_today(all_tasks)
        if params.response_format == ResponseFormat.JSON:
            return truncate_response(format_json({"count": len(due_today), "tasks": due_today}))
        return truncate_response(format_tasks_md(due_today, "Due Today"))
    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="ticktick_get_overdue_tasks",
    annotations={"title": "Overdue Tasks", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
)
async def ticktick_get_overdue_tasks(params: GetOverdueTasksInput, ctx: Context) -> str:
    """Get all overdue tasks across every open project, sorted by priority then age.

    Useful for morning reviews and identifying what needs immediate attention.
    """
    try:
        all_tasks, _ = await _fetch_all_tasks(ctx)
        overdue = filter_overdue_tasks(all_tasks)
        if params.response_format == ResponseFormat.JSON:
            return truncate_response(format_json({"count": len(overdue), "tasks": overdue}))
        return truncate_response(format_tasks_md(overdue, "Overdue"))
    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="ticktick_get_engaged_tasks",
    annotations={"title": "Engaged Tasks (GTD)", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
)
async def ticktick_get_engaged_tasks(params: GetEngagedTasksInput, ctx: Context) -> str:
    """GTD 'Engaged' list: tasks that are high priority OR overdue.

    These are the tasks you should be actively working on right now.
    """
    try:
        all_tasks, _ = await _fetch_all_tasks(ctx)
        engaged = filter_engaged(all_tasks)
        if params.response_format == ResponseFormat.JSON:
            return truncate_response(format_json({"count": len(engaged), "tasks": engaged}))
        return truncate_response(format_tasks_md(engaged, "Engaged (Do Now)"))
    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="ticktick_search_all_tasks",
    annotations={"title": "Search All Tasks", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
)
async def ticktick_search_all_tasks(params: SearchAllTasksInput, ctx: Context) -> str:
    """Search for tasks across ALL open projects by title or content.

    Unlike ticktick_search_tasks which requires a project_id, this searches everywhere.
    """
    try:
        all_tasks, _ = await _fetch_all_tasks(ctx)
        if not params.include_completed:
            all_tasks = [t for t in all_tasks if t.get("status", 0) != 2]
        matches = search_tasks(all_tasks, params.query)
        if params.priority is not None:
            matches = [t for t in matches if t.get("priority", 0) == params.priority.value]
        if params.response_format == ResponseFormat.JSON:
            return truncate_response(format_json({"count": len(matches), "query": params.query, "tasks": matches}))
        return truncate_response(format_tasks_md(matches, f"Search: '{params.query}'"))
    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="ticktick_plan_day",
    annotations={"title": "Plan My Day", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
)
async def ticktick_plan_day(params: PlanDayInput, ctx: Context) -> str:
    """Help structure your day from your task list.

    Pulls overdue + due today + high priority tasks, estimates time using
    pomo estimates (default 25 min per task), and suggests a sequenced plan
    that fits within your available hours. Flags if over-committed.
    """
    try:
        all_tasks, _ = await _fetch_all_tasks(ctx)
        overdue = filter_overdue_tasks(all_tasks)
        due_today_tasks = filter_due_today(all_tasks)
        high_pri = [t for t in all_tasks if t.get("priority", 0) >= 5 and t.get("status", 0) != 2]

        # Deduplicate (a task can be both overdue and high priority)
        seen = set()
        candidates = []
        for t in overdue + due_today_tasks + high_pri:
            tid = t.get("id")
            if tid not in seen:
                seen.add(tid)
                candidates.append(t)

        candidates = sort_by_priority_then_date(candidates)

        # Estimate time: default 25 min per task unless pomo estimate exists
        total_minutes = 0
        plan_lines = []
        available_minutes = params.available_hours * 60

        for t in candidates:
            est_pomos = t.get("estimatedPomo", 1) or 1
            est_minutes = est_pomos * 25
            total_minutes += est_minutes

            icon = "🔴" if t.get("priority", 0) >= 5 else "🟡" if t.get("priority", 0) >= 3 else "⚪"
            project = t.get("_project_name", "")
            over = " -- OVER BUDGET" if total_minutes > available_minutes else ""
            plan_lines.append(
                f"{icon} {t.get('title', '?')} -- {project} ({est_minutes}min){over}"
            )

        header = f"# Day Plan ({params.available_hours}h available)\n\n"
        header += f"**Tasks:** {len(candidates)} | **Estimated:** {total_minutes}min ({total_minutes/60:.1f}h)\n"
        if total_minutes > available_minutes:
            over_by = (total_minutes - available_minutes) / 60
            header += f"**Over-committed by {over_by:.1f}h** -- consider deferring lower-priority items\n"
        else:
            slack = (available_minutes - total_minutes) / 60
            header += f"**{slack:.1f}h slack** -- room for unexpected work\n"

        header += "\n## Suggested Sequence\n\n"
        body = "\n".join(f"{i+1}. {line}" for i, line in enumerate(plan_lines))

        return truncate_response(header + body)
    except Exception as e:
        return _handle_error(e)


# ===================================================================
# DAILY STANDUP & REVIEW TOOLS
# ===================================================================


@mcp.tool(
    name="ticktick_daily_standup",
    annotations={"title": "Daily Standup Briefing", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
)
async def ticktick_daily_standup(params: DailyStandupInput, ctx: Context) -> str:
    """Morning briefing: overdue tasks, due today, completed yesterday, and this week's horizon.

    Zero-parameter tool. Call this every morning for a structured view
    of what needs attention, what's coming, and what you accomplished.
    """
    try:
        all_tasks, _ = await _fetch_all_tasks(ctx)
        now = datetime.now(timezone.utc)
        yesterday = now - timedelta(days=1)

        overdue = filter_overdue_tasks(all_tasks)
        due_today_tasks = filter_due_today(all_tasks)
        completed_yesterday = filter_completed_since(all_tasks, yesterday.replace(hour=0, minute=0, second=0))
        coming_this_week = filter_due_this_week(all_tasks)

        sections = []
        sections.append(f"# Daily Standup -- {now.strftime('%A, %B %d, %Y')}\n")

        # Overdue
        sections.append(f"## OVERDUE ({len(overdue)} tasks)")
        if overdue:
            for t in overdue[:10]:
                icon = "🔴" if t.get("priority", 0) >= 5 else "🟡" if t.get("priority", 0) >= 3 else "⚪"
                project = t.get("_project_name", "")
                due = t.get("dueDate", "")[:10] if t.get("dueDate") else "no date"
                sections.append(f"  - {icon} **{t.get('title', '?')}** -- {project} (due {due})")
        else:
            sections.append("  None -- you're caught up!")

        # Due Today
        sections.append(f"\n## DUE TODAY ({len(due_today_tasks)} tasks)")
        if due_today_tasks:
            for t in due_today_tasks[:10]:
                icon = "🔴" if t.get("priority", 0) >= 5 else "🟡" if t.get("priority", 0) >= 3 else "⚪"
                project = t.get("_project_name", "")
                sections.append(f"  - {icon} {t.get('title', '?')} -- {project}")
        else:
            sections.append("  Nothing due today.")

        # Completed Yesterday
        sections.append(f"\n## COMPLETED YESTERDAY ({len(completed_yesterday)} tasks)")
        if completed_yesterday:
            for t in completed_yesterday[:10]:
                project = t.get("_project_name", "")
                sections.append(f"  - {t.get('title', '?')} -- {project}")
        else:
            sections.append("  No completions yesterday.")

        # Coming This Week
        sections.append(f"\n## COMING THIS WEEK ({len(coming_this_week)} tasks)")
        if coming_this_week:
            for t in coming_this_week[:10]:
                due = t.get("dueDate", "")[:10] if t.get("dueDate") else ""
                project = t.get("_project_name", "")
                sections.append(f"  - {t.get('title', '?')} -- {project} ({due})")
        else:
            sections.append("  Clear week ahead.")

        return truncate_response("\n".join(sections))
    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="ticktick_weekly_review",
    annotations={"title": "Weekly Review", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
)
async def ticktick_weekly_review(params: WeeklyReviewInput, ctx: Context) -> str:
    """End-of-week analysis: completed vs planned, overdue trends, project breakdown.

    Shows what you accomplished, where you fell behind, and how the week compared.
    """
    try:
        all_tasks, name_map = await _fetch_all_tasks(ctx)
        now = datetime.now(timezone.utc)

        # Calculate week boundaries
        days_offset = params.week_offset * 7
        week_start = (now + timedelta(days=days_offset)).replace(hour=0, minute=0, second=0, microsecond=0)
        # Go to Monday of that week
        week_start -= timedelta(days=week_start.weekday())
        week_end = week_start + timedelta(days=7)

        completed_this_week = filter_completed_since(all_tasks, week_start)
        completed_this_week = [t for t in completed_this_week
                               if parse_date(t.get("completedTime", "")) is None
                               or parse_date(t.get("completedTime", "")) < week_end]
        overdue = filter_overdue_tasks(all_tasks)

        # Group completed by project
        by_project: dict[str, int] = {}
        for t in completed_this_week:
            pname = t.get("_project_name", name_map.get(t.get("projectId", ""), "Other"))
            by_project[pname] = by_project.get(pname, 0) + 1

        sections = []
        week_label = "This Week" if params.week_offset == 0 else f"Week of {week_start.strftime('%B %d')}"
        sections.append(f"# Weekly Review -- {week_label}\n")

        sections.append("## Summary")
        sections.append(f"- **Completed:** {len(completed_this_week)} tasks")
        sections.append(f"- **Currently Overdue:** {len(overdue)} tasks")

        sections.append("\n## Completed by Project")
        for pname, count in sorted(by_project.items(), key=lambda x: -x[1]):
            sections.append(f"  - {pname}: {count} tasks")

        if overdue:
            sections.append(f"\n## Still Overdue ({len(overdue)})")
            for t in overdue[:10]:
                icon = "🔴" if t.get("priority", 0) >= 5 else "🟡"
                due = t.get("dueDate", "")[:10] if t.get("dueDate") else ""
                sections.append(f"  - {icon} {t.get('title', '?')} (due {due})")

        return truncate_response("\n".join(sections))
    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="ticktick_launch_dashboard",
    annotations={
        "title": "Launch Dashboard (Cross-List Rollup)",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def ticktick_launch_dashboard(params: LaunchDashboardInput, ctx: Context) -> str:
    """Cross-list status rollup for a set of projects (your products).

    Groups matching tasks by due state: overdue, today, this week, later,
    no date. Use for launch tracking, e.g. "show everything tagged blocker
    across my product lists". Fetches only the requested projects, so it
    stays cheap even with many lists.

    Args:
        params: project_ids (required), optional tags + match ('any'/'all'),
                include_completed_today, and response_format.

    Returns:
        Markdown dashboard grouped by due state, or JSON buckets.

    Examples:
        - "Blocker status across these 4 lists" -> project_ids=[...], tags=["blocker"]
        - "Everything launch-tagged, all must match" -> tags=["launch","p0"], match="all"
    """
    try:
        client = _get_client(ctx)
        projects = {p["id"]: p for p in await client.get_projects()}

        all_tasks: list[dict] = []
        for pid in params.project_ids:
            data = await client.get_project_with_data(pid)
            project_name = projects.get(pid, {}).get("name", pid)
            for task in data.get("tasks", []):
                task["_project_name"] = project_name
                all_tasks.append(task)

        tagged = filter_by_tags(all_tasks, params.tags or [], params.match)
        buckets = group_by_horizon(tagged)

        if params.include_completed_today:
            midnight = datetime.now(timezone.utc).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            buckets["done_today"] = filter_completed_since(all_tasks, midnight)

        if params.response_format == ResponseFormat.JSON:
            return truncate_response(format_json(buckets))
        return format_dashboard_md(buckets, params.tags, projects)
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
