from __future__ import annotations

import asyncio
import unittest
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx

import client


class AihotClientBehaviorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.calls = 0
        self.sleeps: list[float] = []

    async def _client(self, handler) -> client.AihotClient:
        api = client.AihotClient()
        api._http = httpx.AsyncClient(
            base_url=client.BASE_URL,
            transport=httpx.MockTransport(handler),
        )

        async def record_sleep(delay: float) -> None:
            self.sleeps.append(delay)

        api._sleep = record_sleep
        return api

    async def test_cache_control_s_maxage_controls_revalidation(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            self.calls += 1
            return httpx.Response(
                200,
                json={"items": []},
                headers={"cache-control": "public, s-maxage=3600"},
                request=request,
            )

        api = await self._client(handler)
        try:
            first = await api.get_hot_topics()
            second = await api.get_hot_topics()
        finally:
            await api.close()
        self.assertEqual(first, second)
        self.assertEqual(self.calls, 1)

    async def test_endpoint_default_throttle_is_used_without_cache_control(
        self,
    ) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            self.calls += 1
            return httpx.Response(200, json={"items": []}, request=request)

        api = await self._client(handler)
        try:
            await api.get_hot_topics()
            await api.get_hot_topics()
        finally:
            await api.close()
        self.assertEqual(self.calls, 1)

    async def test_single_flight_deduplicates_same_url(self) -> None:
        started = asyncio.Event()
        release = asyncio.Event()

        async def handler(request: httpx.Request) -> httpx.Response:
            self.calls += 1
            started.set()
            await release.wait()
            return httpx.Response(200, json={"items": []}, request=request)

        api = await self._client(handler)
        try:
            first = asyncio.create_task(api.get_hot_topics())
            await started.wait()
            second = asyncio.create_task(api.get_hot_topics())
            await asyncio.sleep(0)
            release.set()
            self.assertEqual(await asyncio.gather(first, second), [{"items": []}] * 2)
        finally:
            await api.close()
        self.assertEqual(self.calls, 1)

    async def test_304_reuses_cached_object_and_conditional_etag(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.calls += 1
            if self.calls == 1:
                return httpx.Response(
                    200,
                    json={"items": [{"id": "same"}]},
                    headers={"etag": '"v1"', "cache-control": "s-maxage=0"},
                    request=request,
                )
            self.assertEqual(request.headers.get("if-none-match"), '"v1"')
            return httpx.Response(
                304,
                headers={"etag": '"v1"', "cache-control": "s-maxage=300"},
                request=request,
            )

        api = await self._client(handler)
        try:
            first = await api.get_hot_topics()
            second = await api.get_hot_topics()
        finally:
            await api.close()
        self.assertEqual(first, second)
        self.assertEqual(self.calls, 2)

    async def test_retry_after_integer_is_honored_for_429(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.calls += 1
            if self.calls == 1:
                return httpx.Response(
                    429,
                    json={"code": "busy"},
                    headers={"retry-after": "17"},
                    request=request,
                )
            return httpx.Response(200, json={"items": []}, request=request)

        api = await self._client(handler)
        try:
            result = await api.get_hot_topics()
        finally:
            await api.close()
        self.assertEqual(result, {"items": []})
        self.assertEqual(self.sleeps, [17.0])

    async def test_retry_after_http_date_is_honored_for_503(self) -> None:
        retry_at = datetime.now(UTC) + timedelta(seconds=20)

        def handler(request: httpx.Request) -> httpx.Response:
            self.calls += 1
            if self.calls == 1:
                return httpx.Response(
                    503,
                    json={"code": "unavailable"},
                    headers={"retry-after": format_datetime(retry_at, usegmt=True)},
                    request=request,
                )
            return httpx.Response(200, json={"items": []}, request=request)

        api = await self._client(handler)
        try:
            result = await api.get_hot_topics()
        finally:
            await api.close()
        self.assertEqual(result, {"items": []})
        self.assertTrue(0 <= self.sleeps[0] <= 21)

    async def test_stale_if_error_is_bounded_after_retry_exhaustion(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            self.calls += 1
            if self.calls == 1:
                return httpx.Response(
                    200,
                    json={"items": [{"id": "cached"}]},
                    headers={"cache-control": "s-maxage=0, stale-if-error=30"},
                    request=request,
                )
            raise httpx.ConnectError("offline", request=request)

        api = await self._client(handler)
        try:
            await api.get_hot_topics()
            result = await api.get_hot_topics()
        finally:
            await api.close()
        self.assertEqual(result, {"items": [{"id": "cached"}]})
        self.assertEqual(self.calls, client.MAX_5XX_RETRIES + 2)

    async def test_success_payload_must_be_a_json_object(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=["not", "an", "object"], request=request)

        api = await self._client(handler)
        try:
            with self.assertRaises(client.AihotError):
                await api.get_hot_topics()
        finally:
            await api.close()


if __name__ == "__main__":
    unittest.main()
