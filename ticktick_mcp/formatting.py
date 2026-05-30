"""Response formatting helpers for TickTick MCP.

Provides consistent Markdown and JSON formatting across all tools.
Markdown is the default — optimized for LLM readability with minimal tokens.
"""

from __future__ import annotations

import json
from typing import Any

CHARACTER_LIMIT = 25_000

# ---------------------------------------------------------------------------
# Priority display
# ---------------------------------------------------------------------------

PRIORITY_LABELS = {
    0: "None",
    1: "Low",
    3: "Medium",
    5: "High",
}

PRIORITY_ICONS = {
    0: "",
    1: "🔵",
    3: "🟡",
    5: "🔴",
}


def priority_label(value: int) -> str:
    """Convert priority int to human label."""
    return PRIORITY_LABELS.get(value, f"Unknown({value})")


def priority_icon(value: int) -> str:
    """Convert priority int to emoji icon."""
    return PRIORITY_ICONS.get(value, "")


# ---------------------------------------------------------------------------
# Task status
# ---------------------------------------------------------------------------

def task_status_label(status: int) -> str:
    """Convert TickTick task status to label."""
    if status == 0:
        return "Active"
    if status == 2:
        return "Completed"
    return f"Status({status})"


# ---------------------------------------------------------------------------
# Markdown formatters
# ---------------------------------------------------------------------------

def format_project_md(project: dict) -> str:
    """Format a single project as Markdown."""
    lines = [f"## {project.get('name', 'Unnamed')}"]
    lines.append(f"- **ID**: `{project.get('id', '?')}`")
    if project.get("color"):
        lines.append(f"- **Color**: {project['color']}")
    if project.get("viewMode"):
        lines.append(f"- **View**: {project['viewMode']}")
    if project.get("kind"):
        lines.append(f"- **Kind**: {project['kind']}")
    return "\n".join(lines)


def format_projects_md(projects: list[dict]) -> str:
    """Format a list of projects as Markdown."""
    if not projects:
        return "No projects found."
    lines = [f"# Projects ({len(projects)})"]
    for p in projects:
        lines.append("")
        lines.append(format_project_md(p))
    return "\n".join(lines)


def format_task_md(task: dict) -> str:
    """Format a single task as Markdown."""
    title = task.get("title", "Untitled")
    pri = task.get("priority", 0)
    icon = priority_icon(pri)
    status = task_status_label(task.get("status", 0))

    lines = [f"## {icon} {title}".strip()]
    lines.append(f"- **ID**: `{task.get('id', '?')}`")
    lines.append(f"- **Project**: `{task.get('projectId', '?')}`")
    lines.append(f"- **Priority**: {priority_label(pri)}")
    lines.append(f"- **Status**: {status}")

    if task.get("content"):
        lines.append(f"- **Content**: {task['content'][:200]}")
    if task.get("dueDate"):
        lines.append(f"- **Due**: {task['dueDate']}")
    if task.get("startDate"):
        lines.append(f"- **Start**: {task['startDate']}")
    if task.get("tags"):
        lines.append(f"- **Tags**: {', '.join(task['tags'])}")
    if task.get("timeZone"):
        lines.append(f"- **Timezone**: {task['timeZone']}")

    items = task.get("items", [])
    if items:
        lines.append(f"- **Subtasks** ({len(items)}):")
        for item in items:
            check = "x" if item.get("status", 0) == 1 else " "
            lines.append(f"  - [{check}] {item.get('title', '?')}")

    return "\n".join(lines)


def format_tasks_md(tasks: list[dict], project_name: str = "") -> str:
    """Format a list of tasks as Markdown."""
    if not tasks:
        return "No tasks found."
    header = f"# Tasks in {project_name}" if project_name else f"# Tasks ({len(tasks)})"
    lines = [f"{header} ({len(tasks)})"]
    for t in tasks:
        lines.append("")
        lines.append(format_task_md(t))
    return "\n".join(lines)


# Ordered horizon buckets produced by queries.group_by_horizon, plus the
# optional done_today bucket appended by the launch dashboard tool.
DASHBOARD_BUCKET_TITLES = {
    "overdue": "Overdue",
    "today": "Due Today",
    "this_week": "This Week",
    "later": "Later",
    "no_date": "No Date",
    "done_today": "Done Today",
}


def format_dashboard_md(
    buckets: dict[str, list[dict]],
    tags: list[str] | None,
    projects: dict[str, dict],
) -> str:
    """Format the launch dashboard horizon buckets as Markdown.

    Each non-empty bucket becomes a section with a count; tasks render as
    priority dot + title + project name + due date. `projects` maps
    project_id -> project dict, used to resolve a task's list name when the
    tool did not stamp `_project_name`.
    """
    tag_label = f" — {', '.join(tags)}" if tags else ""
    total = sum(len(v) for v in buckets.values())
    lines = [f"# Launch Dashboard{tag_label}", f"_{total} matching task(s)_"]

    for key, title in DASHBOARD_BUCKET_TITLES.items():
        items = buckets.get(key)
        if not items:
            continue
        lines.append("")
        lines.append(f"## {title} ({len(items)})")
        for t in items:
            icon = priority_icon(t.get("priority", 0)) or "⚪"
            name = t.get("_project_name") or projects.get(t.get("projectId", ""), {}).get("name", "")
            due = t.get("dueDate", "")[:10] if t.get("dueDate") else ""
            suffix = " — " + " · ".join(p for p in (name, due) if p) if (name or due) else ""
            lines.append(f"- {icon} {t.get('title', '?')}{suffix}")

    if total == 0:
        lines.append("")
        lines.append("No matching tasks.")

    return truncate_response("\n".join(lines))


# ---------------------------------------------------------------------------
# JSON formatter
# ---------------------------------------------------------------------------

def format_json(data: Any) -> str:
    """Format data as indented JSON string."""
    return json.dumps(data, indent=2, ensure_ascii=False, default=str)


# ---------------------------------------------------------------------------
# Truncation
# ---------------------------------------------------------------------------

def truncate_response(response: str) -> str:
    """Truncate response if it exceeds CHARACTER_LIMIT."""
    if len(response) <= CHARACTER_LIMIT:
        return response
    truncated = response[:CHARACTER_LIMIT]
    return (
        truncated
        + "\n\n---\n"
        + f"**Response truncated** ({len(response):,} chars → {CHARACTER_LIMIT:,} chars). "
        + "Use filters or pagination to reduce results."
    )
