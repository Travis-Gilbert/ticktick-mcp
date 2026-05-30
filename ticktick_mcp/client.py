"""Async TickTick API client using httpx.

Wraps the TickTick Open API v1 (https://api.ticktick.com/open/v1).
Designed to be used as a lifespan-managed singleton — one httpx.AsyncClient
is created at server start and reused for all requests.
"""

from __future__ import annotations

import os

import httpx
from dotenv import load_dotenv

load_dotenv()

API_BASE_URL = "https://api.ticktick.com/open/v1"
OAUTH_TOKEN_URL = "https://ticktick.com/oauth/token"
REQUEST_TIMEOUT = 30.0


class TickTickAPIError(Exception):
    """Raised when the TickTick API returns an error."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"TickTick API error {status_code}: {detail}")


class TickTickClient:
    """Async wrapper around the TickTick Open API v1.

    Usage with lifespan:
        client = TickTickClient()   # reads token from env
        data = await client.get_projects()
        await client.close()
    """

    def __init__(self, access_token: str | None = None) -> None:
        self._access_token = access_token or os.getenv("TICKTICK_ACCESS_TOKEN", "")
        if not self._access_token:
            raise ValueError(
                "TICKTICK_ACCESS_TOKEN is required. "
                "Set it in your .env file or pass it directly. "
                "Get a token at https://developer.ticktick.com"
            )
        self._http = httpx.AsyncClient(
            base_url=API_BASE_URL,
            headers={
                "Authorization": f"Bearer {self._access_token}",
                "Content-Type": "application/json",
            },
            timeout=REQUEST_TIMEOUT,
        )

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._http.aclose()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict | list | None = None,
        params: dict | None = None,
    ) -> dict | list | None:
        """Make an API request and handle errors consistently."""
        response = await self._http.request(
            method,
            path,
            json=json_body,
            params=params,
        )
        if response.status_code >= 400:
            detail = response.text or f"HTTP {response.status_code}"
            raise TickTickAPIError(response.status_code, detail)
        if response.status_code == 204 or not response.text:
            return None
        return response.json()

    # ------------------------------------------------------------------
    # Projects
    # ------------------------------------------------------------------

    async def get_projects(self) -> list[dict]:
        """GET /project — list all projects/lists."""
        result = await self._request("GET", "/project")
        return result if isinstance(result, list) else []

    async def get_project(self, project_id: str) -> dict:
        """GET /project/{id} — get single project metadata."""
        result = await self._request("GET", f"/project/{project_id}")
        return result if isinstance(result, dict) else {}

    async def get_project_with_data(self, project_id: str) -> dict:
        """GET /project/{id}/data — get project with all tasks and columns."""
        result = await self._request("GET", f"/project/{project_id}/data")
        return result if isinstance(result, dict) else {}

    async def create_project(self, body: dict) -> dict:
        """POST /project — create a new project."""
        result = await self._request("POST", "/project", json_body=body)
        return result if isinstance(result, dict) else {}

    async def update_project(self, project_id: str, body: dict) -> dict:
        """PUT /project/{id} — update an existing project."""
        result = await self._request("PUT", f"/project/{project_id}", json_body=body)
        return result if isinstance(result, dict) else {}

    async def delete_project(self, project_id: str) -> None:
        """DELETE /project/{id} — delete a project."""
        await self._request("DELETE", f"/project/{project_id}")

    # ------------------------------------------------------------------
    # Tasks
    # ------------------------------------------------------------------

    async def get_task(self, project_id: str, task_id: str) -> dict:
        """GET /project/{pid}/task/{tid} — get a single task."""
        result = await self._request("GET", f"/project/{project_id}/task/{task_id}")
        return result if isinstance(result, dict) else {}

    async def create_task(self, body: dict) -> dict:
        """POST /task — create a new task."""
        result = await self._request("POST", "/task", json_body=body)
        return result if isinstance(result, dict) else {}

    async def update_task(self, task_id: str, body: dict) -> dict:
        """POST /task/{id} — update an existing task."""
        result = await self._request("POST", f"/task/{task_id}", json_body=body)
        return result if isinstance(result, dict) else {}

    async def complete_task(self, project_id: str, task_id: str) -> None:
        """POST /project/{pid}/task/{tid}/complete — complete a task."""
        await self._request("POST", f"/project/{project_id}/task/{task_id}/complete")

    async def delete_task(self, project_id: str, task_id: str) -> None:
        """DELETE /task/{pid}/{tid} — delete a task."""
        await self._request("DELETE", f"/task/{project_id}/{task_id}")

    async def batch_create_tasks(self, tasks: list[dict]) -> list[dict]:
        """POST /batch/task — batch-create multiple tasks."""
        result = await self._request("POST", "/batch/task", json_body={"add": tasks})
        if isinstance(result, dict):
            return result.get("add", result.get("created", []))
        return result if isinstance(result, list) else []

    async def move_tasks(self, moves: list[dict]) -> list[dict]:
        """Move tasks between projects in one call.

        moves: [{"fromProjectId": ..., "toProjectId": ..., "taskId": ...}, ...]

        Tries the dedicated batch-move endpoint first. If that endpoint is
        unavailable on the token (4xx), falls back to a per-task
        get -> update(projectId) -> re-read loop that VERIFIES the move took,
        rather than reporting a silent success (the Open API does not always
        honor a projectId change on a task update).

        Returns one result dict per move:
            {"taskId", "fromProjectId", "toProjectId", "moved": bool,
             "title"?: str, "error"?: str}
        """
        try:
            await self._request("POST", "/project/task/move", json_body=moves)
        except TickTickAPIError as e:
            if e.status_code not in (400, 404, 405):
                raise
            return [await self._move_task_verified(m) for m in moves]
        return [{**m, "moved": True} for m in moves]

    async def _move_task_verified(self, move: dict) -> dict:
        """Move one task via get-then-update, then verify by re-reading it."""
        task_id = move["taskId"]
        from_id = move["fromProjectId"]
        to_id = move["toProjectId"]

        task = await self.get_task(from_id, task_id)
        title = task.get("title", "")
        await self.update_task(
            task_id, {"id": task_id, "projectId": to_id, "title": title}
        )

        moved = False
        try:
            check = await self.get_task(to_id, task_id)
            moved = check.get("projectId") == to_id
        except TickTickAPIError as e:
            if e.status_code != 404:
                raise

        result = {
            "taskId": task_id,
            "fromProjectId": from_id,
            "toProjectId": to_id,
            "moved": moved,
            "title": title,
        }
        if not moved:
            result["error"] = (
                "move did not take effect — task is not in the destination "
                "project after update (the Open API may not honor moves on this token)"
            )
        return result
