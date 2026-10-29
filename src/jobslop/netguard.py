"""Netzwerkziele aus fremden Quellen: nur öffentliche Web-Adressen.

Links aus Stellenanzeigen, von Job-Quellen oder per „Stelle per Link“ dürfen jobslop nicht auf Adressen im eigenen
Rechner oder Netz schicken (SSRF): das eigene Dashboard auf 127.0.0.1 (sein Host-Check lässt diese Adresse durch),
den Router, Drucker oder die Metadaten-Adresse einer Cloud-VM (169.254.169.254).

Zwei Stufen:

- ``is_public_url`` prüft nur die Schreibweise (kein DNS, Mikrosekunden – der Crawl prüft damit Tausende Links):
  http(s), keine IP aus privaten/lokalen Netzen, kein ``localhost``, keine Namen ohne Punkt (``http://router``)
  und keine Zahlenformen, die Browser als IPv4 lesen (``http://2130706433``, ``http://127.1``, ``http://0x7f.1``).
  Geprüft wird die Adresse so, wie Chromium sie liest (WHATWG URL, Hosts nach UTS 46) – nicht, wie ``urlsplit`` sie
  liest: für Chromium ist ``http://127.0.0.1\\@example.com`` die 127.0.0.1, ebenso ``http://127.0.0%2e1`` und
  ``http://127.0.0.1．``, und ``http://x.ⓛocalhost`` ist ein localhost-Name.
- ``ensure_public_target`` löst den Namen zusätzlich auf (Engine und Erweiterung vor jedem Schritt) und
  ``public_client`` prüft bei jedem Verbindungsaufbau genau die Adresse, zu der verbunden wird – auch nach
  Weiterleitungen und ohne Lücke für DNS-Rebinding.

``Settings.allow_private_targets`` (nur Umgebung, z. B. für die Tests mit lokalen Formularen) schaltet beides ab.
"""

from __future__ import annotations

import asyncio
import functools
import ipaddress
import logging
import re
import socket
import time
import unicodedata
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote, urlsplit

if TYPE_CHECKING:
    import httpx

log = logging.getLogger(__name__)

WEB_SCHEMES = ("http", "https")
_LOCAL_SUFFIXES = (".localhost", ".local", ".internal", ".home.arpa", ".lan", ".intranet")
_DNS_TTL_S = 60.0
_dns_cache: dict[str, tuple[float, bool]] = {}

_plain_host = re.compile(r"[a-z0-9.-]*").fullmatch
# UTS 46: unsichtbare Zeichen fallen weg (dazu alle der Kategorie Cf), ideografische Punkte trennen wie „.“
_INVISIBLE = frozenset(
    "\u034f\u17b4\u17b5\u180b\u180c\u180d\u180f"
    + "".join(map(chr, range(0xFE00, 0xFE10)))
    + "".join(map(chr, range(0xE0100, 0xE01F0)))
)
_DOTS = str.maketrans({"\u3002": ".", "\uff0e": ".", "\uff61": "."})
# „forbidden domain code points“: einen Host mit diesen Zeichen öffnet kein Browser
_FORBIDDEN_IN_HOSTS = frozenset("".join(map(chr, range(0x21))) + "#%/:<>?@[\\]^|\x7f")


class BlockedTarget(ValueError):
    """Ziel liegt im eigenen Rechner oder Netz (oder ist keine Web-Adresse)."""


IpAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


def _public_ip(ip: IpAddress) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped  # ::ffff:127.0.0.1
    return ip.is_global and not ip.is_multicast


def _ipv4_number(part: str) -> int | None:
    """Ein Teil einer IPv4-Adresse, wie Browser ihn lesen (WHATWG URL): dezimal, 0x… hexadezimal, 0… oktal."""
    try:
        if part.startswith(("0x", "0X")):
            return int(part[2:] or "0", 16)
        if len(part) > 1 and part.startswith("0"):
            return int(part, 8)
        return int(part, 10)
    except ValueError:
        return None


def _browser_ipv4(host: str) -> ipaddress.IPv4Address | bool | None:
    """IPv4 in Browser-Lesart („127.1“, „0x7f.0.0.1“, „2130706433“). None = kein IPv4-Host, False = ungültig."""
    parts = host.split(".")
    if parts and parts[-1] == "":
        parts.pop()  # „127.0.0.1.“
    last = parts[-1] if parts else ""
    if not last or not (last.isdigit() or last.lower().startswith("0x")):
        return None  # endet nicht auf einer Zahl: ein Name
    numbers = [_ipv4_number(p) for p in parts]
    if len(parts) > 4 or any(n is None for n in numbers):
        return False
    values = [n for n in numbers if n is not None]
    if any(n > 255 for n in values[:-1]) or values[-1] >= 256 ** (5 - len(values)):
        return False
    address = values[-1]
    for i, n in enumerate(values[:-1]):
        address += n << (8 * (3 - i))
    return ipaddress.IPv4Address(address)


def _browser_host(host: str) -> str | None:
    """Host, wie Browser ihn lesen (WHATWG URL, UTS 46) – None, wenn ihn kein Browser öffnet.

    Browser dekodieren ``%xx`` im Host und bilden Vollbreite-, eingekreiste und andere Kompatibilitätszeichen auf
    ASCII ab (``１２７.０.０.１``, ``ⓛocalhost``); fremde Schriften bleiben Namen, über die DNS entscheidet.
    """
    if _plain_host(host):
        return host  # der Normalfall (der Crawl prüft Tausende Links): nichts zu dekodieren oder abzubilden
    host = host.strip().lower()
    if ":" in host:
        return host  # IPv6-Literal (urlsplit liefert es ohne Klammern): kein Dekodieren, keine Abbildung
    host = unquote(host)
    if not host.isascii():
        visible = "".join(c for c in host if c not in _INVISIBLE and unicodedata.category(c) != "Cf")
        host = unicodedata.normalize("NFKC", visible).translate(_DOTS).lower()
    if not _FORBIDDEN_IN_HOSTS.isdisjoint(host):
        return None
    return host


def _browser_url(url: str) -> str:
    """Adresse, wie Browser sie lesen, bevor sie den Host suchen: in http(s)-Adressen ist „\\“ ein „/“.

    Ein Backslash beendet den Host wie ein „/“ – ``urlsplit`` liest ``http://127.0.0.1\\@example.com`` dagegen als
    example.com mit Benutzername. Steuerzeichen am Anfang sowie Tab und Zeilenumbrüche entfernt ``urlsplit`` selbst
    wie ein Browser (seit Python 3.11.4); bleiben welche im Host, gilt er nicht als öffentlich.
    """
    return url.strip().replace("\\", "/")


def is_public_host(host: str) -> bool:
    """Name oder IP-Literal, ohne DNS: kann das ein öffentlicher Server sein?"""
    mapped = _browser_host(host)
    if mapped is None:
        return False
    host = mapped.rstrip(".")
    if not host or host == "localhost" or host.endswith(_LOCAL_SUFFIXES):
        return False
    if ":" in host:  # IPv6-Literal (urlsplit liefert es ohne Klammern)
        try:
            return _public_ip(ipaddress.IPv6Address(host))
        except ValueError:
            return False  # z. B. mit Zonen-ID (fe80::1%eth0)
    v4 = _browser_ipv4(host)
    if v4 is False:
        return False
    if isinstance(v4, ipaddress.IPv4Address):
        return _public_ip(v4)
    return "." in host  # „http://router“, „http://intranet“: Namen ohne Punkt löst das lokale Netz auf


def is_public_url(url: str) -> bool:
    """http(s)-Adresse, deren Host öffentlich sein kann – ohne DNS-Abfrage, gelesen wie im Browser."""
    try:
        parts = urlsplit(_browser_url(url))
        host = parts.hostname or ""
    except ValueError:
        return False
    return parts.scheme.lower() in WEB_SCHEMES and is_public_host(host)


def _addresses(infos: list[Any]) -> list[IpAddress]:
    return [ipaddress.ip_address(str(info[4][0]).split("%")[0]) for info in infos]


async def _resolves_public(host: str) -> bool:
    if (hit := _dns_cache.get(host)) and time.monotonic() - hit[0] < _DNS_TTL_S:
        return hit[1]
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except OSError:
        # Nicht auflösbar: Der Browser kommt dort auch nicht hin. Kein Grund zu blockieren – nur nicht merken.
        return True
    public = bool(infos) and all(_public_ip(ip) for ip in _addresses(infos))
    _dns_cache[host] = (time.monotonic(), public)
    return public


async def ensure_public_target(url: str, settings: Any) -> None:
    """Wirft ``BlockedTarget``, wenn die Adresse (auch nach DNS-Auflösung) im eigenen Rechner oder Netz liegt."""
    if getattr(settings, "allow_private_targets", False):
        return
    if not is_public_url(url):
        raise BlockedTarget(f"Adresse im eigenen Rechner oder Netz – jobslop öffnet sie nicht: {url[:120]}")
    # Aufgelöst wird der Name, den auch der Browser auflöst (nach is_public_url gibt es ihn immer)
    host = _browser_host(urlsplit(_browser_url(url)).hostname or "") or ""
    if not await _resolves_public(host):
        raise BlockedTarget(
            f"{host} zeigt auf eine Adresse im eigenen Rechner oder Netz – jobslop öffnet sie nicht"
        )


# --------------------------------------------------------------------------- HTTP-Client nur für öffentliche Ziele
# httpx/httpcore erst hier laden: die Engine (und damit jeder CLI-Start) importiert dieses Modul, braucht den Client
# aber nie – das sparte ~250 ms beim Start von `jobslop`.


@functools.cache
def _backend_class() -> type:
    import httpcore

    class _PublicOnlyBackend(httpcore.AsyncNetworkBackend):
        """Löst den Namen selbst auf, prüft jede Adresse und verbindet zu genau der geprüften – eine zweite
        Auflösung (DNS-Rebinding) gibt es nicht. TLS prüft weiter gegen den Namen (SNI und Zertifikat vom Ursprung)."""

        def __init__(self) -> None:
            self._inner = httpcore.AnyIOBackend()

        async def connect_tcp(
            self,
            host: str,
            port: int,
            timeout: float | None = None,
            local_address: str | None = None,
            socket_options: Any = None,
        ) -> httpcore.AsyncNetworkStream:
            if not is_public_host(host):
                raise BlockedTarget(f"{host} liegt im eigenen Rechner oder Netz")
            infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
            addresses = _addresses(infos)
            if not addresses or not all(_public_ip(ip) for ip in addresses):
                raise BlockedTarget(f"{host} zeigt auf eine Adresse im eigenen Rechner oder Netz")
            return await self._inner.connect_tcp(
                str(addresses[0]),
                port,
                timeout=timeout,
                local_address=local_address,
                socket_options=socket_options,
            )

        async def connect_unix_socket(
            self, path: str, timeout: float | None = None, socket_options: Any = None
        ) -> httpcore.AsyncNetworkStream:
            raise BlockedTarget("Unix-Sockets sind kein Web-Ziel")

        async def sleep(self, seconds: float) -> None:
            await self._inner.sleep(seconds)

    return _PublicOnlyBackend


def public_client(*, timeout: float = 20.0, max_redirects: int = 5, **kwargs: Any) -> httpx.AsyncClient:
    """httpx-Client, der nur öffentliche Adressen erreicht – jede Verbindung, auch nach Weiterleitungen.

    ``trust_env=False``: ein Proxy aus der Umgebung würde die Prüfung umgehen (verbunden würde zum Proxy).
    """
    import httpcore
    import httpx

    transport = httpx.AsyncHTTPTransport(retries=0)
    # httpx reicht kein eigenes Netzwerk-Backend durch; der Pool ist seit httpx 0.18 unverändert ``_pool``
    transport._pool = httpcore.AsyncConnectionPool(
        ssl_context=httpx.create_ssl_context(),
        max_connections=10,
        network_backend=_backend_class()(),
    )
    return httpx.AsyncClient(
        transport=transport,
        timeout=timeout,
        follow_redirects=True,
        max_redirects=max_redirects,
        trust_env=False,
        **kwargs,
    )


async def read_limited(response: httpx.Response, max_bytes: int) -> bytes:
    """Antwort lesen, aber höchstens ``max_bytes`` (der Rest wird verworfen, die Verbindung geschlossen)."""
    chunks: list[bytes] = []
    size = 0
    async for chunk in response.aiter_bytes():
        chunks.append(chunk[: max_bytes - size])
        size += len(chunk)
        if size >= max_bytes:
            break
    return b"".join(chunks)
