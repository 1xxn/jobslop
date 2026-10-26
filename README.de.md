<div align="center">

<img src="frontend/public/favicon.svg" width="72" height="72" alt="jobslop Logo">

# jobslop

**Ein lokaler, KI‑gesteuerter Bewerbungs‑Autopilot – zusammengesloppt, aber erstaunlich sorgfältig.**

jobslop findet Stellen, bewertet sie gegen dein Profil und füllt Bewerbungsformulare in einem echten Browser aus.
Es denkt mit **deinem eigenen Claude‑Abo** (über Claude Code), läuft **komplett auf deinem Rechner**
und fragt, bevor es etwas absendet.

[English](README.md) · [Schnellstart](#schnellstart) · [So funktioniert’s](#so-funktionierts) · [FAQ](#faq)

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/screenshots/overview-dark.png">
  <img alt="jobslop Dashboard" src="docs/screenshots/overview-light.png" width="100%">
</picture>

</div>

## Warum

Bewerben ist zu 10 % Entscheiden und zu 90 % Copy‑Paste derselben Antworten in leicht unterschiedliche Formulare.
jobslop übernimmt das Copy‑Paste. Das Entscheiden bleibt bei dir.

- **Findet Stellen** auf Jobbörsen (Arbeitnow, Himalayas), Firmen‑Boards (Greenhouse, Ashby, Lever,
  SmartRecruiters, Personio, Workday, amazon.jobs) und beliebigen Karriereseiten – ohne Dubletten, mit Verlauf.
- **Bewertet ehrlich.** Claude liest die Anforderungen und sagt dir, was passt, was nicht und worauf du achten
  solltest (Rufbereitschaft, Deutsch C2, „Senior“ im Mid‑Gewand …).
- **Bewirbt sich im echten Browser.** Iframes, Shadow DOM, eigene Dropdowns, mehrseitige Formulare,
  Cookie‑Banner, „Mit Lebenslauf ausfüllen“‑Buttons und Uploads – auf praktisch jedem Formular.
- **Erfindet nichts.** Es nutzt nur Angaben aus Profil, Lebenslauf und Antwortbank. Fehlt etwas, fragt es dich –
  und merkt sich die Antwort.
- **Behält den Überblick.** Kanban‑Pipeline von *beworben* bis *Angebot*, Nachfass‑Erinnerungen, Notizen,
  Screenshots jedes Schritts, Statistik.

## Schnellstart

Du brauchst ein **Claude‑Pro‑ oder ‑Max‑Abo**. jobslop nutzt es über [Claude Code](https://claude.com/claude-code) –
ohne API‑Schlüssel und ohne API‑Kosten.

**Windows (PowerShell)**

```powershell
irm https://raw.githubusercontent.com/1xxn/jobslop/main/install.ps1 | iex
```

**macOS / Linux**

```bash
curl -fsSL https://raw.githubusercontent.com/1xxn/jobslop/main/install.sh | sh
```

Das Skript richtet [uv](https://docs.astral.sh/uv/) ein, bietet die Installation von Claude Code an, installiert
jobslop samt Browser und startet es. Danach genügt:

```bash
jobslop
```

Das Dashboard öffnet sich unter `http://127.0.0.1:8765`. Beim ersten Start führt dich die Einrichtung durch alles:
Claude verbinden, Lebenslauf hochladen (füllt dein Profil), Suche wählen. Keine Konfigurationsdateien.

<details>
<summary>Manuell / aus dem Quellcode</summary>

```bash
git clone https://github.com/1xxn/jobslop.git
cd jobslop
uv sync
uv run jobslop install-browser
uv run jobslop
```

</details>

## So funktioniert’s

1. **Suchen** – Jobbörsen‑APIs und Karriereseiten werden abgefragt, nach deinen Rollen, Orten und Ausschlüssen
   gefiltert, Dubletten erkannt und mit Verlauf gespeichert.
2. **Bewerten** – Regel‑Score (Rollenpriorität, Stack‑Passung, Firma, Level, Ort) plus Claude‑Einschätzung der
   tatsächlichen Anforderungen.
3. **Bewerben** – jobslop öffnet die Anzeige in einem eigenen Chromium‑Profil, schließt Cookie‑Banner, nutzt
   Autofill‑Buttons, liest jedes Feld (auch in iframes und Shadow DOM) und lässt Claude die Werte planen.
   Der Executor füllt jeden Feldtyp passend aus, prüft ihn, geht durch mehrseitige Formulare und fragt –
   je nach Modus – vor dem Absenden. Jeder Schritt wird mit Screenshots protokolliert.

Mehr dazu: [docs/architecture.md](docs/architecture.md) · Einstellungen: [docs/configuration.md](docs/configuration.md)

### Modi

| Modus | Verhalten |
|---|---|
| **Mit Freigabe** (Standard) | Füllt alles aus und wartet im Dashboard auf „Absenden“, „Ich sende selbst“ oder „Nicht absenden“. |
| **Automatisch** | Sendet selbst ab, wenn jedes Pflichtfeld sicher gefüllt ist – sonst fragt jobslop. |
| **Testlauf** | Füllt nur aus, sendet nie ab. |

## Datenschutz & Verantwortung

- **Alles lokal.** Datenbank, Profil, Lebenslauf, Screenshots liegen in `~/.jobslop`. Das Dashboard lauscht nur auf
  `127.0.0.1` und weist Anfragen fremder Webseiten ab.
- **Deine Daten verlassen den Rechner** nur in Richtung Claude (über dein Abo) und in die Formulare der
  Bewerbungen, die du startest.
- **Du bist verantwortlich für das, was in deinem Namen verschickt wird.** Starte mit *Testlauf* oder *Mit Freigabe*
  und beachte die Nutzungsbedingungen der Seiten. LinkedIn und Indeed werden bewusst nicht automatisiert,
  CAPTCHAs nicht gelöst, Logins übergibt jobslop dir.

## FAQ

**Warum kein Docker?** jobslop steuert einen *sichtbaren* Browser, damit du bei CAPTCHAs, Logins und der Endkontrolle
eingreifen kannst, und nutzt deinen lokalen Claude‑Code‑Login. Im Container bräuchte beides Umwege (VNC, gemountete
Zugangsdaten) ohne echten Vorteil – die native Installation ist ein Befehl.

**Wie viel Claude‑Kontingent braucht das?** Eine Bewerbung meist 2–6 Aufrufe (Sonnet). Bewerten läuft mit Haiku,
6 Stellen pro Aufruf, höchstens 60 Stellen pro Suche. Ist das Limit erreicht, pausiert jobslop sauber und macht nach
dem Reset weiter.

**Nur für IT‑Jobs?** Nein – Rollen, Stichwörter, Orte und Quellen sind frei einstellbar; die Einrichtung hat Vorlagen
für mehrere Bereiche.

**Ich komme von „jobpilot“.** Beim ersten Start zieht jobslop `~/.jobpilot` automatisch nach `~/.jobslop` um –
inklusive Datenbank, Profil und Browser‑Logins. `JOBPILOT_*`‑Umgebungsvariablen funktionieren weiter.

## Lizenz

[MIT](LICENSE)
