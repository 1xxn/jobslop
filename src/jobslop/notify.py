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
    sent = 0
    async with httpx.AsyncClient(timeout=10) as client:
        if settings.notify_ntfy_url:
            headers = {"Title": _ascii(title), "Priority": priority, "Tags": "briefcase"}
            if url:
                headers["Click"] = url
            try:
                r = await client.post(
                    settings.notify_ntfy_url, content=message.encode("utf-8"), headers=headers
                )
                r.raise_for_status()
                sent += 1
            except httpx.HTTPError as exc:
                log.warning("ntfy-Benachrichtigung fehlgeschlagen: %s", exc)
        if settings.notify_webhook_url:
            text = f"**{title}**\n{message}" + (f"\n{url}" if url else "")
            payload = {"content": text, "text": text, "title": title, "message": message, "url": url}
            try:
                r = await client.post(settings.notify_webhook_url, json=payload)
                r.raise_for_status()
                sent += 1
            except httpx.HTTPError as exc:
                log.warning("Webhook-Benachrichtigung fehlgeschlagen: %s", exc)
    return sent


def _ascii(text: str) -> str:
    """HTTP-Header sind ASCII – Umlaute als RFC-2047-Wort kodieren (versteht ntfy)."""
    if text.isascii():
        return text
    return "=?UTF-8?B?" + base64.b64encode(text.encode("utf-8")).decode("ascii") + "?="
