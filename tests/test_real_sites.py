"""Smoke-Tests gegen echte Seiten: Quellen liefern Stellen, echte Bewerbungsformulare werden erkannt.

Nur mit ``JOBSLOP_NETWORK=1`` (braucht Internet, Ergebnisse hängen von den Seiten ab). Es wird nichts eingetragen
und nichts abgeschickt – höchstens „Bewerben“ geklickt, damit sich das Formular öffnet.

    JOBSLOP_NETWORK=1 uv run pytest tests/test_real_sites.py -v
"""

from __future__ import annotations

import os
import re

import pytest

from jobslop.apply.engine import BrowserSession, settle
from jobslop.apply.executor import click_element
from jobslop.apply.extract import extract_state
from jobslop.apply.planner import _APPLY_RX, _SUBMIT_RX, is_final_submit
from jobslop.apply.prepare import dismiss_cookie_banners, reveal_lazy_content
from jobslop.crawl.base import get_json, make_client
from jobslop.crawl.sources import (
    ArbeitsagenturSource,
    AshbySource,
    GreenhouseSource,
    LeverSource,
    RecruiteeSource,
)

pytestmark = [
    pytest.mark.network,
    pytest.mark.skipif(
        os.environ.get("JOBSLOP_NETWORK") != "1", reason="nur mit JOBSLOP_NETWORK=1 (echte Seiten)"
    ),
]

# Boards, die es seit Jahren gibt – die konkrete Stelle wird jedes Mal frisch aus der API geholt
BOARDS = [
    ("greenhouse", GreenhouseSource("gitlab")),
    ("ashby", AshbySource("deepl")),
    ("lever", LeverSource("spotify")),
    ("recruitee", RecruiteeSource("novacard")),
]


async def _first_posting(source):
    async with make_client() as client:
        postings = await source.fetch(client)
    assert postings, f"{source.name} liefert keine Stellen mehr"
    return postings[0]


@pytest.mark.parametrize(("kind", "source"), BOARDS, ids=[k for k, _ in BOARDS])
async def test_real_application_form_is_recognised(settings, kind, source):
    posting = await _first_posting(source)
    url = posting.apply_url or posting.url
    async with BrowserSession(settings, headless=True) as browser:
        page = await browser.new_page()
        await page.goto(url, wait_until="domcontentloaded")
        await settle(page)
        await dismiss_cookie_banners(page)
        await reveal_lazy_content(page)
        state = await extract_state(page)
        if not any(f["kind"] == "file" for f in state.fields):
            # Stellenanzeige ohne Formular: „Bewerben“ öffnet es (nichts wird eingetragen)
            apply = next(
                (b for b in state.buttons if _APPLY_RX.search(b["text"]) and not b.get("cookie")), None
            )
            assert apply, f"{kind}: weder Formular noch Bewerben-Button auf {url}"
            page = await click_element(page, state, apply["id"])
            await settle(page)
            await reveal_lazy_content(page)
            state = await extract_state(page)
        labels = " | ".join(f.get("label", "") for f in state.fields)
        kinds = {f["kind"] for f in state.fields}
        assert "file" in kinds, f"{kind}: kein Upload-Feld erkannt ({labels[:300]})"
        assert re.search(r"e-?mail", labels, re.I), f"{kind}: kein E-Mail-Feld erkannt ({labels[:300]})"
        # Den Absende-Button muss jobslop als solchen erkennen (Regel-Planer und Freigabe-Schutz)
        submit = [b["text"] for b in state.buttons if _SUBMIT_RX.search(b["text"])]
        assert submit, f"{kind}: kein Absende-Button erkannt ({[b['text'] for b in state.buttons][:15]})"
        assert all(is_final_submit(b, form_filled=True) for b in state.buttons if b["text"] in submit)
        assert not state.captcha_visible, f"{kind}: sichtbares CAPTCHA – das löst jobslop nie selbst"


async def test_real_job_sources_respond():
    async with make_client() as client:
        ba = ArbeitsagenturSource(
            ["DevOps"], ["berlin"], remote=False, radius_km=25, skip_agencies=True, max_pages=1
        )
        postings = await ba.fetch(client)
        assert postings and all(p.url.startswith("https://www.arbeitsagentur.de/") for p in postings)
        await ba.details(client, postings[0])
        assert len(postings[0].description) > 100
        data = await get_json(
            client, "https://himalayas.app/jobs/api/search", params={"q": "devops", "page": 1}
        )
        assert data.get("jobs"), "Himalayas-API liefert nichts mehr"
