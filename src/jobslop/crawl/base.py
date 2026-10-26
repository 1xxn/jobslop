"""Gemeinsame Typen und HTTP-Client für alle Quellen."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

log = logging.getLogger(__name__)

USER_AGENT = "jobslop/1.0 (+private job search; contact via profile email)"


@dataclass
class RawPosting:
    source: str
    external_id: str
    company: str
    title: str
    location: str
    url: str
    apply_url: str = ""
    description: str = ""
    posted: str = ""
    remote: bool = False
    workplace: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


class Source(Protocol):
    name: str

    async def fetch(self, client: httpx.AsyncClient) -> list[RawPosting]: ...


class SourceError(RuntimeError):
    pass


def make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(30.0, connect=10.0),
        headers={"User-Agent": USER_AGENT, "Accept": "application/json, text/xml;q=0.9, */*;q=0.5"},
        follow_redirects=True,
        http2=False,
    )


async def get_json(client: httpx.AsyncClient, url: str, **kwargs: Any) -> Any:
    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
        reraise=True,
    ):
        with attempt:
            resp = await client.get(url, **kwargs)
            if resp.status_code == 404:
                raise SourceError(f"404 für {url}")
            if resp.status_code >= 500 or resp.status_code == 429:
                resp.raise_for_status()
            resp.raise_for_status()
            return resp.json()
    raise SourceError(url)  # pragma: no cover


async def post_json(client: httpx.AsyncClient, url: str, payload: dict[str, Any]) -> Any:
    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
        reraise=True,
    ):
        with attempt:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return resp.json()
    raise SourceError(url)  # pragma: no cover


async def get_text(client: httpx.AsyncClient, url: str) -> str:
    resp = await client.get(url)
    if resp.status_code == 404:
        raise SourceError(f"404 für {url}")
    resp.raise_for_status()
    return resp.text
