# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

jobslop is a local job-application autopilot: it crawls job sources, ranks jobs against a profile and fills out
application forms in a real Playwright browser. Claude is called through the locally installed Claude Code CLI
(`claude -p`, subscription login) – there is no Anthropic API key anywhere in the code.

## Commands

```bash
uv sync                                   # Python deps (Python 3.12+)
uv run jobslop install-browser            # Playwright Chromium, needed by browser tests
uv run ruff check . && uv run ruff format --check .
uv run mypy                               # types (default mode, config in pyproject.toml)
uv run pytest -m "not live"               # full suite, ~2 min (real headless Chromium against tests/fixtures/site)
uv run pytest tests/test_browser.py::test_name -m "not live"   # single test
uv run pytest -m "not browser and not live"                    # fast subset without Chromium

cd frontend && npm ci
npm run typecheck
npm test                                  # Vitest (src/**/*.test.ts[x])
npm run build                             # tsc + vite → writes ../src/jobslop/web/dist (committed!)
npm run dev                               # :5173, proxies /api and /artifacts to :8765
```

Before finishing any change, run all of: `ruff check`, `ruff format --check`, `mypy`, `pytest -m "not live"`,
`npm run typecheck`, `npm test`, `npm run build`. CI (`.github/workflows/ci.yml`: lint incl. mypy and zizmor, tests on Ubuntu 3.12/3.14, Windows 3.12, macOS 3.13) fails if
`src/jobslop/web/dist` differs from a fresh build – always commit the build output with frontend changes.

`live` tests call the real Claude Code and spend the user's quota; they only run with `JOBSLOP_LIVE=1`.
`network` tests (`tests/test_real_sites.py`) read real job sites and forms – never fill or submit – and only run with
`JOBSLOP_NETWORK=1`. Any test that builds a `Runtime` must keep Claude out (`monkeypatch.setattr(Runtime, "llm", …)`),
because `find_claude` also finds the developer's real installation.
`tests/test_claude_code.py` runs `tests/fake_claude.py` as a stand-in `claude` binary (by patching `find_claude`).

## Data safety – read before running anything

- All state lives in `JOBSLOP_HOME` (default `~/.jobslop`; a legacy `~/.jobpilot` is auto-migrated on first
  start). The developer's **real** data is in `~/.jobslop` / `~/.jobpilot` – never run the app, tests or scripts
  against it, and never commit personal data, CVs, screenshots of real data or `.demo-home/`.
- For UI work use fictional data: `uv run python scripts/demo_data.py --home .demo-home`, then
  `JOBSLOP_HOME=.demo-home uv run jobslop start --no-open --port 8799` (PowerShell: `$env:JOBSLOP_HOME=...`).
- Demo homes are in demo mode (`demo = true` in `settings.toml`, `config.ensure_not_demo`): crawl, apply, autopilot,
  add-by-link and notifications raise `DemoModeError`. A non-demo dashboard with the autopilot enabled really crawls
  and **really applies**. When stopping a server kill the whole process tree – apply runs are child processes
  (`runner.py` spawns `python -m jobslop apply --via-dashboard`) that own a Chromium.

## Architecture

Single package `src/jobslop`; `cli.py` (Typer) is the entry point and `jobslop` with no arguments starts the
dashboard. `runtime.Runtime` is the shared composition root used by CLI, dashboard and autopilot: it loads
`Settings` + `SearchConfig` + `Profile` and builds the LLM, planner and `ApplyEngine`.

**Config layers** (`config.py`): `Settings` (pydantic-settings) merges defaults < `settings.toml` (written by the
dashboard) < `.env` < `JOBSLOP_*` env vars (legacy `JOBPILOT_*` still read). `SearchConfig` is `search.toml`
(roles, filters, limits, sources). The profile is `profile.yaml` (`profile.py`).

**Database** (`db.py`): SQLite (WAL) via SQLAlchemy. There are no migration files – new columns are added at
startup by `_add_missing_columns`, so schema changes must be additive and nullable/defaulted.

**Crawl** (`crawl/`): each source class in `sources.py` returns `RawPosting`s (API boards: Greenhouse, Ashby,
Lever, SmartRecruiters, Personio, Recruitee, Workable, Workday, amazon.jobs; aggregators in `AGGREGATOR_SOURCES`:
Arbeitnow, Himalayas, Arbeitsagentur, `portal:*` = LinkedIn/Indeed/Glassdoor via JobSpy, which is sync and runs
in a thread; `GenericPageSource` renders a careers page and lets Claude extract the list). `pipeline.py` filters
by roles/locations, dedupes by `fingerprint`/`match_key` (company boards win over aggregators), writes
`JobSnapshot` history and decides closures from everything a source *listed*, not only what passed the filter.
Sources with `complete = False` (capped or nondeterministic) must never cause immediate closures. `boards.py`
discovers company boards for aggregator companies (stored in the `boards` table). `hosts.py` defines handoff
hosts (LinkedIn/Indeed) and browser-only hosts (bot checks: Himalayas, Glassdoor) used by guard and queue.
`classify.py` is the rule-based scorer; Claude enrichment is capped by `limits.max_enrich_per_crawl`.

**Apply engine** (`apply/`), one loop per application in `engine.py`:
`prepare.py` (cookie banners, lazy iframes, autofill buttons; no Claude) → `extract.js`, injected into every
frame and evaluated by `extract.py` into a `PageState` (fields incl. shadow DOM/iframes, buttons, errors, CAPTCHA
signals) → `planner.py` (`LLMPlanner` with schema-validated `PagePlan`, or `HeuristicPlanner` without Claude) →
`executor.py` (fills each field type and reads the value back) → guards in `engine.py` (questions, review before
submit, no double submit, confirmation detection, loop/step limits). Stopping conditions raise `Park(status, …)`.
`guard.check_job` (exclusions, duplicates across sources, per-company window) runs before every application.
LinkedIn/Indeed URLs (`HANDOFF_HOSTS`) and aggregator pages are handed off to the user, never automated.

**CV per job** (`apply/tailor.py`, opt-in `documents.tailor_cv`): Claude reorders the CV for a posting,
`fact_check` (no Claude) rejects anything not in profile/CV; cached per job in `tailored/job-<id>/`. Engine, extension
and dashboard preview share `ensure_tailored_cv`. **Inbox** (`inbox.py`, opt-in IMAP, read-only via `EXAMINE` +
`BODY.PEEK`): `related()` filters locally, only application mail goes to Claude; suggestions are `InboxMessage` rows.

**Human in the loop** (`apply/interact.py`): the engine talks to an `Interactor` – terminal implementation for
the CLI, and a DB-backed one for the dashboard where questions/approvals/handoffs are `Prompt` rows that both the
runner process and the web UI poll. Answers go into the answer bank (`Answer`) and are reused.

**LLM** (`llm.py`): `find_claude` locates the CLI (handles the Windows npm `.cmd` shim by starting the native
`claude.exe`), `subscription_env` strips API-key variables so usage always goes to the subscription, structured
output comes from `--json-schema` (`strict_schema` inlines refs). Usage-limit errors raise `LLMLimitReached` and
park runs as `paused`; `DYNAMIC_BOUNDARY` splits the cacheable system prompt from the variable part.

**Browser extension** (`assist.py` + `src/jobslop/extension/`, MV3, plain JS): installed by the dashboard into
`~/.jobslop/extension` with a pairing token; it runs `extract.js` in the user's real Chrome, `/api/assist/step`
plans server-side (same planner, `guard_submit_clicks`, `compile_action`), the extension fills and only submits
after the user's click. Never touches CAPTCHA frames; LinkedIn/Indeed only with `extension_portals`.
`tests/test_extension.py` loads it into Playwright's Chromium (`channel="chromium"`) against a live uvicorn.

**Dashboard** (`web/app.py`): FastAPI JSON API under `/api` plus the prebuilt SPA from `web/dist`. Security model
for a local server: bind to 127.0.0.1, reject unknown `Host` headers (DNS rebinding), and require `X-Jobslop: 1`
on every mutating request (CSRF). Apply runs are separate processes managed by `runner.Runner`; the autopilot
`Scheduler` (`autopilot.py`) runs in the server's lifespan.

**Frontend** (`frontend/src`): React 19 + TS + Vite + Tailwind 4 + Radix + TanStack Query + React Router.
API client and types in `lib/api.ts` / `lib/types.ts`; all UI strings live in `lib/messages.ts` in German and
English and the type checker enforces both languages exist. Design tokens are in `styles.css` (paper/ink neutrals, one
petrol accent for "your turn"); build pages from `components/ui` (`Section`, `StickyBar`, `Field`, …) and status as
`StatusLabel` – no cards for layout, no coloured pills. Shortcuts go through `lib/hotkeys.ts`. API errors are `Problem(status, "api.<code>", …)`
and show as translated toasts via the shared mutation error handler (no per-mutation `onError` toasts). Backend texts that reach the UI carry a code + params
(`record(..., code=..., **params)`, `guard.Verdict.code/params`) translated via `be.<code>` keys in
`lib/backendText.ts`; plain German text is only the fallback. Pages are lazy-loaded in `App.tsx`.

## Conventions

- Code comments, docstrings, log/event messages and CLI output are mostly German; commit messages are English.
- New form quirks get an HTML fixture in `tests/fixtures/site/` plus a test in `tests/test_browser.py` (served by
  the `site` fixture in `conftest.py`, which also records POSTed submissions).
- Guard rails are product requirements: never invent applicant data (only profile/CV/answer bank), never submit
  twice, review mode asks before submitting. Every click on a final submit button must go through
  `ApplyEngine._submit` or the extension's approval (`planner.is_final_submit` + `planner.guard_submit_clicks`). Engine and
  extension share field resolution (`executor.text_value/select_index/chosen_options`, `Files.from_profile`) and
  cover-letter handling (`engine.ensure_cover_letter`) – change them once, not per caller.
- Ruff: line length 110, rules `E F W I UP B SIM ASYNC RUF`.
