# TickTick MCP Enhancement Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Extend the TickTick MCP server from 13 V1-only tools to ~30 tools covering daily standup, smart queries, focus stats, habits, tags, and productivity analytics — all accessible from Claude on any device via Replit SSE.

**Architecture:** Add a V2 API client (`v2_client.py`) alongside the existing V1 client. V2 uses session-based auth (username/password → cookie token) for endpoints not covered by V1 OAuth. The server detects whether V2 credentials are available and gracefully degrades V2-dependent tools. New tools are organized into feature modules but registered on the same FastMCP server instance.

**Tech Stack:** Python 3.12, FastMCP 2.14.5, httpx (shared for both V1/V2), Pydantic 2.0, python-dotenv

---

## Overview

| Phase | Feature | New Tools | Depends On |
|-------|---------|-----------|------------|
| 1 | V2 Client Foundation | 0 (infrastructure) | — |
| 2 | Smart Query Tools | 5 | V1 only |
| 3 | Daily Standup & Review | 3 | V1 + Phase 2 helpers |
| 4 | Focus/Pomodoro Stats (read-only) | 4 | V2 client |
| 5 | Habit Tracking | 3 | V2 client |
| 6 | Tag Management & Productivity | 3 | V2 client |

**Total new tools:** ~18 (bringing server from 13 → ~31)

---

## Phase 1: V2 Client Foundation

### Task 1.1: Add V2 Client Module

**Files:**
- Create: `ticktick_mcp/v2_client.py`
- Create: `tests/test_v2_client.py`

**Step 1: Write the failing test**

```python
# tests/test_v2_client.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from ticktick_mcp.v2_client import TickTickV2Client, V2AuthError


@pytest.mark.asyncio
async def test_v2_client_requires_credentials():
    """V2 client raises ValueError if username/password missing."""
    with pytest.raises(ValueError, match="TICKTICK_USERNAME"):
        TickTickV2Client(username="", password="test")


@pytest.mark.asyncio
async def test_v2_client_signon_sets_token():
    """V2 client signon extracts token from response."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"token": "fake-session-token"}
    mock_response.cookies = {"t": "fake-session-token"}

    with patch("ticktick_mcp.v2_client.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value
        instance.post = AsyncMock(return_value=mock_response)
        instance.aclose = AsyncMock()

        client = TickTickV2Client(username="user@test.com", password="pass123")
        await client.authenticate()

        assert client._token == "fake-session-token"
        assert client.is_authenticated


@pytest.mark.asyncio
async def test_v2_client_signon_failure_raises():
    """V2 client raises V2AuthError on 401."""
    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_response.text = "Unauthorized"

    with patch("ticktick_mcp.v2_client.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value
        instance.post = AsyncMock(return_value=mock_response)
        instance.aclose = AsyncMock()

        client = TickTickV2Client(username="user@test.com", password="wrong")
        with pytest.raises(V2AuthError, match="Authentication failed"):
            await client.authenticate()
```

**Step 2: Run test to verify it fails**

Run: `cd ticktick-mcp && uv run pytest tests/test_v2_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ticktick_mcp.v2_client'`

**Step 3: Write the V2 client**

```python
# ticktick_mcp/v2_client.py
"""Async TickTick V2 API client for undocumented endpoints.

Handles session-based auth (username/password) for features not covered
by the V1 OAuth API: focus stats, habits, tags, productivity scores.
"""

from __future__ import annotations

import os
import uuid

import httpx
from dotenv import load_dotenv

load_dotenv()

V2_BASE_URL = "https://ticktick.com/api/v2"
SIGNON_URL = f"{V2_BASE_URL}/user/signon"
REQUEST_TIMEOUT = 30.0


class V2AuthError(Exception):
    """Raised when V2 session authentication fails."""
    pass


class TickTickV2APIError(Exception):
    """Raised when the V2 API returns an error."""
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"TickTick V2 API error {status_code}: {detail}")


class TickTickV2Client:
    """Async client for TickTick's undocumented V2 API.

    Requires username/password auth (separate from V1 OAuth token).
    Session tokens are managed automatically with re-auth on expiry.
    """

    def __init__(
        self,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        self._username = username or os.getenv("TICKTICK_USERNAME", "")
        self._password = password or os.getenv("TICKTICK_PASSWORD", "")

        if not self._username:
            raise ValueError(
                "TICKTICK_USERNAME is required for V2 API features. "
                "Set it in your .env file or Replit Secrets."
            )
        if not self._password:
            raise ValueError(
                "TICKTICK_PASSWORD is required for V2 API features. "
                "Set it in your .env file or Replit Secrets."
            )

        self._token: str | None = None
        self._device_id = uuid.uuid4().hex[:24]
        self._http = httpx.AsyncClient(
            base_url=V2_BASE_URL,
            timeout=REQUEST_TIMEOUT,
        )

    @property
    def is_authenticated(self) -> bool:
        return self._token is not None

    async def authenticate(self) -> None:
        """Sign in to V2 API and store session token."""
        device_info = {
            "platform": "web",
            "os": "macOS 10.15",
            "device": "Chrome 120",
            "name": "",
            "version": 6430,
            "id": self._device_id,
            "channel": "website",
            "campaign": "",
        }

        response = await self._http.post(
            f"{V2_BASE_URL}/user/signon",
            params={"wc": "true", "remember": "true"},
            json={
                "username": self._username,
                "password": self._password,
            },
            headers={
                "User-Agent": "Mozilla/5.0",
                "X-Device": str(device_info).replace("'", '"'),
            },
        )

        if response.status_code != 200:
            raise V2AuthError(
                f"Authentication failed (HTTP {response.status_code}): {response.text}"
            )

        data = response.json()
        self._token = data.get("token") or response.cookies.get("t")

        if not self._token:
            raise V2AuthError("No token returned from signon response")

        # Update client headers with auth token
        self._http.headers["Authorization"] = f"Bearer {self._token}"
        self._http.cookies.set("t", self._token)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict | list | None = None,
        params: dict | None = None,
    ) -> dict | list | None:
        """Make an authenticated V2 API request. Re-auths on 401."""
        if not self.is_authenticated:
            await self.authenticate()

        response = await self._http.request(
            method, path, json=json_body, params=params,
        )

        # Re-authenticate on 401 and retry once
        if response.status_code == 401:
            await self.authenticate()
            response = await self._http.request(
                method, path, json=json_body, params=params,
            )

        if response.status_code >= 400:
            detail = response.text or f"HTTP {response.status_code}"
            raise TickTickV2APIError(response.status_code, detail)

        if response.status_code == 204 or not response.text:
            return None

        return response.json()

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._http.aclose()

    # ------------------------------------------------------------------
    # Focus / Pomodoro (read-only)
    # ------------------------------------------------------------------

    async def get_focus_heatmap(self, date_from: str, date_to: str) -> list[dict]:
        """GET /pomodoros/statistics/heatmap/{from}/{to}"""
        result = await self._request("GET", f"/pomodoros/statistics/heatmap/{date_from}/{date_to}")
        return result if isinstance(result, list) else []

    async def get_focus_distribution(self, date_from: str, date_to: str) -> list[dict]:
        """GET /pomodoros/statistics/dist/{from}/{to}"""
        result = await self._request("GET", f"/pomodoros/statistics/dist/{date_from}/{date_to}")
        return result if isinstance(result, list) else []

    async def get_general_statistics(self) -> dict:
        """GET /statistics/general — productivity scores, pomo totals, task counts."""
        result = await self._request("GET", "/statistics/general")
        return result if isinstance(result, dict) else {}

    # ------------------------------------------------------------------
    # Habits
    # ------------------------------------------------------------------

    async def get_habits(self) -> list[dict]:
        """GET /habits — list all habits."""
        result = await self._request("GET", "/habits")
        return result if isinstance(result, list) else []

    async def get_habit_checkins(self, habit_ids: list[str], after_stamp: int) -> list[dict]:
        """POST /habitCheckins/query — get check-in records."""
        result = await self._request(
            "POST", "/habitCheckins/query",
            json_body={"habitIds": habit_ids, "afterStamp": after_stamp},
        )
        return result if isinstance(result, list) else []

    async def checkin_habit(self, checkins: list[dict]) -> dict:
        """POST /habitCheckins/batch — create/update check-in records."""
        result = await self._request(
            "POST", "/habitCheckins/batch",
            json_body={"add": checkins},
        )
        return result if isinstance(result, dict) else {}

    # ------------------------------------------------------------------
    # Tags
    # ------------------------------------------------------------------

    async def batch_tags(
        self,
        add: list[dict] | None = None,
        update: list[dict] | None = None,
        delete: list[str] | None = None,
    ) -> dict:
        """POST /batch/tag — create, update, or delete tags."""
        body: dict = {}
        if add:
            body["add"] = add
        if update:
            body["update"] = update
        if delete:
            body["delete"] = delete
        result = await self._request("POST", "/batch/tag", json_body=body)
        return result if isinstance(result, dict) else {}

    async def rename_tag(self, old_name: str, new_name: str) -> dict:
        """PUT /tag/rename"""
        result = await self._request(
            "PUT", "/tag/rename",
            json_body={"name": old_name, "newName": new_name},
        )
        return result if isinstance(result, dict) else {}
```

**Step 4: Run tests to verify they pass**

Run: `cd ticktick-mcp && uv run pytest tests/test_v2_client.py -v`
Expected: 3 tests PASS

**Step 5: Commit**

```bash
git add ticktick_mcp/v2_client.py tests/test_v2_client.py
git commit -m "feat(v2): add V2 API client with session auth, focus, habits, tags"
```

---

### Task 1.2: Integrate V2 Client into Server Lifespan

**Files:**
- Modify: `ticktick_mcp/server.py` (lifespan function, lines 49-56)
- Create: `tests/test_server_lifespan.py`

**Step 1: Write the failing test**

```python
# tests/test_server_lifespan.py
import pytest
from unittest.mock import patch, AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_lifespan_creates_v2_client_when_credentials_present():
    """When V2 credentials are set, lifespan creates both clients."""
    env = {
        "TICKTICK_ACCESS_TOKEN": "fake-v1-token",
        "TICKTICK_USERNAME": "user@test.com",
        "TICKTICK_PASSWORD": "pass123",
    }
    with patch.dict("os.environ", env):
        with patch("ticktick_mcp.server.TickTickV2Client") as MockV2:
            mock_v2 = MagicMock()
            mock_v2.authenticate = AsyncMock()
            mock_v2.close = AsyncMock()
            MockV2.return_value = mock_v2

            from ticktick_mcp.server import app_lifespan, mcp
            async with app_lifespan(mcp) as ctx:
                assert "ticktick" in ctx
                assert "ticktick_v2" in ctx
                assert ctx["ticktick_v2"] is mock_v2
                mock_v2.authenticate.assert_called_once()


@pytest.mark.asyncio
async def test_lifespan_v2_is_none_when_credentials_missing():
    """When V2 credentials are missing, v2 client is None (graceful degradation)."""
    env = {
        "TICKTICK_ACCESS_TOKEN": "fake-v1-token",
    }
    # Clear V2 env vars
    with patch.dict("os.environ", env, clear=True):
        from ticktick_mcp.server import app_lifespan, mcp
        async with app_lifespan(mcp) as ctx:
            assert "ticktick" in ctx
            assert ctx.get("ticktick_v2") is None
```

**Step 2: Run test to verify it fails**

Run: `cd ticktick-mcp && uv run pytest tests/test_server_lifespan.py -v`
Expected: FAIL — lifespan doesn't create V2 client

**Step 3: Update the lifespan in server.py**

Replace the `app_lifespan` function (lines 49-56) with:

```python
import os
import logging

from ticktick_mcp.v2_client import TickTickV2Client, V2AuthError

logger = logging.getLogger(__name__)


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[dict]:
    """Create API clients at startup, close on shutdown.

    V1 client (OAuth) is always created.
    V2 client (session) is created only if credentials are available.
    """
    client = TickTickClient()
    v2_client = None

    # Try to create V2 client if credentials are available
    if os.getenv("TICKTICK_USERNAME") and os.getenv("TICKTICK_PASSWORD"):
        try:
            v2_client = TickTickV2Client()
            await v2_client.authenticate()
            logger.info("V2 client authenticated successfully")
        except (ValueError, V2AuthError) as e:
            logger.warning(f"V2 client unavailable: {e}")
            v2_client = None

    try:
        yield {"ticktick": client, "ticktick_v2": v2_client}
    finally:
        await client.close()
        if v2_client:
            await v2_client.close()
```

Also add a helper function for V2 tools:

```python
def _get_v2_client(ctx) -> TickTickV2Client:
    """Extract the V2 client from request context. Raises if unavailable."""
    v2 = ctx.request_context.lifespan_context.get("ticktick_v2")
    if v2 is None:
        raise ValueError(
            "V2 features require TICKTICK_USERNAME and TICKTICK_PASSWORD. "
            "Set them in your .env file or Replit Secrets."
        )
    return v2
```

**Step 4: Run tests to verify they pass**

Run: `cd ticktick-mcp && uv run pytest tests/ -v`
Expected: All tests PASS

**Step 5: Update .env.example**

Add to `.env.example`:
```
# V2 API (required for focus stats, habits, tags, productivity)
TICKTICK_USERNAME=your-email@example.com
TICKTICK_PASSWORD=your-password
```

**Step 6: Commit**

```bash
git add ticktick_mcp/server.py ticktick_mcp/v2_client.py .env.example tests/
git commit -m "feat(v2): integrate V2 client into server lifespan with graceful degradation"
```

---

## Phase 2: Smart Query Tools

These tools work with V1 only — they aggregate data from the existing project/task endpoints.

### Task 2.1: Add Smart Query Models

**Files:**
- Modify: `ticktick_mcp/models.py`
- Create: `tests/test_models_queries.py`

**Step 1: Write the failing test**

```python
# tests/test_models_queries.py
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
```

**Step 2: Run test to verify it fails**

Run: `cd ticktick-mcp && uv run pytest tests/test_models_queries.py -v`
Expected: FAIL — `ImportError`

**Step 3: Add models to models.py**

Append to `ticktick_mcp/models.py`:

```python
# ---------------------------------------------------------------------------
# Smart Query Models (Phase 2)
# ---------------------------------------------------------------------------

class GetTasksDueTodayInput(BaseModel):
    """Input for listing tasks due today across all projects."""
    model_config = _CONFIG
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


class GetOverdueTasksInput(BaseModel):
    """Input for listing overdue tasks across all projects."""
    model_config = _CONFIG
    include_no_date: bool = Field(
        default=False,
        description="Include tasks with no due date (often forgotten tasks)",
    )
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


class SearchAllTasksInput(BaseModel):
    """Input for searching tasks across ALL projects."""
    model_config = _CONFIG
    query: str = Field(min_length=1, max_length=200, description="Text to search in title and content")
    priority: TaskPriority | None = Field(default=None)
    include_completed: bool = Field(default=False)
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


class GetEngagedTasksInput(BaseModel):
    """Input for GTD 'Engaged' list: high priority OR overdue."""
    model_config = _CONFIG
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


class PlanDayInput(BaseModel):
    """Input for day planning tool."""
    model_config = _CONFIG
    available_hours: float = Field(
        ge=0.5, le=24.0,
        description="How many hours of work time you have today",
    )
    priorities: list[str] | None = Field(
        default=None,
        description="Optional: project names or tags to prioritize",
    )
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)
```

**Step 4: Run tests to verify they pass**

Run: `cd ticktick-mcp && uv run pytest tests/test_models_queries.py -v`
Expected: All 5 tests PASS

**Step 5: Commit**

```bash
git add ticktick_mcp/models.py tests/test_models_queries.py
git commit -m "feat(models): add smart query input models for Phase 2"
```

---

### Task 2.2: Implement Cross-Project Query Helpers

**Files:**
- Create: `ticktick_mcp/queries.py`
- Create: `tests/test_queries.py`

**Step 1: Write the failing test**

```python
# tests/test_queries.py
import pytest
from datetime import datetime, timezone


def _make_task(title, due_date=None, priority=0, status=0, project_id="proj1"):
    """Helper to build a fake task dict."""
    t = {
        "id": f"task-{title.lower().replace(' ', '-')}",
        "title": title,
        "projectId": project_id,
        "priority": priority,
        "status": status,
    }
    if due_date:
        t["dueDate"] = due_date
    return t


def test_filter_overdue_tasks():
    from ticktick_mcp.queries import filter_overdue_tasks
    tasks = [
        _make_task("Old task", due_date="2026-02-01T09:00:00+0000", priority=5),
        _make_task("Future task", due_date="2099-01-01T09:00:00+0000"),
        _make_task("No date task"),
        _make_task("Done task", due_date="2026-02-01T09:00:00+0000", status=2),
    ]
    overdue = filter_overdue_tasks(tasks)
    assert len(overdue) == 1
    assert overdue[0]["title"] == "Old task"


def test_filter_due_today():
    from ticktick_mcp.queries import filter_due_today
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT")
    tasks = [
        _make_task("Today task", due_date=f"{today_str}09:00:00+0000"),
        _make_task("Tomorrow task", due_date="2099-01-01T09:00:00+0000"),
    ]
    today = filter_due_today(tasks)
    assert len(today) == 1
    assert today[0]["title"] == "Today task"


def test_sort_by_priority_then_date():
    from ticktick_mcp.queries import sort_by_priority_then_date
    tasks = [
        _make_task("Low", priority=1, due_date="2026-02-10T09:00:00+0000"),
        _make_task("High early", priority=5, due_date="2026-02-01T09:00:00+0000"),
        _make_task("High late", priority=5, due_date="2026-02-15T09:00:00+0000"),
        _make_task("Medium", priority=3),
    ]
    sorted_tasks = sort_by_priority_then_date(tasks)
    assert [t["title"] for t in sorted_tasks] == [
        "High early", "High late", "Medium", "Low"
    ]
```

**Step 2: Run test to verify it fails**

Run: `cd ticktick-mcp && uv run pytest tests/test_queries.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Write the queries module**

```python
# ticktick_mcp/queries.py
"""Cross-project query helpers for smart task filtering.

These functions operate on lists of task dicts returned by the TickTick API.
They are pure functions (no I/O) for easy testing.
"""

from __future__ import annotations

from datetime import datetime, timezone, date


def parse_date(date_str: str | None) -> datetime | None:
    """Parse a TickTick date string to datetime. Returns None if unparseable."""
    if not date_str:
        return None
    try:
        # TickTick uses format like "2026-02-13T09:00:00+0000"
        # Also handles "2026-02-13T09:00:00.000+0000"
        cleaned = date_str.replace(".000", "")
        if cleaned.endswith("+0000") or cleaned.endswith("-0000"):
            cleaned = cleaned[:-5] + "+00:00"
        return datetime.fromisoformat(cleaned)
    except (ValueError, TypeError):
        return None


def is_active(task: dict) -> bool:
    """Check if task is not completed (status != 2)."""
    return task.get("status", 0) != 2


def filter_overdue_tasks(tasks: list[dict]) -> list[dict]:
    """Return active tasks with due dates in the past."""
    now = datetime.now(timezone.utc)
    result = []
    for t in tasks:
        if not is_active(t):
            continue
        due = parse_date(t.get("dueDate"))
        if due and due < now:
            result.append(t)
    return sort_by_priority_then_date(result)


def filter_due_today(tasks: list[dict]) -> list[dict]:
    """Return active tasks due today."""
    today = date.today()
    result = []
    for t in tasks:
        if not is_active(t):
            continue
        due = parse_date(t.get("dueDate"))
        if due and due.date() == today:
            result.append(t)
    return sort_by_priority_then_date(result)


def filter_due_this_week(tasks: list[dict]) -> list[dict]:
    """Return active tasks due within the next 7 days (excluding today)."""
    now = datetime.now(timezone.utc)
    today = now.date()
    from datetime import timedelta
    week_end = today + timedelta(days=7)
    result = []
    for t in tasks:
        if not is_active(t):
            continue
        due = parse_date(t.get("dueDate"))
        if due and today < due.date() <= week_end:
            result.append(t)
    return sort_by_priority_then_date(result)


def filter_completed_since(tasks: list[dict], since: datetime) -> list[dict]:
    """Return tasks completed after the given datetime."""
    result = []
    for t in tasks:
        if t.get("status") != 2:
            continue
        completed = parse_date(t.get("completedTime"))
        if completed and completed >= since:
            result.append(t)
    return result


def filter_engaged(tasks: list[dict]) -> list[dict]:
    """GTD 'Engaged' list: high priority OR overdue."""
    now = datetime.now(timezone.utc)
    result = []
    for t in tasks:
        if not is_active(t):
            continue
        is_high = t.get("priority", 0) >= 5
        due = parse_date(t.get("dueDate"))
        is_overdue = due is not None and due < now
        if is_high or is_overdue:
            result.append(t)
    return sort_by_priority_then_date(result)


def sort_by_priority_then_date(tasks: list[dict]) -> list[dict]:
    """Sort tasks by priority (desc) then due date (asc, None last)."""
    def sort_key(t):
        priority = -(t.get("priority", 0))
        due = parse_date(t.get("dueDate"))
        date_key = due.isoformat() if due else "9999"
        return (priority, date_key)
    return sorted(tasks, key=sort_key)


def search_tasks(tasks: list[dict], query: str) -> list[dict]:
    """Case-insensitive search in task title and content."""
    q = query.lower()
    return [
        t for t in tasks
        if q in t.get("title", "").lower()
        or q in t.get("content", "").lower()
    ]
```

**Step 4: Run tests to verify they pass**

Run: `cd ticktick-mcp && uv run pytest tests/test_queries.py -v`
Expected: All 3 tests PASS

**Step 5: Commit**

```bash
git add ticktick_mcp/queries.py tests/test_queries.py
git commit -m "feat(queries): add pure-function query helpers for filtering and sorting"
```

---

### Task 2.3: Implement Smart Query Tools

**Files:**
- Modify: `ticktick_mcp/server.py`
- Create: `tests/test_smart_query_tools.py`

**Step 1: Write the failing test**

```python
# tests/test_smart_query_tools.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_mock_ctx(projects, project_data_map):
    """Create a mock context with a fake V1 client."""
    mock_client = MagicMock()
    mock_client.get_projects = AsyncMock(return_value=projects)
    mock_client.get_project_with_data = AsyncMock(
        side_effect=lambda pid: project_data_map.get(pid, {"tasks": []})
    )

    ctx = MagicMock()
    ctx.request_context.lifespan_context = {"ticktick": mock_client, "ticktick_v2": None}
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
                {"id": "t1", "title": "Old task", "dueDate": "2026-01-01T09:00:00+0000", "priority": 5, "status": 0, "projectId": "p1"},
                {"id": "t2", "title": "Future task", "dueDate": "2099-01-01T09:00:00+0000", "priority": 0, "status": 0, "projectId": "p1"},
            ],
        }
    }
    ctx = _make_mock_ctx(projects, data)
    params = GetOverdueTasksInput()
    result = await ticktick_get_overdue_tasks(params, ctx)
    assert "Old task" in result
    assert "Future task" not in result
```

**Step 2: Run test to verify it fails**

Run: `cd ticktick-mcp && uv run pytest tests/test_smart_query_tools.py -v`
Expected: FAIL — `ImportError: cannot import name 'ticktick_get_overdue_tasks'`

**Step 3: Add tools to server.py**

Append these tools to `server.py`, after the existing task tools section:

```python
# ===================================================================
# SMART QUERY TOOLS (Phase 2)
# ===================================================================

from ticktick_mcp.queries import (
    filter_overdue_tasks,
    filter_due_today,
    filter_engaged,
    search_tasks,
    sort_by_priority_then_date,
)
from ticktick_mcp.models import (
    GetTasksDueTodayInput,
    GetOverdueTasksInput,
    SearchAllTasksInput,
    GetEngagedTasksInput,
    PlanDayInput,
)


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
async def ticktick_get_tasks_due_today(params: GetTasksDueTodayInput, ctx=None) -> str:
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
async def ticktick_get_overdue_tasks(params: GetOverdueTasksInput, ctx=None) -> str:
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
async def ticktick_get_engaged_tasks(params: GetEngagedTasksInput, ctx=None) -> str:
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
async def ticktick_search_all_tasks(params: SearchAllTasksInput, ctx=None) -> str:
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
async def ticktick_plan_day(params: PlanDayInput, ctx=None) -> str:
    """Help structure your day from your task list.

    Pulls overdue + due today + high priority tasks, estimates time using
    pomo estimates (default 25 min per task), and suggests a sequenced plan
    that fits within your available hours. Flags if over-committed.
    """
    try:
        all_tasks, _ = await _fetch_all_tasks(ctx)
        overdue = filter_overdue_tasks(all_tasks)
        due_today = filter_due_today(all_tasks)
        high_pri = [t for t in all_tasks if t.get("priority", 0) >= 5 and t.get("status", 0) != 2]

        # Deduplicate (a task can be both overdue and high priority)
        seen = set()
        candidates = []
        for t in overdue + due_today + high_pri:
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
            over = " ⚠️ OVER BUDGET" if total_minutes > available_minutes else ""
            plan_lines.append(
                f"{icon} {t.get('title', '?')} — {project} ({est_minutes}min){over}"
            )

        header = f"# Day Plan ({params.available_hours}h available)\n\n"
        header += f"**Tasks:** {len(candidates)} | **Estimated:** {total_minutes}min ({total_minutes/60:.1f}h)\n"
        if total_minutes > available_minutes:
            over_by = (total_minutes - available_minutes) / 60
            header += f"**⚠️ Over-committed by {over_by:.1f}h** — consider deferring lower-priority items\n"
        else:
            slack = (available_minutes - total_minutes) / 60
            header += f"**✅ {slack:.1f}h slack** — room for unexpected work\n"

        header += "\n## Suggested Sequence\n\n"
        body = "\n".join(f"{i+1}. {line}" for i, line in enumerate(plan_lines))

        return truncate_response(header + body)
    except Exception as e:
        return _handle_error(e)
```

**Step 4: Run all tests**

Run: `cd ticktick-mcp && uv run pytest tests/ -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add ticktick_mcp/server.py ticktick_mcp/models.py tests/test_smart_query_tools.py
git commit -m "feat(tools): add 5 smart query tools — due today, overdue, engaged, search all, plan day"
```

---

## Phase 3: Daily Standup & Review

### Task 3.1: Add Standup/Review Models

**Files:**
- Modify: `ticktick_mcp/models.py`

**Step 1: Add models**

```python
# Append to models.py

class DailyStandupInput(BaseModel):
    """Input for daily standup briefing."""
    model_config = _CONFIG
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


class WeeklyReviewInput(BaseModel):
    """Input for weekly review analysis."""
    model_config = _CONFIG
    week_offset: int = Field(
        default=0,
        ge=-52, le=0,
        description="0 = this week, -1 = last week, etc.",
    )
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)
```

**Step 2: Commit**

```bash
git add ticktick_mcp/models.py
git commit -m "feat(models): add daily standup and weekly review input models"
```

---

### Task 3.2: Implement Daily Standup Tool

**Files:**
- Modify: `ticktick_mcp/server.py`
- Create: `tests/test_standup_tools.py`

**Step 1: Write the failing test**

```python
# tests/test_standup_tools.py
import pytest
from unittest.mock import AsyncMock, MagicMock


def _make_mock_ctx_with_tasks(tasks_by_project):
    """Create mock context returning tasks organized by project."""
    projects = [{"id": pid, "name": pname, "closed": False} for pid, pname in tasks_by_project.keys()]
    mock_client = MagicMock()
    mock_client.get_projects = AsyncMock(return_value=projects)
    mock_client.get_project_with_data = AsyncMock(
        side_effect=lambda pid: {
            "project": {"id": pid, "name": dict(tasks_by_project.keys()).get(pid, "")},
            "tasks": tasks_by_project.get(
                next((k for k in tasks_by_project if k[0] == pid), None), []
            ),
        }
    )
    ctx = MagicMock()
    ctx.request_context.lifespan_context = {"ticktick": mock_client, "ticktick_v2": None}
    return ctx


@pytest.mark.asyncio
async def test_daily_standup_returns_sections():
    from ticktick_mcp.server import ticktick_daily_standup
    from ticktick_mcp.models import DailyStandupInput

    ctx = _make_mock_ctx_with_tasks({
        ("p1", "Work"): [
            {"id": "t1", "title": "Overdue task", "dueDate": "2026-01-01T09:00:00+0000", "priority": 5, "status": 0, "projectId": "p1"},
        ],
    })

    result = await ticktick_daily_standup(DailyStandupInput(), ctx)
    assert "OVERDUE" in result or "Overdue" in result
    assert "Overdue task" in result
```

**Step 2: Run test to verify it fails**

Run: `cd ticktick-mcp && uv run pytest tests/test_standup_tools.py -v`
Expected: FAIL

**Step 3: Implement the standup and review tools**

Add to `server.py`:

```python
from datetime import datetime, timezone, timedelta
from ticktick_mcp.queries import (
    filter_overdue_tasks,
    filter_due_today,
    filter_due_this_week,
    filter_completed_since,
    filter_engaged,
    search_tasks,
    sort_by_priority_then_date,
)
from ticktick_mcp.models import DailyStandupInput, WeeklyReviewInput


@mcp.tool(
    name="ticktick_daily_standup",
    annotations={"title": "Daily Standup Briefing", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
)
async def ticktick_daily_standup(params: DailyStandupInput, ctx=None) -> str:
    """Morning briefing: overdue tasks, due today, completed yesterday, and this week's horizon.

    Zero-parameter tool. Call this every morning for a structured view
    of what needs attention, what's coming, and what you accomplished.
    """
    try:
        all_tasks, _ = await _fetch_all_tasks(ctx)
        now = datetime.now(timezone.utc)
        yesterday = now - timedelta(days=1)

        overdue = filter_overdue_tasks(all_tasks)
        due_today = filter_due_today(all_tasks)
        completed_yesterday = filter_completed_since(all_tasks, yesterday.replace(hour=0, minute=0, second=0))
        coming_this_week = filter_due_this_week(all_tasks)

        sections = []
        sections.append(f"# Daily Standup — {now.strftime('%A, %B %d, %Y')}\n")

        # Overdue
        sections.append(f"## 🔴 OVERDUE ({len(overdue)} tasks)")
        if overdue:
            for t in overdue[:10]:
                icon = "🔴" if t.get("priority", 0) >= 5 else "🟡" if t.get("priority", 0) >= 3 else "⚪"
                project = t.get("_project_name", "")
                due = t.get("dueDate", "")[:10] if t.get("dueDate") else "no date"
                sections.append(f"  - {icon} **{t.get('title', '?')}** — {project} (due {due})")
        else:
            sections.append("  None — you're caught up!")

        # Due Today
        sections.append(f"\n## 📅 DUE TODAY ({len(due_today)} tasks)")
        if due_today:
            for t in due_today[:10]:
                icon = "🔴" if t.get("priority", 0) >= 5 else "🟡" if t.get("priority", 0) >= 3 else "⚪"
                project = t.get("_project_name", "")
                sections.append(f"  - {icon} {t.get('title', '?')} — {project}")
        else:
            sections.append("  Nothing due today.")

        # Completed Yesterday
        sections.append(f"\n## ✅ COMPLETED YESTERDAY ({len(completed_yesterday)} tasks)")
        if completed_yesterday:
            for t in completed_yesterday[:10]:
                project = t.get("_project_name", "")
                sections.append(f"  - {t.get('title', '?')} — {project}")
        else:
            sections.append("  No completions yesterday.")

        # Coming This Week
        sections.append(f"\n## 🔮 COMING THIS WEEK ({len(coming_this_week)} tasks)")
        if coming_this_week:
            for t in coming_this_week[:10]:
                due = t.get("dueDate", "")[:10] if t.get("dueDate") else ""
                project = t.get("_project_name", "")
                sections.append(f"  - {t.get('title', '?')} — {project} ({due})")
        else:
            sections.append("  Clear week ahead.")

        return truncate_response("\n".join(sections))
    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="ticktick_weekly_review",
    annotations={"title": "Weekly Review", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
)
async def ticktick_weekly_review(params: WeeklyReviewInput, ctx=None) -> str:
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
        sections.append(f"# Weekly Review — {week_label}\n")

        sections.append(f"## Summary")
        sections.append(f"- **Completed:** {len(completed_this_week)} tasks")
        sections.append(f"- **Currently Overdue:** {len(overdue)} tasks")

        sections.append(f"\n## Completed by Project")
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
```

Also add this import at the top of server.py if not already there:
```python
from ticktick_mcp.queries import parse_date
```

**Step 4: Run all tests**

Run: `cd ticktick-mcp && uv run pytest tests/ -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add ticktick_mcp/server.py ticktick_mcp/models.py tests/test_standup_tools.py
git commit -m "feat(tools): add daily standup and weekly review tools"
```

---

## Phase 4: Focus/Pomodoro Stats (Read-Only)

### Task 4.1: Add Focus Stats Models and Tools

**Files:**
- Modify: `ticktick_mcp/models.py`
- Modify: `ticktick_mcp/server.py`
- Create: `tests/test_focus_tools.py`

**Step 1: Add models to models.py**

```python
class GetFocusStatsInput(BaseModel):
    """Input for focus/pomodoro statistics."""
    model_config = _CONFIG
    period: str = Field(
        default="today",
        description="Time period: 'today', 'week', 'month', or 'year'",
        pattern="^(today|week|month|year)$",
    )
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


class GetFocusHeatmapInput(BaseModel):
    """Input for focus duration heatmap."""
    model_config = _CONFIG
    date_from: str = Field(description="Start date in YYYYMMDD format (e.g., '20260201')")
    date_to: str = Field(description="End date in YYYYMMDD format (e.g., '20260213')")
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


class GetFocusDistributionInput(BaseModel):
    """Input for focus time distribution by tag."""
    model_config = _CONFIG
    date_from: str = Field(description="Start date in YYYYMMDD format")
    date_to: str = Field(description="End date in YYYYMMDD format")
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


class GetProductivityScoreInput(BaseModel):
    """Input for productivity score and general statistics."""
    model_config = _CONFIG
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)
```

**Step 2: Add tools to server.py**

```python
from ticktick_mcp.models import (
    GetFocusStatsInput,
    GetFocusHeatmapInput,
    GetFocusDistributionInput,
    GetProductivityScoreInput,
)


# ===================================================================
# FOCUS / POMODORO TOOLS (Phase 4 — V2 Required)
# ===================================================================


@mcp.tool(
    name="ticktick_get_focus_stats",
    annotations={"title": "Focus Statistics", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
)
async def ticktick_get_focus_stats(params: GetFocusStatsInput, ctx=None) -> str:
    """Get Pomodoro/focus statistics for a time period.

    Returns total focus time, pomo count, and breakdowns.
    Requires V2 API credentials (TICKTICK_USERNAME / TICKTICK_PASSWORD).
    """
    try:
        v2 = _get_v2_client(ctx)
        now = datetime.now(timezone.utc)

        if params.period == "today":
            date_from = now.strftime("%Y%m%d")
            date_to = date_from
        elif params.period == "week":
            start = now - timedelta(days=now.weekday())
            date_from = start.strftime("%Y%m%d")
            date_to = now.strftime("%Y%m%d")
        elif params.period == "month":
            date_from = now.strftime("%Y%m01")
            date_to = now.strftime("%Y%m%d")
        else:  # year
            date_from = now.strftime("%Y0101")
            date_to = now.strftime("%Y%m%d")

        heatmap = await v2.get_focus_heatmap(date_from, date_to)
        distribution = await v2.get_focus_distribution(date_from, date_to)

        if params.response_format == ResponseFormat.JSON:
            return format_json({"period": params.period, "heatmap": heatmap, "distribution": distribution})

        # Format as markdown
        total_seconds = sum(d.get("duration", d.get("pomoDuration", 0)) for d in heatmap) if heatmap else 0
        total_hours = total_seconds / 3600

        lines = [f"# Focus Stats — {params.period.title()}\n"]
        lines.append(f"**Total Focus Time:** {total_hours:.1f}h ({total_seconds // 60}min)")
        lines.append(f"**Days with Focus:** {len([d for d in heatmap if d.get('duration', d.get('pomoDuration', 0)) > 0])}")

        if distribution:
            lines.append(f"\n## By Tag")
            for d in sorted(distribution, key=lambda x: -(x.get("duration", x.get("pomoDuration", 0)))):
                tag = d.get("tag", d.get("name", "Untagged"))
                dur = d.get("duration", d.get("pomoDuration", 0)) / 60
                lines.append(f"  - {tag}: {dur:.0f}min")

        return truncate_response("\n".join(lines))
    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="ticktick_get_focus_heatmap",
    annotations={"title": "Focus Heatmap", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
)
async def ticktick_get_focus_heatmap(params: GetFocusHeatmapInput, ctx=None) -> str:
    """Get daily focus duration heatmap for a date range.

    Shows how much focus time you had each day. Useful for spotting patterns.
    Requires V2 API credentials.
    """
    try:
        v2 = _get_v2_client(ctx)
        heatmap = await v2.get_focus_heatmap(params.date_from, params.date_to)
        if params.response_format == ResponseFormat.JSON:
            return format_json(heatmap)
        lines = [f"# Focus Heatmap ({params.date_from} → {params.date_to})\n"]
        for entry in heatmap:
            date = str(entry.get("date", entry.get("day", "?")))
            dur = entry.get("duration", entry.get("pomoDuration", 0)) / 60
            bar = "█" * int(dur / 15)  # 1 block per 15 min
            lines.append(f"  {date}: {dur:.0f}min {bar}")
        return truncate_response("\n".join(lines))
    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="ticktick_get_focus_distribution",
    annotations={"title": "Focus Distribution by Tag", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
)
async def ticktick_get_focus_distribution(params: GetFocusDistributionInput, ctx=None) -> str:
    """Get focus time broken down by tag for a date range.

    Shows which areas you spent the most focus time on.
    Requires V2 API credentials.
    """
    try:
        v2 = _get_v2_client(ctx)
        distribution = await v2.get_focus_distribution(params.date_from, params.date_to)
        if params.response_format == ResponseFormat.JSON:
            return format_json(distribution)
        lines = [f"# Focus Distribution ({params.date_from} → {params.date_to})\n"]
        total = sum(d.get("duration", d.get("pomoDuration", 0)) for d in distribution) if distribution else 0
        for d in sorted(distribution or [], key=lambda x: -(x.get("duration", x.get("pomoDuration", 0)))):
            tag = d.get("tag", d.get("name", "Untagged"))
            dur = d.get("duration", d.get("pomoDuration", 0))
            pct = (dur / total * 100) if total > 0 else 0
            lines.append(f"  - **{tag}**: {dur // 60}min ({pct:.0f}%)")
        return truncate_response("\n".join(lines))
    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="ticktick_get_productivity_score",
    annotations={"title": "Productivity Score", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
)
async def ticktick_get_productivity_score(params: GetProductivityScoreInput, ctx=None) -> str:
    """Get your TickTick productivity/achievement score and general statistics.

    Includes level, score, pomo totals, task completion counts, and trends.
    Requires V2 API credentials.
    """
    try:
        v2 = _get_v2_client(ctx)
        stats = await v2.get_general_statistics()
        if params.response_format == ResponseFormat.JSON:
            return format_json(stats)

        lines = ["# Productivity Score\n"]
        lines.append(f"**Score:** {stats.get('score', '?')}/100")
        lines.append(f"**Level:** {stats.get('level', '?')}")
        lines.append(f"\n## Pomodoro")
        lines.append(f"  - Today: {stats.get('todayPomoCount', 0)} pomos ({stats.get('todayPomoDuration', 0) // 60}min)")
        lines.append(f"  - Total: {stats.get('totalPomoCount', 0)} pomos ({stats.get('totalPomoDuration', 0) // 60}min)")
        lines.append(f"\n## Tasks")
        lines.append(f"  - Today: {stats.get('todayCompleted', 0)} completed")
        lines.append(f"  - Yesterday: {stats.get('yesterdayCompleted', 0)} completed")
        lines.append(f"  - Total: {stats.get('totalCompleted', 0)} completed")

        return truncate_response("\n".join(lines))
    except Exception as e:
        return _handle_error(e)
```

**Step 3: Run all tests**

Run: `cd ticktick-mcp && uv run pytest tests/ -v`
Expected: All tests PASS

**Step 4: Commit**

```bash
git add ticktick_mcp/server.py ticktick_mcp/models.py tests/test_focus_tools.py
git commit -m "feat(tools): add 4 read-only focus/pomodoro stats tools (V2)"
```

---

## Phase 5: Habit Tracking

### Task 5.1: Add Habit Models and Tools

**Files:**
- Modify: `ticktick_mcp/models.py`
- Modify: `ticktick_mcp/server.py`
- Create: `tests/test_habit_tools.py`

**Step 1: Add models**

```python
class ListHabitsInput(BaseModel):
    """Input for listing all habits."""
    model_config = _CONFIG
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


class CheckinHabitInput(BaseModel):
    """Input for checking in a habit."""
    model_config = _CONFIG
    habit_id: str = Field(min_length=1, description="Habit ID")
    date: str | None = Field(
        default=None,
        description="Date in YYYYMMDD format (defaults to today)",
    )
    value: float | None = Field(
        default=None,
        description="For quantitative habits (e.g., glasses of water). Omit for boolean habits.",
    )


class GetHabitStatsInput(BaseModel):
    """Input for habit statistics."""
    model_config = _CONFIG
    habit_id: str = Field(min_length=1, description="Habit ID")
    days: int = Field(
        default=30,
        ge=7, le=365,
        description="Number of days of history to analyze",
    )
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)
```

**Step 2: Add tools to server.py**

```python
from ticktick_mcp.models import ListHabitsInput, CheckinHabitInput, GetHabitStatsInput


# ===================================================================
# HABIT TOOLS (Phase 5 — V2 Required)
# ===================================================================


@mcp.tool(
    name="ticktick_list_habits",
    annotations={"title": "List Habits", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
)
async def ticktick_list_habits(params: ListHabitsInput, ctx=None) -> str:
    """List all habits with current streak and settings.

    Shows habit name, type (boolean/quantitative), goal, frequency, and streak.
    Requires V2 API credentials.
    """
    try:
        v2 = _get_v2_client(ctx)
        habits = await v2.get_habits()
        if params.response_format == ResponseFormat.JSON:
            return format_json(habits)

        lines = [f"# Habits ({len(habits)})\n"]
        for h in habits:
            name = h.get("name", "?")
            htype = h.get("type", "Boolean")
            goal = h.get("goal", 1)
            unit = h.get("unit", "")
            streak = h.get("streak", 0)
            icon = "🔥" if streak >= 7 else "✅" if streak > 0 else "⚪"
            if htype == "Real":
                lines.append(f"  - {icon} **{name}** — {goal} {unit}/day | Streak: {streak} days | ID: `{h.get('id', '?')}`")
            else:
                lines.append(f"  - {icon} **{name}** — Yes/No | Streak: {streak} days | ID: `{h.get('id', '?')}`")
        return truncate_response("\n".join(lines))
    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="ticktick_checkin_habit",
    annotations={"title": "Check In Habit", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
)
async def ticktick_checkin_habit(params: CheckinHabitInput, ctx=None) -> str:
    """Mark a habit as done for today (or a specific date).

    For boolean habits, just provide the habit_id.
    For quantitative habits, also provide a value (e.g., glasses of water).
    Requires V2 API credentials.
    """
    try:
        v2 = _get_v2_client(ctx)
        stamp = params.date or datetime.now(timezone.utc).strftime("%Y%m%d")
        checkin = {
            "habitId": params.habit_id,
            "checkinStamp": int(stamp),
            "status": 2,  # 2 = completed
        }
        if params.value is not None:
            checkin["value"] = params.value

        result = await v2.checkin_habit([checkin])
        return f"Habit `{params.habit_id}` checked in for {stamp}."
    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="ticktick_get_habit_stats",
    annotations={"title": "Habit Statistics", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
)
async def ticktick_get_habit_stats(params: GetHabitStatsInput, ctx=None) -> str:
    """Get habit performance data: completion rate, streak, history.

    Shows how consistent you've been with a specific habit.
    Requires V2 API credentials.
    """
    try:
        v2 = _get_v2_client(ctx)
        now = datetime.now(timezone.utc)
        start = now - timedelta(days=params.days)
        after_stamp = int(start.strftime("%Y%m%d"))

        checkins = await v2.get_habit_checkins([params.habit_id], after_stamp)
        completed = [c for c in checkins if c.get("status") == 2 and c.get("habitId") == params.habit_id]

        if params.response_format == ResponseFormat.JSON:
            return format_json({
                "habit_id": params.habit_id,
                "days_analyzed": params.days,
                "completed_count": len(completed),
                "completion_rate": len(completed) / params.days if params.days > 0 else 0,
                "checkins": completed,
            })

        rate = (len(completed) / params.days * 100) if params.days > 0 else 0
        lines = [f"# Habit Stats — `{params.habit_id}`\n"]
        lines.append(f"**Period:** Last {params.days} days")
        lines.append(f"**Completed:** {len(completed)} / {params.days} days ({rate:.0f}%)")

        # Simple streak calculation from recent checkins
        sorted_checkins = sorted(completed, key=lambda c: c.get("checkinStamp", 0), reverse=True)
        if sorted_checkins:
            latest = str(sorted_checkins[0].get("checkinStamp", ""))
            lines.append(f"**Last Check-in:** {latest}")

        return truncate_response("\n".join(lines))
    except Exception as e:
        return _handle_error(e)
```

**Step 3: Run all tests**

Run: `cd ticktick-mcp && uv run pytest tests/ -v`
Expected: All tests PASS

**Step 4: Commit**

```bash
git add ticktick_mcp/server.py ticktick_mcp/models.py tests/test_habit_tools.py
git commit -m "feat(tools): add 3 habit tracking tools — list, checkin, stats (V2)"
```

---

## Phase 6: Tag Management & Productivity

### Task 6.1: Add Tag and Productivity Models and Tools

**Files:**
- Modify: `ticktick_mcp/models.py`
- Modify: `ticktick_mcp/server.py`
- Create: `tests/test_tag_tools.py`

**Step 1: Add models**

```python
class ListTagsInput(BaseModel):
    """Input for listing all tags."""
    model_config = _CONFIG
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


class CreateTagInput(BaseModel):
    """Input for creating a tag."""
    model_config = _CONFIG
    name: str = Field(min_length=1, max_length=100, description="Tag name")
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    parent: str | None = Field(default=None, description="Parent tag name for nesting")


class RenameTagInput(BaseModel):
    """Input for renaming a tag."""
    model_config = _CONFIG
    old_name: str = Field(min_length=1, description="Current tag name")
    new_name: str = Field(min_length=1, description="New tag name")
```

**Step 2: Add tools**

```python
from ticktick_mcp.models import ListTagsInput, CreateTagInput, RenameTagInput


# ===================================================================
# TAG TOOLS (Phase 6 — V2 Required)
# ===================================================================


@mcp.tool(
    name="ticktick_list_tags",
    annotations={"title": "List Tags", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
)
async def ticktick_list_tags(params: ListTagsInput, ctx=None) -> str:
    """List all tags. V2 API exposes full tag management that V1 doesn't.

    Requires V2 API credentials.
    """
    try:
        v2 = _get_v2_client(ctx)
        # Tags come from the batch sync endpoint
        stats = await v2.get_general_statistics()
        tags = stats.get("tags", [])
        if params.response_format == ResponseFormat.JSON:
            return format_json(tags)
        lines = [f"# Tags ({len(tags)})\n"]
        for tag in tags:
            name = tag if isinstance(tag, str) else tag.get("label", tag.get("name", "?"))
            lines.append(f"  - {name}")
        return truncate_response("\n".join(lines))
    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="ticktick_create_tag",
    annotations={"title": "Create Tag", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True},
)
async def ticktick_create_tag(params: CreateTagInput, ctx=None) -> str:
    """Create a new tag. Supports nesting via parent parameter.

    Requires V2 API credentials.
    """
    try:
        v2 = _get_v2_client(ctx)
        tag: dict = {"label": params.name, "name": params.name.lower()}
        if params.color:
            tag["color"] = params.color
        if params.parent:
            tag["parent"] = params.parent.lower()
        result = await v2.batch_tags(add=[tag])
        return f"Tag '{params.name}' created successfully."
    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="ticktick_rename_tag",
    annotations={"title": "Rename Tag", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
)
async def ticktick_rename_tag(params: RenameTagInput, ctx=None) -> str:
    """Rename an existing tag. All tasks with the old tag are updated automatically.

    Requires V2 API credentials.
    """
    try:
        v2 = _get_v2_client(ctx)
        await v2.rename_tag(params.old_name, params.new_name)
        return f"Tag '{params.old_name}' renamed to '{params.new_name}'."
    except Exception as e:
        return _handle_error(e)
```

**Step 3: Run all tests**

Run: `cd ticktick-mcp && uv run pytest tests/ -v`
Expected: All tests PASS

**Step 4: Commit**

```bash
git add ticktick_mcp/server.py ticktick_mcp/models.py tests/test_tag_tools.py
git commit -m "feat(tools): add 3 tag management tools + productivity score (V2)"
```

---

## Phase 7: Deploy and Verify

### Task 7.1: Update Replit and Verify

**Files:**
- Modify: `.env.example`
- No code changes

**Step 1: Update .env.example with all required vars**

```
# V1 API (required for all tools)
TICKTICK_ACCESS_TOKEN=your-oauth-access-token

# V2 API (required for focus, habits, tags, productivity)
TICKTICK_USERNAME=your-email@example.com
TICKTICK_PASSWORD=your-password

# Transport (set to 'sse' for Replit, default 'stdio' for Claude Desktop)
MCP_TRANSPORT=stdio
```

**Step 2: Add V2 secrets to Replit**

In Replit Secrets, add:
- `TICKTICK_USERNAME` = your TickTick email
- `TICKTICK_PASSWORD` = your TickTick password

**Step 3: Push to GitHub and pull on Replit**

```bash
git push origin main
```

Then in Replit Shell: `git pull && pip install -q fastmcp httpx python-dotenv pydantic && python -m ticktick_mcp`

**Step 4: Verify tool count**

Run locally:
```bash
cd ticktick-mcp && uv run python -c "
from ticktick_mcp.server import mcp
tools = mcp._tool_manager._tools
print(f'{len(tools)} tools:')
for name in sorted(tools): print(f'  {name}')
"
```

Expected: ~31 tools listed

**Step 5: Commit all remaining changes**

```bash
git add .
git commit -m "chore(deploy): update env example and prepare for Replit deployment"
git push origin main
```

---

## Final Tool Inventory

| # | Tool | Phase | API | Purpose |
|---|------|-------|-----|---------|
| 1 | ticktick_list_projects | Existing | V1 | List all projects |
| 2 | ticktick_get_project | Existing | V1 | Get project + tasks |
| 3 | ticktick_create_project | Existing | V1 | Create project |
| 4 | ticktick_update_project | Existing | V1 | Update project |
| 5 | ticktick_delete_project | Existing | V1 | Delete project |
| 6 | ticktick_get_task | Existing | V1 | Get single task |
| 7 | ticktick_search_tasks | Existing | V1 | Search within project |
| 8 | ticktick_create_task | Existing | V1 | Create task |
| 9 | ticktick_update_task | Existing | V1 | Update task |
| 10 | ticktick_complete_task | Existing | V1 | Complete task |
| 11 | ticktick_delete_task | Existing | V1 | Delete task |
| 12 | ticktick_batch_create_tasks | Existing | V1 | Batch create tasks |
| 13 | ticktick_move_task | Existing | V1 | Move task between projects |
| 14 | ticktick_get_tasks_due_today | Phase 2 | V1 | Tasks due today (all projects) |
| 15 | ticktick_get_overdue_tasks | Phase 2 | V1 | Overdue tasks (all projects) |
| 16 | ticktick_get_engaged_tasks | Phase 2 | V1 | GTD Engaged list |
| 17 | ticktick_search_all_tasks | Phase 2 | V1 | Search across all projects |
| 18 | ticktick_plan_day | Phase 2 | V1 | Day planner |
| 19 | ticktick_daily_standup | Phase 3 | V1 | Morning briefing |
| 20 | ticktick_weekly_review | Phase 3 | V1 | Week analysis |
| 21 | ticktick_get_focus_stats | Phase 4 | V2 | Focus stats (period) |
| 22 | ticktick_get_focus_heatmap | Phase 4 | V2 | Daily focus heatmap |
| 23 | ticktick_get_focus_distribution | Phase 4 | V2 | Focus by tag |
| 24 | ticktick_get_productivity_score | Phase 4 | V2 | Productivity score |
| 25 | ticktick_list_habits | Phase 5 | V2 | List habits + streaks |
| 26 | ticktick_checkin_habit | Phase 5 | V2 | Check in habit |
| 27 | ticktick_get_habit_stats | Phase 5 | V2 | Habit completion stats |
| 28 | ticktick_list_tags | Phase 6 | V2 | List all tags |
| 29 | ticktick_create_tag | Phase 6 | V2 | Create tag |
| 30 | ticktick_rename_tag | Phase 6 | V2 | Rename tag |
