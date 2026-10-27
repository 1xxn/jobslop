"""Dashboard Ende-zu-Ende: echter Server mit Demodaten (Demo-Modus), echter Chromium, gebaute Oberfläche aus web/dist."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

from conftest import serve
from jobslop.config import SearchConfig, get_settings
from jobslop.runtime import Runtime
from jobslop.web.app import create_app

pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parents[1]


def _demo_builder():
    spec = importlib.util.spec_from_file_location("demo_data", ROOT / "scripts" / "demo_data.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.build


@pytest.fixture
def dashboard(tmp_path, monkeypatch):
    home = tmp_path / "demo-home"
    _demo_builder()(home)
    monkeypatch.setenv("JOBSLOP_HOME", str(home))
    monkeypatch.setattr(Runtime, "llm", lambda self: None)  # nie das echte Claude
    get_settings.cache_clear()
    rt = Runtime.load(get_settings())
    assert rt.settings.demo  # Demodaten sind immer im Demo-Modus
    with serve(create_app(rt)) as url:
        yield url, home
    get_settings.cache_clear()


async def test_dashboard_end_to_end(dashboard):
    from playwright.async_api import async_playwright

    base, home = dashboard
    errors: list[str] = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(locale="de-DE", viewport={"width": 1440, "height": 1000})
        page = await ctx.new_page()
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.on("console", lambda msg: msg.type == "error" and errors.append(msg.text))
        try:
            # Heute: oben das eine, was dich braucht (die Freigabe), darunter die Warteliste und neue Stellen
            await page.goto(base)
            await page.get_by_text("Demo · erfundene Daten").first.wait_for()
            await page.get_by_role("heading", name="Vor dem Absenden prüfen").wait_for()
            for text in ("Danach", "Neue Stellen", "Bewerbungen"):
                await page.get_by_role("heading", name=text, exact=True).wait_for()
            assert await page.get_by_text("Bewerbungen pro Woche").count() == 0
            # ein Klick in „Danach“ holt die Rückfrage nach oben
            await page.get_by_role("button", name="Rückfrage").first.click()
            await page.get_by_text("Wie viele Jahre Erfahrung hast du mit Terraform?").wait_for()

            # Demo-Modus: Suchen ist gesperrt und sagt das auch (Suche sitzt in der Lauf-Seitenleiste)
            await page.get_by_role("button", name="Lauf und Suche anzeigen").click()
            await page.get_by_role("button", name="Neue Stellen suchen").click()
            await page.get_by_text("Demo-Modus: Crawlen ist gesperrt").wait_for()
            await page.keyboard.press("Escape")

            # Stellen: Liste und Stelle nebeneinander, die Score-Erklärung steht offen in der Stelle
            await page.goto(f"{base}/jobs")
            await page.get_by_role("option").first.wait_for()
            await page.get_by_role("heading", name=re.compile(r"Warum [\d,.]+ von 21")).wait_for()
            await page.get_by_text("Zielrolle").first.wait_for()
            # Aussortieren mit X springt zur nächsten Stelle, Z macht es rückgängig
            first = await page.get_by_role("option").first.get_attribute("id")
            await page.keyboard.press("x")
            await page.get_by_text("Aussortiert: ").first.wait_for()
            await page.wait_for_function(
                "id => document.querySelector('[role=option]')?.id !== id && !document.getElementById(id)",
                arg=first,
            )
            await page.keyboard.press("z")
            await page.get_by_text("Rückgängig gemacht").wait_for()
            await page.wait_for_selector(f"#{first}")

            # Einstellungen speichern: LinkedIn abschalten bleibt nach dem Neuladen aus
            await page.goto(f"{base}/settings/search")
            linkedin = page.get_by_role("switch", name="LinkedIn")
            await linkedin.wait_for()
            assert await linkedin.get_attribute("aria-checked") == "true"
            await linkedin.click()
            await page.get_by_role("button", name="Speichern").click()
            await page.get_by_text("Suche gespeichert").wait_for()
            config = SearchConfig.load(home / "search.toml")
            assert "linkedin" not in config.sources.portals and "indeed" in config.sources.portals

            # Bewerbungen: nach Stand gruppiert, wartende oben; Detail mit Stand, Nachfassen und Notizen rechts
            await page.goto(f"{base}/applications")
            await page.get_by_role("button", name=re.compile("Wartet auf dich")).wait_for()
            assert (
                await page.get_by_role("button", name=re.compile("Absagen")).get_attribute("aria-expanded")
                == "false"
            )
            await page.get_by_role("link", name=re.compile(r"DevSecOps Engineer\s*Mitte Consulting")).click()
            stage = page.get_by_label("Stand", exact=True)
            await stage.select_option("interview")
            await page.get_by_text("Gespeichert").first.wait_for()

            # Alte Adressen: Pipeline ist die Board-Ansicht der Bewerbungen
            await page.goto(f"{base}/pipeline")
            await page.wait_for_url("**/applications?view=board")
            await page.get_by_role("heading", name="Interview").wait_for()

            # Die Lauf-Seitenleiste öffnet sich auch auf anderen Seiten
            await page.get_by_role("button", name="Lauf und Suche anzeigen").click()
            await page.get_by_role("dialog", name="Was gerade läuft").wait_for()
            await page.keyboard.press("Escape")

            # Tastenkürzel: G dann E öffnet die Einstellungen, ? zeigt die Übersicht
            await page.keyboard.press("g")
            await page.keyboard.press("e")
            await page.wait_for_url("**/settings")
            await page.keyboard.press("?")
            await page.get_by_role("dialog", name="Tastenkürzel").wait_for()
            await page.keyboard.press("Escape")

            # Sprache wechseln (Aktivität ist jetzt das Protokoll): Oberfläche und Backend-Meldungen auf Englisch
            await page.goto(f"{base}/activity")
            await page.wait_for_url("**/settings/log")
            await page.get_by_role("button", name="Sprache und Farbschema").click()
            await page.get_by_role("menuitemradio", name="English").click()
            await page.get_by_text("Search #6: 18 new jobs, 5 queued").wait_for()
            await page.get_by_text("Application run finished: 3× Sent, 1× Question").wait_for()
        finally:
            await browser.close()
    # 409 vom gesperrten Crawl ist erwartet; sonst darf die Konsole sauber bleiben
    assert [e for e in errors if "409" not in e] == []
