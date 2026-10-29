"""Geheimnisse im Schlüsselbund des Betriebssystems statt im Klartext in ``settings.toml``.

Windows-Anmeldeinformationsverwaltung, macOS-Schlüsselbund oder Secret Service (GNOME Keyring, KWallet) – über das
Paket ``keyring``. Bisher nur das App-Passwort des Postfachs. Gibt es keinen Schlüsselbund (Linux ohne Secret Service,
eine Sitzung ohne D-Bus), bleibt es wie bisher in ``settings.toml``; der jobslop-Ordner ist dann nur für dich lesbar.
Das Token der Browser-Erweiterung bleibt eine Datei: die Erweiterung liest es aus ihrer ``config.js``.

``keyring`` wird erst beim ersten Zugriff geladen (die Suche nach Backends kostet beim Start sonst Zeit).
"""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)

SERVICE = "jobslop"


def _account(home: Path, name: str) -> str:
    # Pro jobslop-Ordner: ein Demo- oder Testordner liest nie das Passwort deines echten
    return f"{name}:{home.resolve()}"


def store(home: Path, name: str, secret: str) -> bool:
    """Ablegen (leer = entfernen). False, wenn kein Schlüsselbund verfügbar ist – dann bleibt es in der Datei."""
    try:
        import keyring
        from keyring.errors import PasswordDeleteError

        if secret:
            keyring.set_password(SERVICE, _account(home, name), secret)
        else:
            try:
                keyring.delete_password(SERVICE, _account(home, name))
            except PasswordDeleteError:
                pass  # war nicht da
        return True
    except Exception as exc:  # kein Backend, gesperrter Schlüsselbund, D-Bus fehlt …
        log.info("Kein Schlüsselbund verfügbar (%s) – das Passwort bleibt in settings.toml", type(exc).__name__)
        return False


def load(home: Path, name: str) -> str:
    try:
        import keyring

        return keyring.get_password(SERVICE, _account(home, name)) or ""
    except Exception as exc:
        log.warning("Schlüsselbund nicht lesbar (%s)", type(exc).__name__)
        return ""
