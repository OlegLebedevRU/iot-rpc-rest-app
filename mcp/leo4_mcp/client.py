from __future__ import annotations
import asyncio
import logging
from typing import Any

import httpx

from .config import settings

log = logging.getLogger(__name__)


class Leo4ApiError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"LEO4 API error {status_code}: {detail}")


class Leo4Client:
    """Async HTTP client for LEO4 REST API with retries and error handling."""

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    def _make_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=settings.api_url,
            headers={
                "x-api-key": settings.api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=settings.timeout_s,
        )

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = self._make_client()
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json: Any = None,
    ) -> Any:
        client = await self._ensure_client()
        last_exc: Exception | None = None

        for attempt in range(max(1, settings.http_retries)):
            try:
                resp = await client.request(method, path, params=params, json=json)
                if resp.status_code == 401:
                    raise Leo4ApiError(401, "Unauthorized – check LEO4_API_KEY")
                if resp.status_code == 403:
                    raise Leo4ApiError(403, "Forbidden – API key lacks permission")
                if resp.status_code == 422:
                    raise Leo4ApiError(422, f"Validation error: {resp.text}")
                if resp.status_code == 404:
                    raise Leo4ApiError(404, f"Not found: {path}")
                if resp.status_code >= 500:
                    log.warning("5xx from LEO4, attempt %d: %s", attempt + 1, resp.text)
                    last_exc = Leo4ApiError(resp.status_code, resp.text)
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                resp.raise_for_status()
                return resp.json()
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                log.warning("Network error attempt %d: %s", attempt + 1, exc)
                last_exc = exc
                await asyncio.sleep(0.5 * (attempt + 1))
                continue
            except Leo4ApiError:
                raise

        raise last_exc or Leo4ApiError(0, "Unknown error after retries")

    async def post(self, path: str, *, json: Any = None) -> Any:
        return await self._request("POST", path, json=json)

    async def get(self, path: str, *, params: dict | None = None) -> Any:
        return await self._request("GET", path, params=params)

    async def put(self, path: str, *, json: Any = None) -> Any:
        return await self._request("PUT", path, json=json)

    async def delete(self, path: str) -> Any:
        return await self._request("DELETE", path)


_client: Leo4Client | None = None


def get_client() -> Leo4Client:
    global _client
    if _client is None:
        _client = Leo4Client()
    return _client
