"""Seiten, die jobslop nicht selbst im eigenen Browser bedient – und warum."""

from __future__ import annotations

from urllib.parse import urlparse

# Portale mit Konto und Automatisierungs-Erkennung: Übergabe an dich (bzw. die Browser-Erweiterung)
HANDOFF_HOSTS = ("linkedin.com", "indeed.com", "indeed.de")
# Hinter einer Bot-Abfrage (Cloudflare), die im automatisierten Browser endlos hängt: nur in deinem Browser
BROWSER_ONLY_HOSTS = ("himalayas.app", "glassdoor.")


def host_of(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def is_handoff(url: str) -> bool:
    return any(h in host_of(url) for h in HANDOFF_HOSTS)


def is_browser_only(url: str) -> bool:
    return any(h in host_of(url) for h in BROWSER_ONLY_HOSTS)
