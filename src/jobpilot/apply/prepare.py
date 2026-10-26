"""Seite vorbereiten, bevor der Planer sie sieht: Cookie-Banner schließen, nachgeladene Inhalte wecken, Autofill nutzen.

Alles hier ist deterministisch und kostet kein Abo-Kontingent. Was schiefgeht, wird geloggt und übersprungen –
der Planer sieht danach einfach den aktuellen Zustand der Seite.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .extract import PageState, extract_state

log = logging.getLogger(__name__)

# Sucht in einem Frame (inkl. offener Shadow Roots) den besten Button eines Cookie-Banners und markiert ihn.
# Bevorzugt "ablehnen"/"nur notwendige", sonst "akzeptieren". Nur Buttons innerhalb eines Banners/Dialogs zählen.
_COOKIE_JS = r"""
(tried) => {
  const clean = (s) => (s || "").replace(/\s+/g, " ").trim();
  const CONTAINER = /cookie|consent|gdpr|dsgvo|onetrust|usercentrics|didomi|cookiebot|sp_message|truste|borlabs|klaro|iubenda|cmp-|cmp_|\bcmp\b|cc-banner|cc_banner|cookiefirst|axeptio|tarteaucitron|privacy-banner|datenschutz-banner/i;
  const REJECT = /^(alle ablehnen|ablehnen|alles ablehnen|reject( all)?( cookies)?|decline( all)?( cookies)?|deny( all)?|refuse( all)?|nicht zustimmen|disagree|nur (technisch )?(notwendige|erforderliche|essenzielle|essentielle|funktionale)( cookies)?( (akzeptieren|zulassen|erlauben|verwenden|speichern))?|(accept |use |allow )?only (essential|necessary|required|strictly necessary)( cookies)?|(accept |use |allow )?(strictly )?(necessary|essential|required) (cookies )?only|continue without (accepting|agreeing|consent)|weiter ohne (zustimmung|einwilligung|akzeptieren|cookies)|mit erforderlichen cookies fortfahren)$/i;
  const ACCEPT = /^(alle (akzeptieren|zulassen|erlauben|annehmen|cookies (akzeptieren|zulassen))|accept( all)?( cookies)?|allow( all)?( cookies)?|akzeptieren|annehmen|zustimmen|alle zustimmen|agree|i agree|einverstanden|ok|okay|verstanden|got it|that[’']?s (ok|okay|fine)|alles klar|zustimmen und (weiter|fortfahren)|accept (and|&) (continue|close))$/i;
  const all = [];
  const walk = (root) => { for (const el of root.querySelectorAll("*")) { all.push(el); if (el.shadowRoot) walk(el.shadowRoot); } };
  walk(document);
  // Wirklich sichtbar: Größe, nicht ausgeblendet, nicht durchsichtig, nicht außerhalb des Fensters (Skip-Links!)
  const visible = (el) => {
    const r = el.getBoundingClientRect(); const st = getComputedStyle(el);
    if (r.width <= 8 || r.height <= 8 || st.visibility === "hidden" || st.display === "none") return false;
    if (parseFloat(st.opacity || "1") < 0.1) return false;
    return r.right > 0 && r.bottom > 0 && r.left < innerWidth && r.top < Math.max(innerHeight, document.documentElement.clientHeight) + 2000;
  };
  const inBanner = (el) => {
    for (let e = el, i = 0; e && e.nodeType === 1 && i < 15; i++, e = e.parentElement || (e.getRootNode && e.getRootNode().host)) {
      const sig = `${e.id || ""} ${typeof e.className === "string" ? e.className : ""} ${e.getAttribute("aria-label") || ""} ${e.tagName}`;
      if (CONTAINER.test(sig)) return true;
      const dialog = e.getAttribute("role") === "dialog" || e.getAttribute("role") === "alertdialog" || e.getAttribute("aria-modal") === "true";
      if (dialog && /cookie|datenschutz|privacy|consent|einwillig|tracking/i.test((e.innerText || "").slice(0, 3000))) return true;
    }
    return false;
  };
  const label = (b) => clean(b.innerText || b.value || b.getAttribute("aria-label") || b.title || "");
  const buttons = all.filter((el) => {
    const role = el.getAttribute && el.getAttribute("role");
    const isBtn = el.tagName === "BUTTON" || role === "button" || el.tagName === "A" || (el.tagName === "INPUT" && /^(button|submit)$/i.test(el.type));
    return isBtn && visible(el) && label(el).length <= 60 && !tried.includes(label(el));
  }).sort((a, b) => (a.tagName === "A") - (b.tagName === "A"));  // echte Buttons vor Links
  const pick = (rx) => buttons.find((b) => rx.test(label(b)) && inBanner(b));
  const b = pick(REJECT) || pick(ACCEPT);
  if (!b) return null;
  b.setAttribute("data-jp-cookie", "1");
  return label(b);
}
"""

_REVEAL_JS = r"""
async () => {
  for (const el of document.querySelectorAll('iframe[loading="lazy"], img[loading="lazy"]')) el.loading = "eager";
  const height = () => Math.max(document.body ? document.body.scrollHeight : 0, document.documentElement.scrollHeight);
  let y = 0;
  for (let i = 0; i < 40 && y < height(); i++) {
    y += Math.max(400, window.innerHeight * 0.9);
    window.scrollTo(0, y);
    await new Promise((r) => setTimeout(r, 120));
  }
  window.scrollTo(0, 0);
}
"""

# Autofill über Konten, die wir nicht anfassen (Bot-Erkennung/Kontensperre) – nur Lebenslauf- und Portal-Autofill.
_SOCIAL_RX = re.compile(r"linkedin|indeed|xing|facebook|google|apple|github", re.I)
_LOGIN_RX = re.compile(
    r"sign in|log ?in|anmelden|einloggen|verification code|bestätigungscode|verifizierungscode|one-time|passcode|"
    r"create (an )?account|konto (erstellen|anlegen)|magic link",
    re.I,
)


async def robust_click(loc: Any, wait_ms: int = 6000) -> None:
    """Normal klicken; bei verdeckten/animierten Elementen erzwungen; zuletzt per JavaScript."""
    with contextlib.suppress(Exception):
        await loc.scroll_into_view_if_needed(timeout=3000)
    try:
        await loc.click(timeout=wait_ms)
        return
    except Exception as exc:
        log.debug("Klick fehlgeschlagen (%s), versuche force", exc)
    try:
        await loc.click(timeout=3000, force=True)
        return
    except Exception as exc:
        log.debug("force-Klick fehlgeschlagen (%s), versuche JavaScript", exc)
    await loc.evaluate("e => e.click()", timeout=3000)


async def dismiss_cookie_banners(page: Any, rounds: int = 3) -> list[str]:
    """Schließt Cookie-Banner in allen Frames. Gibt die Beschriftungen der geklickten Buttons zurück."""
    clicked: list[str] = []
    for _ in range(rounds):
        hit = False
        for frame in list(page.frames):
            try:
                # Schon geklickte Beschriftungen ausschließen: Taucht derselbe Button wieder auf, hat er nicht gewirkt.
                text = await frame.evaluate(_COOKIE_JS, clicked)
            except Exception:
                continue
            if not text:
                continue
            loc = frame.locator('[data-jp-cookie="1"]').first
            try:
                await robust_click(loc, wait_ms=4000)
                clicked.append(text)
                hit = True
            except Exception as exc:
                log.info("Cookie-Button '%s' nicht klickbar: %s", text, exc)
            with contextlib.suppress(Exception):
                await frame.evaluate(
                    "() => document.querySelectorAll('[data-jp-cookie]').forEach(e => e.removeAttribute('data-jp-cookie'))"
                )
        if not hit:
            break
        await asyncio.sleep(0.8)
    return clicked


async def reveal_lazy_content(page: Any) -> None:
    """Lazy-iframes (z. B. eingebettete Greenhouse-/Personio-Formulare) laden und Inhalte unterhalb des Sichtbereichs wecken."""
    with contextlib.suppress(Exception):
        await page.evaluate(_REVEAL_JS)
    with contextlib.suppress(Exception):
        await page.wait_for_load_state("networkidle", timeout=4000)
    await asyncio.sleep(0.5)


_CLOSE_JS = r"""
() => {
  const rx = /^(close|schließen|schliessen|cancel|abbrechen|×|✕|x|zurück|back|not now|später|maybe later)$/i;
  const dialogs = document.querySelectorAll('[role="dialog"], [aria-modal="true"], dialog[open], .modal');
  for (const d of dialogs) {
    for (const b of d.querySelectorAll('button, [role="button"], a')) {
      const t = (b.getAttribute("aria-label") || b.innerText || b.title || "").replace(/\s+/g, " ").trim();
      if (rx.test(t)) { b.click(); return t; }
    }
  }
  return null;
}
"""


async def _close_dialog(page: Any) -> None:
    """Login-Dialog eines Autofill-Anbieters schließen: Escape, sonst Schließen/Abbrechen-Button im Dialog."""
    with contextlib.suppress(Exception):
        await page.keyboard.press("Escape")
    await asyncio.sleep(0.5)
    for frame in list(page.frames):
        with contextlib.suppress(Exception):
            if await frame.evaluate(_CLOSE_JS):
                await asyncio.sleep(0.5)
                return


def _filled(state: PageState) -> int:
    return sum(1 for f in state.form_fields if f.get("value") and f["kind"] != "file")


async def _wait_for_parse(page: Any, before: int, seconds: float = 12.0) -> PageState:
    """Wartet, bis ein Lebenslauf-Parser Felder befüllt hat (Anzahl gefüllter Felder steigt und bleibt stabil)."""
    state = await extract_state(page)
    last, stable, waited = _filled(state), 0, 0.0
    while waited < seconds:
        await asyncio.sleep(1.0)
        waited += 1.0
        state = await extract_state(page)
        now = _filled(state)
        stable = stable + 1 if now == last else 0
        last = now
        if now > before and stable >= 2:
            break
    return state


async def try_autofill(page: Any, state: PageState, cv: Path | None) -> tuple[str, Any]:
    """Nutzt Autofill-Buttons der Seite. Gibt (Notiz für den Planer, aktuelle Seite) zurück; Notiz leer = nichts passiert.

    - Lebenslauf-Autofill (Button öffnet Dateiauswahl oder ein Upload-Feld): Lebenslauf hochladen, Parser abwarten.
    - Portal-Autofill (z. B. MyGreenhouse): klicken; verlangt es einen Login, wird abgebrochen und weitergemacht.
    - LinkedIn/Indeed/XING/Google-Autofill wird nie benutzt.
    """
    candidates = [
        b
        for b in state.buttons
        if b.get("autofill") and not b.get("disabled") and not _SOCIAL_RX.search(b["text"])
    ]
    if not candidates:
        return "", page
    button = candidates[0]
    frame = state.frame_for(button["id"]) or page.main_frame
    loc = frame.locator(f'[data-jp="{button["id"]}"]').first
    has_cv = cv is not None and await asyncio.to_thread(cv.exists)
    before = _filled(state)
    known_files = {f["id"] for f in state.fields if f["kind"] == "file"}
    context = page.context
    pages_before = list(context.pages)
    chooser = None
    try:
        async with page.expect_file_chooser(timeout=4000) as fc_info:
            await robust_click(loc, wait_ms=4000)
        chooser = await fc_info.value
    except Exception:
        chooser = None  # Klick ist trotzdem passiert; es öffnete sich nur keine Dateiauswahl

    if chooser is not None:
        if not has_cv:
            return "Autofill-Button gefunden, aber kein Lebenslauf vorhanden", page
        await chooser.set_files([str(cv)])
        after = await _wait_for_parse(page, before)
        return (
            f"Autofill aus dem Lebenslauf über '{button['text']}' genutzt: {_filled(after) - before} Felder vorausgefüllt. "
            "Vorausgefüllte Werte gegen das Profil prüfen und Fehler korrigieren.",
            page,
        )

    await asyncio.sleep(2.0)
    new_pages = [p for p in context.pages if p not in pages_before]
    for popup in new_pages:
        with contextlib.suppress(Exception):
            await popup.wait_for_load_state("domcontentloaded", timeout=10_000)
        text = ""
        with contextlib.suppress(Exception):
            text = await popup.inner_text("body", timeout=3000)
        if _LOGIN_RX.search(text[:4000]) or re.search(r"sign_?in|log_?in|auth|account", popup.url, re.I):
            portal = urlparse(popup.url)
            with contextlib.suppress(Exception):
                await popup.close()
            return (
                f"Autofill '{button['text']}' verlangt einen Login bei {portal.hostname} – übersprungen, Formular "
                f"wird normal ausgefüllt. Tipp: einmal `jobpilot login {portal.scheme}://{portal.hostname}` "
                "ausführen, dann klappt dieses Autofill künftig.",
                page,
            )

    after = await extract_state(page)
    new_upload = next((f for f in after.fields if f["kind"] == "file" and f["id"] not in known_files), None)
    if new_upload and has_cv:
        # Autofill öffnet einen Upload-Dialog/-Schritt: Lebenslauf dort hochladen.
        floc = (
            (after.frame_for(new_upload["id"]) or page.main_frame)
            .locator(f'[data-jp="{new_upload["id"]}"]')
            .first
        )
        with contextlib.suppress(Exception):
            await floc.set_input_files([str(cv)], timeout=10_000)
            after = await _wait_for_parse(page, before)
            return (
                f"Autofill über '{button['text']}': Lebenslauf hochgeladen, {_filled(after) - before} Felder vorausgefüllt.",
                page,
            )
    old_buttons = {b["text"] for b in state.buttons}
    login_hints = [
        f["label"]
        for f in after.fields
        if f["kind"] == "password"
        or _LOGIN_RX.search(f.get("label", ""))
        or "code" in f.get("label", "").lower()
    ]
    login_hints += [
        b["text"] for b in after.buttons if b["text"] not in old_buttons and _LOGIN_RX.search(b["text"])
    ]
    login_hints += [h for h in after.headings if h not in state.headings and _LOGIN_RX.search(h)]
    if login_hints:
        await _close_dialog(page)
        return (
            f"Autofill '{button['text']}' verlangt einen Login ('{login_hints[0][:60]}') – übersprungen, "
            "Formular wird normal ausgefüllt.",
            page,
        )
    if _filled(after) > before:
        return (
            f"Autofill über '{button['text']}' genutzt: {_filled(after) - before} Felder vorausgefüllt. "
            "Vorausgefüllte Werte gegen das Profil prüfen und Fehler korrigieren.",
            page,
        )
    return f"Autofill '{button['text']}' ausprobiert, ohne sichtbare Wirkung.", page
