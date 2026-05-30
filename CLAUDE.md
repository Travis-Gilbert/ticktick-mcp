# TickTick MCP — General-Purpose Task Management Server

## Project Overview

Standalone MCP server for the TickTick Open API v1. Provides 22 tools for project and task management in Claude Desktop, Claude Code, and remotely over Streamable HTTP (Railway). Replaces the NPX `@alexarevalo.ai/mcp-server-ticktick` package.

**Tech Stack:** Python, FastMCP, httpx, Pydantic

## Development Commands

```bash
# Install dependencies
cd "/Users/travisgilbert/Tech Dev Local/ticktick-mcp" && uv sync

# Run server (stdio transport — same as Claude Desktop uses)
MCP_TRANSPORT=stdio uv run python -m ticktick_mcp

# Verify tools register correctly
uv run python -c "
from ticktick_mcp.server import mcp
tools = mcp._tool_manager._tools
print(f'{len(tools)} tools:')
for name in sorted(tools): print(f'  {name}')
"

# Run tests
uv run pytest
```

## Architecture

```
ticktick_mcp/
├── __init__.py        # Package marker
├── __main__.py        # Entry: mcp.run(transport=...) — defaults to streamable-http
├── server.py          # FastMCP server + 22 tool definitions
├── client.py          # Async httpx TickTick API client (lifespan-managed)
├── models.py          # Pydantic input models for all tools
├── queries.py         # Pure cross-project filter/grouping helpers (no I/O)
└── formatting.py      # Markdown/JSON response helpers + truncation
```

## Key Files

| File | Purpose |
|------|---------|
| `server.py` | All 22 tools, lifespan setup, error handler |
| `client.py` | `TickTickClient` — wraps TickTick Open API v1 (incl. `move_tasks`) |
| `models.py` | Pydantic BaseModels for every tool's input |
| `queries.py` | `filter_*`, `group_by_horizon`, `filter_by_tags`, `sort_by_priority_then_date` |
| `formatting.py` | `format_task_md()`, `format_dashboard_md()`, `truncate_response()` |

## Tools (22)

### Projects (5)

| Tool | Type | Annotation |
|------|------|------------|
| `ticktick_list_projects` | read | readOnly |
| `ticktick_get_project` | read | readOnly |
| `ticktick_create_project` | write | — |
| `ticktick_update_project` | write | idempotent |
| `ticktick_delete_project` | write | destructive |

### Tasks (9)

| Tool | Type | Annotation |
|------|------|------------|
| `ticktick_get_task` | read | readOnly |
| `ticktick_search_tasks` | read | readOnly (local filter) |
| `ticktick_create_task` | write | — |
| `ticktick_update_task` | write | idempotent |
| `ticktick_complete_task` | write | idempotent |
| `ticktick_delete_task` | write | destructive |
| `ticktick_batch_create_tasks` | write | — |
| `ticktick_move_task` | write | idempotent (verified) |
| `ticktick_batch_move` | write | idempotent (verified) |

### Smart queries — cross-project (5)

| Tool | Type | Annotation |
|------|------|------------|
| `ticktick_get_tasks_due_today` | read | readOnly |
| `ticktick_get_overdue_tasks` | read | readOnly |
| `ticktick_get_engaged_tasks` | read | readOnly |
| `ticktick_search_all_tasks` | read | readOnly |
| `ticktick_plan_day` | read | readOnly |

### Standup / review / dashboard (3)

| Tool | Type | Annotation |
|------|------|------------|
| `ticktick_daily_standup` | read | readOnly |
| `ticktick_weekly_review` | read | readOnly |
| `ticktick_launch_dashboard` | read | readOnly |

## API Coverage

Base URL: `https://api.ticktick.com/open/v1`

| Endpoint | Method | Tool |
|----------|--------|------|
| `/project` | GET | `ticktick_list_projects`, smart queries, `ticktick_launch_dashboard` |
| `/project/{id}` | GET | `ticktick_get_project` (metadata) |
| `/project/{id}/data` | GET | `ticktick_get_project`, `ticktick_search_tasks`, smart queries, standup/review, `ticktick_launch_dashboard` |
| `/project/{id}` | POST | `ticktick_create_project` |
| `/project/{id}` | PUT | `ticktick_update_project` |
| `/project/{id}` | DELETE | `ticktick_delete_project` |
| `/project/{pid}/task/{tid}` | GET | `ticktick_get_task` |
| `/task` | POST | `ticktick_create_task` |
| `/task/{id}` | POST | `ticktick_update_task` (+ move fallback) |
| `/project/{pid}/task/{tid}/complete` | POST | `ticktick_complete_task` |
| `/task/{pid}/{tid}` | DELETE | `ticktick_delete_task` |
| `/batch/task` | POST | `ticktick_batch_create_tasks` |
| `/project/task/move` | POST | `ticktick_move_task`, `ticktick_batch_move` (dedicated path; see Gotchas) |

## Auth

Bearer token via `TICKTICK_ACCESS_TOKEN` env var (OAuth only — no username/password). Credentials are passed through Claude Desktop's `env` config (not a `.env` file). Get tokens at https://developer.ticktick.com.

Tags are pure OAuth: applied through the `tags` list on `ticktick_create_task` / `ticktick_update_task` and read off the `tags` field of returned tasks. Renaming or deleting a tag *definition* in bulk is not supported (do it in the app).

## Claude Desktop Config

```json
{
  "ticktick": {
    "command": "/Users/travisgilbert/.local/bin/uv",
    "args": ["run", "--directory", "/Users/travisgilbert/Tech Dev Local/ticktick-mcp", "python", "-m", "ticktick_mcp"],
    "env": { "TICKTICK_ACCESS_TOKEN": "...", "MCP_TRANSPORT": "stdio" }
  }
}
```

## Gotchas

- **`--directory` path has spaces** — always quote it.
- **`MCP_TRANSPORT` defaults to `streamable-http`** (for Railway). Set `MCP_TRANSPORT=stdio` for Claude Desktop.
- **No `from __future__ import annotations` in `server.py`** — pydantic 2.12 + FastMCP cannot resolve stringized tool-parameter annotations during schema generation, so the future import makes every tool fail to register. Tool-param annotations must stay as real objects.
- **TickTick API has no search endpoint** — `ticktick_search_tasks` / `ticktick_search_all_tasks` fetch tasks then filter locally.
- **Move is verified** — `ticktick_move_task` / `ticktick_batch_move` call `client.move_tasks`, which tries the dedicated `/project/task/move` endpoint and, if it's unavailable (4xx), falls back to per-task `get` → `update(projectId)` → re-read to confirm the move took. A silent no-op is reported as a failure, never as success.
- **FastMCP tool introspection** — tools are `FunctionTool` objects; access `.fn` for direct testing.
- **CHARACTER_LIMIT = 25,000** — responses are truncated with a notice if they exceed this.
- **Batch limits = 50** — `ticktick_batch_create_tasks` and `ticktick_batch_move` cap at 50 (Pydantic `max_length`).
- **Duplicate `server.py` at repo root** — a byte-identical copy of `ticktick_mcp/server.py` lives at the repo root from an upload commit. The Dockerfile copies only `ticktick_mcp/`, so the root copy is not deployed; it is kept in sync to avoid drift and could be removed.

## Relationship to Orchestra MCP

This is a **standalone, general-purpose** TickTick MCP. The Orchestra MCP (`orchestra_ticktick/`) adds production-specific semantics on top (🎬 naming, P0-P7 phases, priority encoding). They share the same TickTick API credentials but are separate codebases.

## Recent Decisions

| Decision | Why | Date |
|----------|-----|------|
| Retired the V2 surface (focus, habits, productivity, tag-admin) | Needed username/password and added nothing to task/project management; tags survive on the OAuth task body | 2026-05-30 |
| Added `ticktick_launch_dashboard` | Cross-list tag + due-state rollup — the one capability the tool set lacked | 2026-05-30 |
| Hardened move into `ticktick_batch_move` with verified fallback | Open API may silently ignore a `projectId` change on update; dedicated endpoint tried first, then per-task update + re-read verification | 2026-05-30 |
| Removed `from __future__ import annotations` from `server.py` | pydantic 2.12 + FastMCP schema-gen cannot resolve stringized tool-param annotations → all tools failed to register | 2026-05-30 |
| Standalone project (not inside Orchestra) | Reusable for any TickTick use case, not just video production | 2026-02-13 |
| Replaces NPX `@alexarevalo.ai/mcp-server-ticktick` | NPX downloads fresh copy every launch; local Python is deterministic | 2026-02-13 |
| Lifespan-managed httpx client | Single connection reused across all tool calls; no leaks | 2026-02-13 |
| Pydantic `extra="forbid"` | Catches LLM typos in field names immediately | 2026-02-13 |
