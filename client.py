"""Small, anonymous AI HOT REST API v1 client.

The client deliberately keeps only bounded in-memory state.  It is designed to
be owned by one plugin instance, and accepts a logger from that owner so the
plugin does not create a second logging configuration.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlsplit

import httpx

BASE_URL = "https://aihot.virxact.com"

# Server-side shared-cache defaults.  A response Cache-Control s-maxage wins
# over these values for the URL that returned it.
THROTTLE_SECONDS: dict[str, int] = {
    "/api/v1/items": 60,
    "/api/v1/hot-topics": 300,
}
DEFAULT_THROTTLE_SECONDS = 30
DEFAULT_STALE_IF_ERROR_SECONDS = 300

MAX_5XX_RETRIES = 3
MAX_429_RETRIES = 3
REQUEST_TIMEOUT = 15.0
MAX_CACHE_ENTRIES = 512

VALID_MODES = ("selected", "all")
VALID_WINDOWS = ("24h", "7d")
VALID_BY = ("timeline", "published")
VALID_CATEGORIES = ("ai-models", "ai-products", "industry", "paper", "tip")

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_S_MAXAGE_RE = re.compile(r"(?:^|,)\s*s-maxage\s*=\s*\"?(\d+)\"?", re.IGNORECASE)
_STALE_IF_ERROR_RE = re.compile(
    r"(?:^|,)\s*stale-if-error\s*=\s*\"?(\d+)\"?", re.IGNORECASE
)


class _NoopLogger:
    """Logger seam used when the client is exercised outside AstrBot."""

    def debug(self, *args: Any, **kwargs: Any) -> None:
        return None

    info = debug
    warning = debug
    error = debug


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
        except (TypeError, ValueError):
            problem = {}
        if not isinstance(problem, dict):
            problem = {}
        return cls(
            status=response.status_code,
            code=str(problem.get("code") or "unknown"),
            title=str(problem.get("title") or ""),
            detail=str(problem.get("detail") or ""),
            request_id=response.headers.get("x-request-id", ""),
        )


def _parse_retry_after(response: httpx.Response, default: float = 5.0) -> float:
    """Parse Retry-After delay-seconds or an HTTP-date.

    RFC 9110 allows an integer delay or an IMF-fixdate.  A malformed value is
    treated as absent.  Delays are not capped: capping would violate the API's
    back-pressure signal and can turn a busy-loop into an outage amplifier.
    """

    raw = response.headers.get("retry-after")
    if not raw:
        return default
    value = raw.strip()
    if value.isdigit():
        return float(int(value))
    try:
        numeric = float(value)
    except ValueError:
        numeric = None
    if numeric is not None and numeric >= 0:
        return numeric
    try:
        retry_at = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return default
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=UTC)
    return max(0.0, (retry_at - datetime.now(UTC)).total_seconds())


def _cache_control_seconds(header: str | None, pattern: re.Pattern[str]) -> int | None:
    if not header:
        return None
    match = pattern.search(header)
    if not match:
        return None
    return int(match.group(1))


class AihotClient:
    """Thin, spec-compliant client for the AI HOT API v1.

    Values are cached by exact URL.  Requests for the same URL share one
    in-flight task (single-flight), while ETags and Cache-Control permit cheap
    conditional revalidation.  The cache is bounded by ``MAX_CACHE_ENTRIES``.
    """

    def __init__(
        self,
        logger: Any | None = None,
        *,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self.logger = logger or _NoopLogger()
        self._logger = self.logger
        self._http = http or httpx.AsyncClient(
            base_url=BASE_URL,
            timeout=REQUEST_TIMEOUT,
            follow_redirects=True,
        )
        # url -> data, completed timestamp, freshness and stale-if-error data
        self._cache: dict[str, dict[str, Any]] = {}
        # Kept separately for compatibility with callers that inspect ETags.
        self._etags: dict[str, str] = {}
        self._inflight: dict[str, asyncio.Task[dict[str, Any]]] = {}
        self._closed = False
        # A test seam that also makes all sleeps easy to audit.
        self._sleep: Callable[[float], Awaitable[None]] = asyncio.sleep

    async def close(self) -> None:
        """Close the underlying HTTP client and release all in-flight state."""

        if self._closed:
            return
        self._closed = True
        for task in tuple(self._inflight.values()):
            if not task.done():
                task.cancel()
        self._inflight.clear()
        await self._http.aclose()

    def _default_freshness(self, path: str) -> int:
        endpoint = urlsplit(path).path
        for prefix, seconds in THROTTLE_SECONDS.items():
            if endpoint == prefix or endpoint.startswith(prefix + "/"):
                return seconds
        return DEFAULT_THROTTLE_SECONDS

    def _can_use_cache(self, cached: dict[str, Any], now: float) -> bool:
        return now - cached["at"] < cached["s_maxage"]

    @staticmethod
    def _can_use_stale(cached: dict[str, Any], now: float) -> bool:
        age = now - cached["at"]
        return age <= cached["s_maxage"] + cached["stale_if_error"]

    def _remember(
        self,
        url: str,
        data: dict[str, Any],
        response: httpx.Response,
        completed_at: float,
        *,
        fallback: dict[str, Any] | None = None,
        default_s_maxage: int = DEFAULT_THROTTLE_SECONDS,
    ) -> dict[str, Any]:
        cache_control = response.headers.get("cache-control")
        s_maxage = _cache_control_seconds(cache_control, _S_MAXAGE_RE)
        stale_if_error = _cache_control_seconds(cache_control, _STALE_IF_ERROR_RE)
        previous = fallback or self._cache.get(url)
        entry = {
            "data": data,
            "at": completed_at,
            "s_maxage": (
                s_maxage
                if s_maxage is not None
                else (previous or {}).get("s_maxage", default_s_maxage)
            ),
            "stale_if_error": (
                stale_if_error
                if stale_if_error is not None
                else (previous or {}).get(
                    "stale_if_error", DEFAULT_STALE_IF_ERROR_SECONDS
                )
            ),
        }
        self._cache[url] = entry
        etag = response.headers.get("etag")
        if etag:
            self._etags[url] = etag
        else:
            self._etags.pop(url, None)
        self._evict_cache()
        return entry

    def _evict_cache(self) -> None:
        while len(self._cache) > MAX_CACHE_ENTRIES:
            oldest_url = min(self._cache, key=lambda key: self._cache[key]["at"])
            self._cache.pop(oldest_url, None)
            self._etags.pop(oldest_url, None)

    def _stale_result(
        self,
        url: str,
        cached: dict[str, Any] | None,
        now: float,
        reason: str,
    ) -> dict[str, Any] | None:
        if cached and self._can_use_stale(cached, now):
            self._logger.warning(
                "AI HOT using bounded stale cache for %s after %s.",
                url,
                reason,
            )
            return cached["data"]
        return None

    async def _get(self, path: str, *, params: dict[str, Any] | None = None) -> dict:
        """GET ``path`` with throttling, revalidation, retries and single-flight."""

        if self._closed:
            raise AihotError("AI HOT client is closed")
        request = self._http.build_request("GET", path, params=params)
        url = str(request.url)
        now = time.monotonic()
        cached = self._cache.get(url)
        if cached and self._can_use_cache(cached, now):
            return cached["data"]

        running = self._inflight.get(url)
        if running is not None:
            return await asyncio.shield(running)

        task = asyncio.create_task(self._fetch(url, path, cached))
        self._inflight[url] = task
        try:
            return await asyncio.shield(task)
        finally:
            if self._inflight.get(url) is task:
                self._inflight.pop(url, None)

    async def _fetch(
        self,
        url: str,
        path: str,
        cached: dict[str, Any] | None,
    ) -> dict[str, Any]:
        retry_429 = 0
        retry_5xx = 0
        headers: dict[str, str] = {}
        if self._etags.get(url):
            headers["If-None-Match"] = self._etags[url]

        while True:
            try:
                response = await self._http.get(url, headers=headers)
            except httpx.HTTPError as exc:
                retry_5xx += 1
                if retry_5xx > MAX_5XX_RETRIES:
                    stale = self._stale_result(
                        url,
                        cached or self._cache.get(url),
                        time.monotonic(),
                        "network error",
                    )
                    if stale is not None:
                        return stale
                    raise AihotError(
                        f"Network error while requesting {url}: {exc}"
                    ) from exc
                delay = min(2**retry_5xx, 30)
                self._logger.warning(
                    "AI HOT network error for %s, retrying in %.1fs: %s",
                    url,
                    delay,
                    exc,
                )
                await self._sleep(delay)
                continue

            if response.status_code == httpx.codes.OK:
                try:
                    data = response.json()
                except (TypeError, ValueError) as exc:
                    raise AihotError(f"AI HOT returned invalid JSON for {url}") from exc
                if not isinstance(data, dict):
                    raise AihotError(
                        f"AI HOT returned a non-object JSON payload for {url}"
                    )
                # Record completion only after the body has been parsed and is
                # known to be usable; request start time must not extend TTL.
                self._remember(
                    url,
                    data,
                    response,
                    time.monotonic(),
                    fallback=cached,
                    default_s_maxage=self._default_freshness(path),
                )
                return data

            if response.status_code == httpx.codes.NOT_MODIFIED:
                current = cached or self._cache.get(url)
                if current:
                    cache_control = response.headers.get("cache-control")
                    s_maxage = _cache_control_seconds(cache_control, _S_MAXAGE_RE)
                    stale_if_error = _cache_control_seconds(
                        cache_control, _STALE_IF_ERROR_RE
                    )
                    if s_maxage is not None:
                        current["s_maxage"] = s_maxage
                    if stale_if_error is not None:
                        current["stale_if_error"] = stale_if_error
                    etag = response.headers.get("etag")
                    if etag:
                        self._etags[url] = etag
                    current["at"] = time.monotonic()
                    return current["data"]
                raise AihotNotModified(
                    f"Server returned 304 for {url} but no cached copy is available."
                )

            if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
                retry_429 += 1
                if retry_429 > MAX_429_RETRIES:
                    stale = self._stale_result(
                        url,
                        cached or self._cache.get(url),
                        time.monotonic(),
                        "429 retries",
                    )
                    if stale is not None:
                        return stale
                    raise AihotAPIError.from_response(response)
                delay = _parse_retry_after(response)
                self._logger.warning("AI HOT 429 for %s, retrying in %.1fs", url, delay)
                await self._sleep(delay)
                continue

            if 500 <= response.status_code < 600:
                retry_5xx += 1
                if retry_5xx > MAX_5XX_RETRIES:
                    stale = self._stale_result(
                        url,
                        cached or self._cache.get(url),
                        time.monotonic(),
                        f"{response.status_code} retries",
                    )
                    if stale is not None:
                        return stale
                    raise AihotAPIError.from_response(response)
                if response.status_code == httpx.codes.SERVICE_UNAVAILABLE:
                    delay = _parse_retry_after(response, default=min(2**retry_5xx, 30))
                else:
                    delay = min(2**retry_5xx, 30)
                self._logger.warning(
                    "AI HOT %s for %s, retrying in %.1fs",
                    response.status_code,
                    url,
                    delay,
                )
                await self._sleep(delay)
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
        """List recent items (selected set or the last-7-day public pool)."""

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

    async def get_daily(self, day: str) -> dict:
        """Fetch a daily report by ISO date."""

        if not _DATE_RE.fullmatch(day):
            raise ValueError("date must be YYYY-MM-DD")
        try:
            datetime.fromisoformat(day).date()
        except ValueError as exc:
            raise ValueError("date must be a valid YYYY-MM-DD date") from exc
        return await self._get(f"/api/v1/dailies/{day}")
