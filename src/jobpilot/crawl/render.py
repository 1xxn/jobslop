"""Headless-Renderer für JavaScript-lastige Karriereseiten."""

from __future__ import annotations

import contextlib
from typing import Any


class PageRenderer:
    """Teilt einen Headless-Chromium über alle generischen Quellen eines Crawl-Laufs."""

    def __init__(self) -> None:
        self._pw: Any = None
        self._browser: Any = None

    async def __aenter__(self) -> PageRenderer:
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._browser is not None:
            await self._browser.close()
        if self._pw is not None:
            await self._pw.stop()

    async def _ensure(self) -> Any:
        if self._browser is None:
            from playwright.async_api import async_playwright

            self._pw = await async_playwright().start()
            self._browser = await self._pw.chromium.launch(headless=True)
        return self._browser

    async def __call__(self, url: str) -> tuple[str, list[dict[str, str]]]:
        browser = await self._ensure()
        page = await browser.new_page(locale="de-DE")
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            with contextlib.suppress(Exception):
                await page.wait_for_load_state("networkidle", timeout=8_000)
            text = await page.evaluate("() => document.body ? document.body.innerText : ''")
            links = await page.evaluate(
                """() => Array.from(document.querySelectorAll('a[href]')).map(a => ({
                    text: (a.innerText || a.getAttribute('aria-label') || '').trim().replace(/\\s+/g, ' '),
                    href: a.href})).filter(l => l.text && l.href.startsWith('http'))"""
            )
            return text, links
        finally:
            await page.close()
