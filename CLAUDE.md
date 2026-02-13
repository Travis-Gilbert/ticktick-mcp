# TickTick MCP — General-Purpose Task Management Server

## Project Overview

Standalone MCP server for the TickTick Open API v1. Provides 13 tools for project and task management in Claude Desktop and Claude Code. Replaces the NPX `@alexarevalo.ai/mcp-server-ticktick` package.

**Tech Stack:** Python, FastMCP, httpx, Pydantic

## Development Commands

```bash
# Install dependencies
cd "ticktick-mcp" && uv sync

# Run server (stdio transport — same as Claude Desktop uses)
uv run --directory "/Users/travisgilbert/Library/Mobile Documents/com~apple~CloudDocs/Tech Dev/ticktick-mcp" python -m ticktick_mcp

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
├── __main__.py        # Entry: mcp.run(transport="stdio")
├── server.py          # FastMCP server + 13 tool definitions
├── client.py          # Async httpx TickTick API client (lifespan-managed)
├── models.py          # Pydantic input models for all tools
└── formatting.py      # Markdown/JSON response helpers + truncation
```

## Key Files

| File | Purpose |
|------|---------|
| `server.py` | All 13 tools, lifespan setup, error handler |
| `client.py` | `TickTickClient` — wraps TickTick Open API v1 |
| `models.py` | Pydantic BaseModels for every tool's input |
| `formatting.py` | `format_task_md()`, `format_projects_md()`, `truncate_response()` |

## Tools (13)

| Tool | Type | Annotation |
|------|------|------------|
| `ticktick_list_projects` | read | readOnly |
| `ticktick_get_project` | read | readOnly |
| `ticktick_create_project` | write | — |
| `ticktick_update_project` | write | idempotent |
| `ticktick_delete_project` | write | destructive |
| `ticktick_get_task` | read | readOnly |
| `ticktick_search_tasks` | read | readOnly (local filter) |
| `ticktick_create_task` | write | — |
| `ticktick_update_task` | write | idempotent |
| `ticktick_complete_task` | write | idempotent |
| `ticktick_delete_task` | write | destructive |
| `ticktick_batch_create_tasks` | write | — |
| `ticktick_move_task` | write | idempotent |

## API Coverage

Base URL: `https://api.ticktick.com/open/v1`

| Endpoint | Method | Tool |
|----------|--------|------|
| `/project` | GET | `ticktick_list_projects` |
| `/project/{id}/data` | GET | `ticktick_get_project`, `ticktick_search_tasks` |
| `/project/{id}` | POST | `ticktick_create_project` |
| `/project/{id}` | PUT | `ticktick_update_project` |
| `/project/{id}` | DELETE | `ticktick_delete_project` |
| `/project/{pid}/task/{tid}` | GET | `ticktick_get_task` |
| `/task` | POST | `ticktick_create_task` |
| `/task/{id}` | POST | `ticktick_update_task`, `ticktick_move_task` |
| `/project/{pid}/task/{tid}/complete` | POST | `ticktick_complete_task` |
| `/task/{pid}/{tid}` | DELETE | `ticktick_delete_task` |
| `/batch/task` | POST | `ticktick_batch_create_tasks` |

## Auth

Bearer token via `TICKTICK_ACCESS_TOKEN` env var. Credentials are passed through Claude Desktop's `env` config (not a `.env` file). Get tokens at https://developer.ticktick.com.

## Claude Desktop Config

```json
{
  "ticktick": {
    "command": "/Users/travisgilbert/.local/bin/uv",
    "args": ["run", "--directory", "/Users/travisgilbert/Library/Mobile Documents/com~apple~CloudDocs/Tech Dev/ticktick-mcp", "python", "-m", "ticktick_mcp"],
    "env": { "TICKTICK_ACCESS_TOKEN": "..." }
  }
}
```

## Gotchas

- **iCloud path has spaces** — always quote the `--directory` path
- **TickTick API has no search endpoint** — `ticktick_search_tasks` fetches all tasks then filters locally
- **`ticktick_move_task`** requires fetching the task first (GET then POST with new projectId)
- **FastMCP tool introspection** — tools are `FunctionTool` objects, access `.fn` for direct testing
- **CHARACTER_LIMIT = 25,000** — responses are truncated with a notice if they exceed this
- **Batch create max 50 tasks** — enforced by Pydantic `max_length` on the list

## Relationship to Orchestra MCP

This is a **standalone, general-purpose** TickTick MCP. The Orchestra MCP (`orchestra_ticktick/`) adds production-specific semantics on top (🎬 naming, P0-P7 phases, priority encoding). They share the same TickTick API credentials but are separate codebases.

## Recent Decisions

| Decision | Why | Date |
|----------|-----|------|
| Standalone project (not inside Orchestra) | Reusable for any TickTick use case, not just video production | 2026-02-13 |
| Replaces NPX `@alexarevalo.ai/mcp-server-ticktick` | NPX downloads fresh copy every launch; local Python is deterministic | 2026-02-13 |
| Lifespan-managed httpx client | Single connection reused across all tool calls; no leaks | 2026-02-13 |
| Pydantic `extra="forbid"` | Catches LLM typos in field names immediately | 2026-02-13 |
