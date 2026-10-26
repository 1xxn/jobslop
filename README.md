# jobpilot

Lokaler Bewerbungs-Autopilot. jobpilot sucht Stellen auf den Karriereseiten der Firmen und führt eine History mit, die zeigt, was neu ist, was sich geändert hat und was geschlossen wurde. Die Stellen werden nach deinem Profil bewertet. Danach füllt jobpilot die Bewerbungsformulare in einem echten Browser aus – egal welches Layout – und sendet sie je nach Modus selbst ab oder nach deiner Freigabe.

**Claude läuft über dein Claude-Abo (Pro/Max) via Claude Code.** Es gibt keinen API-Schlüssel und keine API-Kosten. jobpilot startet für jeden Denkschritt das lokal installierte `claude` im Headless-Modus und entfernt dabei `ANTHROPIC_API_KEY` aus der Umgebung, damit garantiert nichts über die API abgerechnet wird.

Startbestand: die 141 Stellen aus der Recherche vom 26.10.2026. Die 11 Stellen, auf die du dich laut LinkedIn schon beworben hast, sind als „beworben“ markiert und werden übersprungen.

```
┌──────────────┐   ┌───────────────┐   ┌──────────────┐   ┌────────────────────────────┐
│ Crawler       │──▶│ SQLite        │──▶│ Queue/Guard   │──▶│ Bewerbungs-Engine          │
│ Greenhouse,   │   │ Jobs+History, │   │ Ausschlüsse,  │   │ Playwright: Formular lesen  │
│ Ashby, Lever, │   │ Bewerbungen,  │   │ Dubletten,    │   │ Claude Code: Felder planen  │
│ SmartRecr.,   │   │ Antwortbank   │   │ Firmen-Limit  │   │ Executor: ausfüllen         │
│ Personio,     │   └───────────────┘   └──────────────┘   │ Review → Absenden → Beleg   │
│ Workday, AWS, │          ▲                                └────────────────────────────┘
│ beliebige     │          │            CLI (Typer/Rich) + Web-Dashboard (FastAPI)
│ Karriereseiten│          └──────────── Rückfragen, Freigaben, Screenshots, History
└──────────────┘
```

## Stack

- **Python 3.12+** mit **uv** (Paketverwaltung, Lockfile; uv lädt Python bei Bedarf selbst)
- **Playwright** (Chromium, persistentes Browserprofil, Frames, Shadow DOM, Datei-Uploads)
- **Claude Code headless** (`claude -p`) mit deinem Abo-Login: **Structured Outputs** über `--json-schema` (schema-validierte Antworten), eigener System-Prompt mit **Prompt-Cache-Grenze** (Profil und Lebenslauf werden gecacht, die Antwortbank nicht), **Vision** über das Read-Tool (Screenshots mit eingezeichneten Element-IDs) als Rückfallebene. Jeder Aufruf ist isoliert: keine Tools außer Read, keine MCP-Server, keine Einstellungen, keine gespeicherte Sitzung.
- **pypdf** liest den Lebenslauf einmal lokal als Text (spart Kontingent; bei Bild-PDFs liest Claude die Datei selbst)
- **SQLAlchemy 2** + SQLite (WAL) für Jobs, Snapshots, Bewerbungen, Ereignisse und Antwortbank
- **httpx** + **tenacity** für die Job-Board-APIs, **Typer/Rich** für die CLI, **FastAPI/Jinja** für das Dashboard
- **pytest** mit echtem Chromium gegen lokale Testformulare, einer `claude`-Attrappe für die CLI-Anbindung, **respx** für API-Mocks, **ruff**

## Installation (Windows, PowerShell)

```powershell
# 1. Claude Code (nativ, aktualisiert sich selbst) – alternativ: winget install Anthropic.ClaudeCode
irm https://claude.ai/install.ps1 | iex
# neues Terminal öffnen:
claude            # einmal starten und mit deinem Claude-Konto (Pro/Max) einloggen, dann /exit
claude --version  # muss eine Versionsnummer zeigen

# 2. uv (Python-Paketmanager)
winget install astral-sh.uv
# neues Terminal öffnen

# 3. jobpilot
cd $HOME\Desktop\srejob
uv sync
uv run playwright install chromium
uv run jobpilot init                     # legt %USERPROFILE%\.jobpilot an und importiert die Startliste
Copy-Item <Pfad>\Max_Mustermann_CV_SRE.pdf $HOME\.jobpilot\
notepad $HOME\.jobpilot\profile.yaml     # TODO-Felder ausfüllen (Gehalt, Kündigungsfrist, Starttermin …)
uv run jobpilot doctor                   # prüft Profil, Lebenslauf, Claude-Login, Browser, Datenbank
```

macOS/Linux: `curl -fsSL https://claude.ai/install.sh | bash`, uv per `curl -LsSf https://astral.sh/uv/install.sh | sh`, sonst identisch.

`jobpilot doctor` zeigt eine Zeile wie `✓ Claude Code 2.1.310 angemeldet (claude.ai · max)`. Steht dort „per api_key angemeldet“, in `claude` einmal `/logout` und `/login` mit dem Claude-Konto ausführen.

Das Profil ist schon mit den Daten aus deinem Lebenslauf befüllt. Für einen anderen Lebenslauf: `uv run jobpilot profile import-cv lebenslauf.pdf`.

## Typischer Ablauf

```powershell
uv run jobpilot crawl                   # alle Quellen neu abfragen, Änderungen landen in der History
uv run jobpilot jobs list --top 25      # Priorität: SRE › Platform › DevOps › Cloud › System
uv run jobpilot queue add --top 10      # beste offene Stellen ohne Bewerbung einreihen
uv run jobpilot apply --queue --mode dry-run --max 2   # erster Test: nur ausfüllen, nicht absenden
uv run jobpilot apply --queue           # Review-Modus: vor jedem Absenden fragt jobpilot nach
uv run jobpilot dashboard               # alles im Browser unter http://127.0.0.1:8765
```

### Modi

| Modus | Verhalten |
|---|---|
| `dry-run` | Füllt alles aus, sendet nie ab. Das Fenster bleibt zur Kontrolle offen. |
| `review` (Standard) | Füllt aus, zeigt dir alle Werte und wartet auf „absenden“, „ich sende selbst“ oder „nicht absenden“. |
| `auto` | Sendet selbst ab, wenn jedes Pflichtfeld gefüllt ist und kein Wert unsicher ist. Sonst fragt jobpilot oder parkt die Bewerbung. |

Für unbeaufsichtigte Läufe (z. B. nachts über die Aufgabenplanung): `jobpilot apply --queue --mode auto --unattended`. Offene Fragen werden dann als `needs_input` geparkt und im Dashboard beantwortet. Beim nächsten Lauf werden die Antworten automatisch genutzt. Claude Code muss dafür nur einmal eingeloggt sein; der Login bleibt gespeichert.

## Abo-Kontingent

Alles, was jobpilot an Claude schickt, zählt zum Nutzungslimit deines Claude-Abos (gemeinsam mit claude.ai und Claude Code).

| Schritt | Modell | Aufrufe |
|---|---|---|
| Formularseite planen | `sonnet` | 1 pro Seite, typisch 2–6 pro Bewerbung |
| Anschreiben (nur wenn verlangt und `cover_letter: auto`) | `sonnet` | 1 |
| Stellen bewerten (`crawl`, `jobs enrich`) | `haiku` | 1 pro 6 Stellen |
| Generische Karriereseite auslesen | `haiku` | 1 pro Seite |

Echte Testläufe: Ein einseitiges Greenhouse-artiges Formular brauchte 2 Aufrufe in 14 Sekunden, eine zweistufige Bewerbung mit Anzeige, neuem Tab und iframe 3 Aufrufe in 14 Sekunden. Profil und Lebenslauf kamen dabei jeweils aus dem Prompt-Cache.

Ist das Limit erreicht, stoppt jobpilot sauber: Die laufende Bewerbung wird **nicht** abgesendet, bekommt den Status `paused` und bleibt in der Warteschlange. Die restlichen Stellen werden nicht angefasst. Nach dem Reset einfach `jobpilot apply --queue` erneut starten. Beim Crawlen bleiben nicht bewertete Stellen offen; `jobpilot jobs enrich` holt das später nach.

Stellschrauben (Umgebung oder `.env`, siehe `.env.example`): `JOBPILOT_LLM_MODEL=haiku` spart Kontingent, `opus` ist gründlicher. `JOBPILOT_CLAUDE_PARALLEL` (Standard 2) begrenzt gleichzeitige Aufrufe. `JOBPILOT_VISION=never` verzichtet auf Screenshots.

## Wie das Ausfüllen funktioniert

1. **Erfassen**: Ein Skript läuft in jedem Frame der Seite, auch in iframes eingebetteter Bewerbungssysteme und in offenen Shadow Roots. Es findet Textfelder, Selects, Radio- und Checkbox-Gruppen, Custom-Dropdowns (`role=combobox`), Rich-Text-Felder und versteckte Datei-Inputs. Für jedes Feld ermittelt es Label (aria-labelledby, label[for], umgebender Text, Legend), Pflicht-Status, Optionen und aktuellen Wert und vergibt eine stabile ID.
2. **Planen**: Claude Code bekommt die Felder, die Buttons, Fehlermeldungen und den Stellentext; Profil und Lebenslauf stehen im gecachten System-Prompt. Zurück kommt ein schema-validierter Plan: pro Feld eine Aktion mit Wert, Quelle und Sicherheit, dazu offene Fragen und der nächste Button.
3. **Ausfüllen**: Der Executor füllt jeden Feldtyp passend aus: native Felder, Masken (tippt, wenn `fill` umformatiert wird), Custom-Dropdowns (öffnen, tippen, beste Option wählen), visuell versteckte Radios (über das Label), Uploads (Input oder File-Chooser). Jeder Wert wird zurückgelesen und geprüft.
4. **Mehrere Schritte**: Bei „Weiter“, „Bewerben“ in neuem Tab, Seitenwechseln im iframe oder Validierungsfehlern wird die Seite neu erfasst und neu geplant.
5. **Vision-Fallback**: Wenn eine Seite ohne erkennbare Felder hängen bleibt, legt jobpilot Screenshots mit eingezeichneten IDs in den Arbeitsordner des Aufrufs, und Claude liest sie mit dem Read-Tool.
6. **Beleg**: Für jede Bewerbung speichert jobpilot Screenshots pro Schritt, vor und nach dem Absenden, alle Pläne als JSON, die ausgefüllten Werte und gegebenenfalls das Anschreiben als PDF unter `~/.jobpilot/artifacts/`.

### Schutzregeln

- **Nichts erfinden**: Claude darf nur Fakten aus Profil, Lebenslauf und Antwortbank verwenden. Fehlt eine Pflichtangabe, fragt jobpilot dich einmal und merkt sich die Antwort. TODO-Felder gelten als unbekannt.
- **Kein doppeltes Absenden**: Nach einem Klick auf „Absenden“ wird nur erneut geklickt, wenn seitdem etwas korrigiert wurde. Sonst wird die Bewerbung zur Prüfung geparkt.
- **Dubletten und Limits**: Dieselbe Stelle über eine andere Quelle wird erkannt. Pro Firma gibt es höchstens 2 Bewerbungen in 30 Tagen (in `search.toml` änderbar). Ausschlüsse für Firmen, Stellen, Titel-Regex und URL-Teile greifen vor jedem Lauf.
- **CAPTCHAs, Logins, Konto-Anlage** (z. B. Workday): jobpilot übergibt an dich und macht danach weiter. Der Login bleibt im jobpilot-Browserprofil gespeichert. Einmalig vorab geht das auch mit `jobpilot login <url>`.
- **LinkedIn und Indeed** werden nicht automatisiert, weil beide Automatisierung erkennen und Konten sperren. Bei solchen Links öffnet jobpilot die Seite, du klickst auf „Bewerben“, und jobpilot übernimmt auf der Firmenseite. Beim Crawlen werden Einträge aus der Startliste nach Möglichkeit auf die direkte Firmen-URL umgestellt.

## Crawling und History

Die Quellen stehen in `~/.jobpilot/search.toml`:

- **Greenhouse, Ashby, Lever, SmartRecruiters, Personio, Workday**: öffentliche Job-Board-APIs der Bewerbungssysteme. Ein neues Unternehmen fügst du hinzu, indem du den Board-Namen aus der URL der Karriereseite einträgst, z. B. `job-boards.greenhouse.io/<board>`.
- **amazon.jobs**: Suchabfragen für Deutschland.
- **Beliebige Karriereseiten** (`[[sources.generic]]`): Die Seite wird im Browser gerendert, und Claude liest die Stellen heraus.

Filter (Titel, Ausschlussbegriffe, Berlin oder Remote in Deutschland), Segmente und Stack-Begriffe sind dort ebenfalls einstellbar. Jeder Lauf schreibt Snapshots: `new`, `updated` (mit Diff), `closed`, `reopened`. Eine Stelle gilt nur dann als geschlossen, wenn ihre Quelle erfolgreich abgefragt wurde und die Stelle darin fehlt. Fällt eine Quelle aus, wird also nichts geschlossen.

```powershell
uv run jobpilot history                 # alle Läufe
uv run jobpilot history 7               # Änderungen in Lauf 7
uv run jobpilot jobs show 42            # Stelle mit Snapshot-History und Bewerbungen
uv run jobpilot jobs enrich             # Claude liest die Anforderungen: echtes Level, Stack-Match, Hinweise
```

## Befehle

| Befehl | Zweck |
|---|---|
| `init`, `doctor` | Einrichten, Selbsttest (inkl. Claude-Code-Login) |
| `profile show`, `profile import-cv PDF` | Profil anzeigen bzw. aus Lebenslauf befüllen |
| `crawl [-s greenhouse]`, `history [ID]` | Neu crawlen, History ansehen |
| `jobs list/show/enrich` | Stellen filtern, Details, Bewertung durch Claude |
| `queue add [IDs] [--top N]`, `queue list/remove/clear` | Warteschlange |
| `apply [IDs] [--queue] [--mode] [--max] [--unattended] [--via-dashboard] [--offline]` | Bewerben |
| `apps list/show` | Bewerbungen, Ablaufprotokoll, offene Fragen |
| `mark applied/interview/rejected/offer JOB` | Status von Hand setzen (z. B. Easy Apply selbst gemacht) |
| `exclude add company/job/title/url WERT`, `exclude list/remove` | Ausschlüsse |
| `answers list/add/remove` | Antwortbank |
| `login URL` | Einmal bei einem Bewerbungsportal einloggen |
| `dashboard`, `export --format csv/json` | Web-Oberfläche, Export |

`--offline` arbeitet ganz ohne Claude mit einem Regel-Planer, der nur Standardfelder (Name, Kontakt, Lebenslauf-Upload, Datenschutz) ausfüllt.

Das Dashboard zeigt Rückfragen und Freigaben live an. Bewerbungsläufe lassen sich dort starten; der Browser öffnet sich auf deinem Rechner.

## Daten

Alles liegt lokal unter `~/.jobpilot/` (änderbar über `JOBPILOT_HOME`): `profile.yaml`, `search.toml`, `jobpilot.db`, `artifacts/` (Belege), `browser-profile/` (Logins), `claude-work/` (temporäre Arbeitsordner der Claude-Aufrufe, werden sofort gelöscht). An Claude gehen nur die Inhalte, die für den jeweiligen Schritt nötig sind: Profil, Lebenslauf-Text, Stellentext und Formularinhalt.

## Fehlersuche

| Meldung | Lösung |
|---|---|
| `Claude Code wurde nicht gefunden` | Neues Terminal öffnen (PATH), `claude --version` prüfen, sonst `JOBPILOT_CLAUDE_BIN=C:\Users\<du>\.local\bin\claude.exe` setzen |
| `nicht angemeldet` / `per api_key angemeldet` | `claude` starten, `/login` mit dem Claude-Konto |
| Status `paused` | Abo-Limit erreicht – nach dem Reset `jobpilot apply --queue` |
| Claude antwortet nicht | `JOBPILOT_CLAUDE_TIMEOUT_S` erhöhen; mit `JOBPILOT_KEEP_LLM_WORKDIRS=true` bleiben Prompt und Dateien jedes Aufrufs unter `claude-work/` liegen |

## Grenzen

- Die ersten Bewerbungen solltest du im Review-Modus begleiten. Jedes Portal ist anders, und die Antwortbank füllt sich erst mit der Zeit.
- Portale mit Kontopflicht (Workday, SuccessFactors) brauchen beim ersten Mal dich für die Registrierung.
- CAPTCHAs löst jobpilot bewusst nicht, sondern übergibt sie an dich.
- Ein Claude-Code-Aufruf hat einige Sekunden Startzeit. Eine Bewerbung dauert deshalb eher Minuten als Sekunden – dafür ohne API-Kosten.

## Entwicklung

```powershell
uv run pytest                                   # 32 Tests, davon 8 mit echtem Chromium gegen lokale Testformulare
$env:JOBPILOT_LIVE="1"; uv run pytest -m live   # 2 Tests gegen das echte Claude Code (verbraucht etwas Abo-Kontingent)
uv run ruff check src tests
```

Die Tests für die Claude-Code-Anbindung nutzen eine `claude`-Attrappe (`tests/fake_claude.py`) und laufen unter Windows nicht (Shebang-Skript); alles andere läuft überall.
