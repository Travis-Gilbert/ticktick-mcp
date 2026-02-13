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
        """GET /statistics/general -- productivity scores, pomo totals, task counts."""
        result = await self._request("GET", "/statistics/general")
        return result if isinstance(result, dict) else {}

    # ------------------------------------------------------------------
    # Habits
    # ------------------------------------------------------------------

    async def get_habits(self) -> list[dict]:
        """GET /habits -- list all habits."""
        result = await self._request("GET", "/habits")
        return result if isinstance(result, list) else []

    async def get_habit_checkins(self, habit_ids: list[str], after_stamp: int) -> list[dict]:
        """POST /habitCheckins/query -- get check-in records."""
        result = await self._request(
            "POST", "/habitCheckins/query",
            json_body={"habitIds": habit_ids, "afterStamp": after_stamp},
        )
        return result if isinstance(result, list) else []

    async def checkin_habit(self, checkins: list[dict]) -> dict:
        """POST /habitCheckins/batch -- create/update check-in records."""
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
        """POST /batch/tag -- create, update, or delete tags."""
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
