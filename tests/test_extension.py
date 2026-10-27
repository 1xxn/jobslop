"""Browser-Erweiterung Ende-zu-Ende: echter Chromium mit geladener Erweiterung, echter jobslop-Server, Testformular."""

from __future__ import annotations

import socket
import threading
import time

import pytest
import uvicorn
from sqlalchemy import select

from conftest import add_job
from jobslop import assist
from jobslop.db import Answer, Application, session_scope
from jobslop.runtime import Runtime
from jobslop.web.app import create_app

pytestmark = pytest.mark.browser


@pytest.fixture
def server(settings, config, profile, monkeypatch):
    monkeypatch.setattr(
        Runtime, "llm", lambda self: None
    )  # Regel-Planer statt echtem Claude (kein Abo-Verbrauch)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    settings.dashboard_port = port
    app = create_app(Runtime(settings=settings, config=config, profile=profile))
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not srv.started and time.monotonic() < deadline:
        time.sleep(0.05)
    yield settings
    srv.should_exit = True
    thread.join(5)


async def _browser(pw, ext, tmp_path):
    ctx = await pw.chromium.launch_persistent_context(
        str(tmp_path / "chrome"),
        channel="chromium",  # neuer Headless-Modus: lädt Erweiterungen
        headless=True,
        args=[f"--disable-extensions-except={ext}", f"--load-extension={ext}"],
    )
    worker = ctx.service_workers[0] if ctx.service_workers else await ctx.wait_for_event("serviceworker")
    return ctx, worker


START = """async (part) => {
  const tabs = await chrome.tabs.query({});
  await self.jobslopStart(tabs.find((t) => (t.url || "").includes(part)));
}"""


async def test_extension_fills_form_and_submits_only_after_approval(server, site, tmp_path):
    from playwright.async_api import async_playwright

    settings = server
    ext = assist.install(settings)
    url = f"{site.base_url}/greenhouse_like.html?ext=1"
    add_job(settings, url, "Acme Cloud", "Site Reliability Engineer")
    before = len(site.submissions)
    async with async_playwright() as pw:
        ctx, worker = await _browser(pw, ext, tmp_path)
        try:
            page = await ctx.new_page()
            await page.goto(url)
            await worker.evaluate(START, "greenhouse_like")

            # Rückfragen erscheinen im Panel (Shadow DOM) – beantworten
            await page.get_by_text("Antworten & weiter").wait_for(timeout=20_000)
            answers = {"visa": "No", "salary": "70000", "hear": "Company website"}
            for label in await page.locator("jobslop-assistant label").all():
                question = (await label.locator("span").first.inner_text()).lower()
                value = next((v for k, v in answers.items() if k in question), None)
                control = label.locator("select, input").first
                if value and await control.evaluate("e => e.tagName") == "SELECT":
                    await control.select_option(label=value)
                elif value:
                    await control.fill(value)
            await page.get_by_text("Antworten & weiter").click()

            # Alles ausgefüllt, aber nichts abgeschickt, bis du freigibst
            await page.get_by_text("Vor dem Absenden prüfen").wait_for(timeout=20_000)
            assert len(site.submissions) == before
            assert await page.input_value("#first_name") == "Max"
            assert await page.is_checked("#visa-no") and await page.is_checked("#privacy")
            assert await page.input_value("#hear-value") == "Company website"
            assert (
                await page.evaluate("document.getElementById('resume').files[0].name")
                == "Max_Mustermann_CV.pdf"
            )

            await page.get_by_role("button", name="Absenden").click()
            await page.get_by_text("Bewerbung abgeschickt und in jobslop eingetragen").wait_for(
                timeout=20_000
            )
        finally:
            await ctx.close()

    assert len(site.submissions) == before + 1
    sub = site.submissions[before]
    assert sub["first_name"] == "Max" and sub["resume"] == "Max_Mustermann_CV.pdf" and sub["visa"] == "no"
    with session_scope(settings.db_path) as s:
        app = s.execute(select(Application)).scalars().one()
        assert app.origin == "extension" and app.status == "submitted" and app.submitted_at is not None
        assert any(r["ok"] and r["label"].startswith("First Name") for r in app.filled)
        assert s.execute(select(Answer)).scalars().all()  # Antworten gespeichert


async def test_extension_refuses_portals_unless_allowed(server, site, tmp_path):
    """LinkedIn/Indeed nur mit ausdrücklicher Erlaubnis – geprüft wird serverseitig über die Seiten-URL."""
    from jobslop.assist import StepIn, step
    from jobslop.runtime import Runtime

    settings = server
    frame = {
        "url": "https://www.linkedin.com/jobs/view/42/",
        "title": "SRE",
        "fields": [],
        "buttons": [],
        "errors": [],
        "captcha": [],
        "headings": [],
        "text": "",
    }
    rt = Runtime.load(settings)
    result = await step(rt, StepIn(frames=[{"index": 0, "data": frame}]))
    assert "erlaubst" in result["blocked"]
    rt.settings.extension_portals = True
    rt.settings.extension_portal_daily_limit = 0
    result = await step(rt, StepIn(frames=[{"index": 0, "data": frame}]))
    assert "Tageslimit" in result["blocked"]
