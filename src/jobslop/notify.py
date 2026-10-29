"""Benachrichtigungen nach außen: ntfy (Push aufs Handy) und Webhooks (Discord, Slack, Home Assistant …).

Browser-Benachrichtigungen erzeugt das Dashboard selbst. Fehler beim Senden werden nur geloggt.
"""

from __future__ import annotations

import base64
import logging

import httpx

from .config import Settings

log = logging.getLogger(__name__)


async def notify(
    settings: Settings, title: str, message: str, *, url: str = "", priority: str = "default"
) -> int:
    """Sendet an alle konfigurierten Kanäle. Gibt die Anzahl erfolgreicher Zustellungen zurück."""
    if settings.demo:
        log.info("Demo-Modus – Benachrichtigung nicht gesendet: %s", title)
        return 0
    sent = 0
    # Ziele stellst du selbst ein – auch im eigenen Netz (Home Assistant, eigener ntfy-Server); nur http(s)
    ntfy = settings.notify_ntfy_url if _web(settings.notify_ntfy_url) else ""
    webhook = settings.notify_webhook_url if _web(settings.notify_webhook_url) else ""
    async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
        if ntfy:
            headers = {"Title": _ascii(title), "Priority": priority, "Tags": "briefcase"}
            if url:
                headers["Click"] = url
            try:
                r = await client.post(ntfy, content=message.encode("utf-8"), headers=headers)
                r.raise_for_status()
                sent += 1
            except httpx.HTTPError as exc:
                log.warning("ntfy-Benachrichtigung fehlgeschlagen: %s", exc)
        if webhook:
            text = f"**{title}**\n{message}" + (f"\n{url}" if url else "")
            payload = {"content": text, "text": text, "title": title, "message": message, "url": url}
            try:
                r = await client.post(webhook, json=payload)
                r.raise_for_status()
                sent += 1
            except httpx.HTTPError as exc:
                log.warning("Webhook-Benachrichtigung fehlgeschlagen: %s", exc)
    return sent


def _web(url: str) -> bool:
    return url.strip().lower().startswith(("https://", "http://"))


def _ascii(text: str) -> str:
    """HTTP-Header sind ASCII – Umlaute als RFC-2047-Wort kodieren (versteht ntfy)."""
    if text.isascii():
        return text
    return "=?UTF-8?B?" + base64.b64encode(text.encode("utf-8")).decode("ascii") + "?="
