"""AI HOT REST API v1 client.

Implements the integration contract documented at https://aihot.virxact.com/agent:

- Anonymous, read-only. No API key is required.
- Conditional requests: send ``If-None-Match``; a 304 means nothing changed
  and the cached copy may be reused.
- Poll cadence per the shared-cache ``s-maxage``: ``/api/v1/items`` 60s,
  ``/api/v1/hot-topics`` 300s. Polling faster only re-fetches the same copy.
- On 429 strictly honor ``Retry-After``; on 5xx back off exponentially
  (the service offers no SLA).
- Errors are ``application/problem+json`` with a stable ``code`` and an
  ``X-Request-Id`` header.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import date as _Date
from typing import Any

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://aihot.virxact.com"

# Minimum seconds between fetches of the same URL, from the s-maxage contract.
THROTTLE_SECONDS: dict[str, int] = {
    "/api/v1/items": 60,
    "/api/v1/hot-topics": 300,
}
DEFAULT_THROTTLE_SECONDS = 30

MAX_5XX_RETRIES = 3
MAX_429_RETRIES = 3
REQUEST_TIMEOUT = 15.0

VALID_MODES = ("selected", "all")
VALID_WINDOWS = ("24h", "7d")
VALID_BY = ("timeline", "published")
VALID_CATEGORIES = ("ai-models", "ai-products", "industry", "paper", "tip")

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class AihotError(Exception):
    """Base error for AI HOT API failures."""


class AihotNotModified(AihotError):
    """The server returned 304 but no cached copy is available."""


class AihotAPIError(AihotError):
    """The API returned a non-success response (Problem JSON)."""

    def __init__(
        self,
        status: int,
        code: str,
        title: str = "",
        detail: str = "",
        request_id: str = "",
    ) -> None:
        self.status = status
        self.code = code
        self.title = title
        self.detail = detail
        self.request_id = request_id
        super().__init__(f"[{status}] {code}: {detail or title}")

    @classmethod
    def from_response(cls, response: httpx.Response) -> AihotAPIError:
        try:
            problem = response.json()
        except ValueError:
            problem = {}
        return cls(
            status=response.status_code,
            code=str(problem.get("code") or "unknown"),
            title=str(problem.get("title") or ""),
            detail=str(problem.get("detail") or ""),
            request_id=response.headers.get("x-request-id", ""),
        )


def _parse_retry_after(response: httpx.Response, default: float = 5.0) -> float:
    raw = response.headers.get("retry-after")
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


class AihotClient:
    """Thin, spec-compliant client for the AI HOT REST API v1.

    Responses are cached in memory keyed by the exact URL. ETags enable
    conditional revalidation (304), and the ``s-maxage`` throttle prevents
    polling the shared cache faster than it refreshes.
    """

    def __init__(self) -> None:
        self._http = httpx.AsyncClient(
            base_url=BASE_URL,
            timeout=REQUEST_TIMEOUT,
            follow_redirects=True,
        )
        # url -> {"data": dict, "at": float (monotonic clock)}
        self._cache: dict[str, dict[str, Any]] = {}
        # url -> ETag
        self._etags: dict[str, str] = {}

    async def close(self) -> None:
        await self._http.aclose()

    async def _get(self, path: str, *, params: dict[str, Any] | None = None) -> dict:
        """GET ``path`` with ETag revalidation, throttling and retries."""
        request = self._http.build_request("GET", path, params=params)
        url = str(request.url)
        now = time.monotonic()
        cached = self._cache.get(url)
        throttle = THROTTLE_SECONDS.get(path, DEFAULT_THROTTLE_SECONDS)
        if cached and now - cached["at"] < throttle:
            return cached["data"]

        retry_429 = 0
        retry_5xx = 0
        while True:
            headers: dict[str, str] = {}
            if self._etags.get(url):
                headers["If-None-Match"] = self._etags[url]
            try:
                response = await self._http.get(url, headers=headers)
            except httpx.HTTPError as exc:
                raise AihotError(
                    f"Network error while requesting {url}: {exc}"
                ) from exc

            if response.status_code == httpx.codes.OK:
                data = response.json()
                self._cache[url] = {"data": data, "at": now}
                self._etags[url] = response.headers.get("etag", "")
                return data

            if response.status_code == httpx.codes.NOT_MODIFIED:
                if cached:
                    cached["at"] = now
                    return cached["data"]
                raise AihotNotModified(
                    f"Server returned 304 for {url} but no cached copy is available."
                )

            if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
                retry_429 += 1
                if retry_429 > MAX_429_RETRIES:
                    raise AihotAPIError.from_response(response)
                delay = _parse_retry_after(response)
                logger.warning("AI HOT 429 for %s, retrying in %.1fs", url, delay)
                await asyncio.sleep(delay)
                continue

            if 500 <= response.status_code < 600:
                retry_5xx += 1
                if retry_5xx > MAX_5XX_RETRIES:
                    raise AihotAPIError.from_response(response)
                delay = min(2**retry_5xx, 30)
                logger.warning(
                    "AI HOT %s for %s, retrying in %.1fs",
                    response.status_code,
                    url,
                    delay,
                )
                await asyncio.sleep(delay)
                continue

            raise AihotAPIError.from_response(response)

    # ------------------------------------------------------------------ items

    async def get_items(
        self,
        *,
        mode: str = "selected",
        window: str = "7d",
        by: str = "timeline",
        category: str | None = None,
        q: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> dict:
        """List recent items (selected set or the last-7-day public pool).

        Parameters are validated against the OpenAPI spec; invalid values
        raise ``ValueError`` instead of being silently widened.
        """
        if mode not in VALID_MODES:
            raise ValueError(f"mode must be one of: {', '.join(VALID_MODES)}")
        if window not in VALID_WINDOWS:
            raise ValueError(f"window must be one of: {', '.join(VALID_WINDOWS)}")
        if by not in VALID_BY:
            raise ValueError(f"by must be one of: {', '.join(VALID_BY)}")
        if category is not None and category not in VALID_CATEGORIES:
            raise ValueError(f"category must be one of: {', '.join(VALID_CATEGORIES)}")
        if q is not None and not (2 <= len(q.strip()) <= 200):
            raise ValueError("q must be 2-200 characters")
        if not 1 <= limit <= 100:
            raise ValueError("limit must be 1-100")

        params: dict[str, Any] = {
            "mode": mode,
            "window": window,
            "by": by,
            "limit": limit,
        }
        if category:
            params["category"] = category
        if q:
            params["q"] = q.strip()
        if cursor:
            params["cursor"] = cursor
        return await self._get("/api/v1/items", params=params)

    # ------------------------------------------------------------ hot topics

    async def get_hot_topics(self) -> dict:
        """Current multi-source Top 10 hot-topic board."""
        return await self._get("/api/v1/hot-topics")

    # ----------------------------------------------------------------- stories

    async def get_story(self, public_id: str) -> dict:
        """Event detail: reporting timeline + AI summary + related events."""
        if not public_id:
            raise ValueError("public_id is required")
        return await self._get(f"/api/v1/stories/{public_id}")

    # ----------------------------------------------------------------- dailies

    async def get_dailies(self, limit: int = 30) -> dict:
        """Date index of past daily reports, newest first."""
        if not 1 <= limit <= 180:
            raise ValueError("limit must be 1-180")
        return await self._get("/api/v1/dailies", params={"limit": limit})

    async def get_latest_daily(self) -> dict:
        """Most recent daily report."""
        return await self._get("/api/v1/dailies/latest")

    async def get_daily(self, date: str) -> dict:
        """Daily report for an Asia/Shanghai calendar date (YYYY-MM-DD)."""
        if not _DATE_RE.match(date):
            raise ValueError("date must be in YYYY-MM-DD format")
        try:
            _Date.fromisoformat(date)
        except ValueError:
            raise ValueError("date must be a real YYYY-MM-DD calendar date") from None
        return await self._get(f"/api/v1/dailies/{date}")
