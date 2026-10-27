# Architecture

jobslop is a single Python package (`src/jobslop`) with a React dashboard (`frontend/`, built into
`src/jobslop/web/dist`). Everything runs locally; the only external services are the job sources, the
application forms you apply to, and Claude Code on your machine.

```
src/jobslop/
├── cli.py            Typer CLI – `jobslop` without arguments starts the dashboard
├── config.py         Settings (env/.env/settings.toml) and SearchConfig (search.toml)
├── presets.py        Role templates for the setup wizard
├── db.py             SQLAlchemy models + lightweight migrations (SQLite, WAL)
├── classify.py       Rule-based ranking: role, level, location, stack fit, score
├── crawl/            Sources (APIs + rendered careers pages), pipeline, history
├── apply/            The application engine (see below)
├── llm.py            Claude Code wrapper: `claude -p` with JSON schema, no API key
├── autopilot.py      Crawl → queue → apply, scheduler
├── runner.py         Application runs as a separate process
├── notify.py         ntfy / webhook notifications
├── jobpage.py        "Add job by link" (schema.org JobPosting → meta tags → Claude)
├── importer.py       JSON job import
├── system.py         Setup checks (Claude login, Chromium, profile), helpers
└── web/app.py        FastAPI: JSON API under /api + the built SPA
```

## Data

Everything lives in `~/.jobslop` (override with `JOBSLOP_HOME`):

| File | Content |
|---|---|
| `jobslop.db` | Jobs with snapshot history, crawl runs, applications + events, prompts, answer bank, exclusions, activity |
| `profile.yaml` | Your applicant profile (edited in the dashboard) |
| `search.toml` | Target roles, filters, sources, limits |
| `settings.toml` | Dashboard-managed settings (mode, models, autopilot, notifications) |
| `documents/` | Your CV(s) and certificates |
| `artifacts/` | Per application: screenshots, plans, filled values, cover letter PDF |
| `browser-profile/` | The persistent Chromium profile (portal logins stay signed in) |

New columns are added automatically on start (`db._add_missing_columns`), so upgrades never need a manual migration.

## Crawling

Each source returns `RawPosting`s. The pipeline filters titles (role keywords minus exclusions; "senior" is kept as
*stretch*), matches locations (cities on-site, remote only in allowed regions), fetches missing descriptions, and
upserts jobs by fingerprint. Every run writes snapshots (`new`, `updated` with a diff, `closed`, `reopened`).

- A job is only closed when its source was queried **completely** and the job is missing. Capped searches
  (job boards) close jobs only after three weeks without a sighting. A failing source closes nothing.
- The same job from a job board and a company board is stored once; the company board wins.
- Claude rates at most `limits.max_enrich_per_crawl` new jobs per run (best rule score first) to protect your quota.

Sources: API boards (`greenhouse`, `ashby`, `lever`, `smartrecruiters`, `personio`, `recruitee`, `workable`,
`workday`, `amazon`), job boards with keyword search (`arbeitsagentur` – the official German job search API,
`himalayas`, `arbeitnow`) and the big portals (`portal:linkedin`, `portal:indeed`, `portal:glassdoor`) through
[JobSpy](https://github.com/speedyapply/JobSpy) – public search only, no login, throttled; LinkedIn searches are
bundled into one OR query per location and descriptions are loaded only for jobs that pass the filters.

**Board discovery** (`crawl/boards.py`): companies from job-board hits are looked up on Greenhouse, Ashby, Lever,
Recruitee, Workable and Personio (slug guesses from the company name). A board only counts if the same job is
listed there; hits and misses are stored in the `boards` table (misses are rechecked after 30 days) and found
boards are crawled from then on. Their postings replace the job-board entries – which matters for job boards whose
pages sit behind bot checks (Himalayas, Glassdoor): those are *browser-only* (`hosts.py`), never queued
automatically and ranked lower, and can still be applied to through the browser extension.

## The application engine (`apply/`)

One application is a loop of up to `max_steps_per_application` steps:

1. **Prepare** (`prepare.py`, no Claude): close cookie banners (prefers "reject"/"only necessary", searches all
   frames and open shadow roots, skips buttons that had no effect), wake lazy iframes and content below the fold,
   use autofill buttons (CV upload with parser wait; portal logins such as MyGreenhouse are detected and skipped).
2. **Extract** (`extract.js` in every frame): fields with labels, required state, options and current value; buttons
   flagged as form/autofill/cookie; errors; CAPTCHA signals. Hidden form sections and screen-reader shims are ignored.
3. **Plan** (`planner.py`): Claude gets fields, buttons, errors, page text, job description and history; profile and
   CV sit in a cached system prompt, the answer bank after the cache boundary. The result is schema-validated: an
   action per field with value, source and confidence, open questions, and the next button. Without Claude a rule
   planner fills standard fields.
4. **Execute** (`executor.py`): native inputs, masked inputs, custom comboboxes, hidden radios, file uploads – each
   value is read back. Clicks fall back to forced and JavaScript clicks; a vanished element just triggers a re-scan.
5. **Guard** (`engine.py`): open questions go to you (dashboard/terminal) and into the answer bank; review mode asks
   before submitting; a second submit only happens after a correction; confirmation pages are recognised; loops and
   step limits park the application for review.

Usage limits of the subscription pause the run (`paused`) without submitting anything half-filled.

## Browser extension (`assist.py`, `extension/`)

An unpacked Chrome extension (Manifest V3) that applies in the user's own browser – where the automated Chromium
gets stuck in bot checks or needs a login. The dashboard writes it to `~/.jobslop/extension` together with
`config.js` (server address + pairing token) and `extract.js` (the engine's form reader). Flow per step: the
extension reads every frame with `extract.js`, posts it to `/api/assist/step` (token in `X-Jobslop-Token`), the
server builds a `PageState`, plans with the normal planner, applies `guard_submit_clicks` and compiles each action
into a concrete instruction (option already resolved, files as placeholders that the extension downloads). The
extension fills, reports results, shows questions in an in-page panel and stops before the final submit until the
user clicks “Submit”. CAPTCHA frames are never read or touched. LinkedIn/Indeed pages are refused unless
`extension_portals` is on, with a daily submission limit.

## Dashboard

FastAPI serves a JSON API and the pre-built React app. Security for a local server:

- binds to `127.0.0.1` only,
- rejects unknown `Host` headers (DNS rebinding),
- requires `X-Jobslop: 1` on every mutating request (a foreign website cannot set it without a CORS preflight).

Application runs are separate processes (`runner.py`) so a hanging page never blocks the UI. Prompts (questions,
approvals, handoffs) are rows in the database that both sides poll. The autopilot scheduler runs inside the
dashboard; `jobslop autopilot` provides the same for OS schedulers.

Frontend stack: React 19, TypeScript, Vite, Tailwind CSS 4, Radix UI primitives, TanStack Query, React Router,
lucide icons. Design tokens follow Material 3 colour roles and Apple HIG typography/spacing; light and dark themes,
German and English.
