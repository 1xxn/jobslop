# Changelog

## Unreleased

### New
- Many more jobs: the German Federal Employment Agency (official job search, every industry, without temp
  agencies), LinkedIn, Indeed and Glassdoor (public search via JobSpy, no login), Recruitee and Workable boards.
  One list of search terms now serves all job boards (`queries`, formerly `himalayas_queries`).
- Company boards are discovered automatically: companies from job boards are looked up on Greenhouse, Ashby,
  Lever, Recruitee, Workable and Personio; found boards are crawled and replace the job-board entries.
- Jobs on pages behind bot checks (Himalayas, Glassdoor) are marked as browser-only: never queued automatically,
  ranked lower, applied to in your own browser.
- Browser extension: fills application forms in your own Chrome (same form reader and planner as the engine),
  asks for missing answers in an in-page panel and only submits after your click. LinkedIn/Indeed Easy Apply
  can be enabled explicitly, with a daily limit.
- Read-only smoke tests against real sites (`JOBSLOP_NETWORK=1`).
- Frontend tests (Vitest), an end-to-end test of the dashboard on demo data and a release workflow: tagging
  `vX.Y.Z` re-runs CI, checks the version and publishes wheel, sdist and release notes.
- Every score is explained in the job details (target role, stack, company, level, location – out of 21 points).
- Activity and guard messages are translated in the English UI (backend stores a code with parameters).

### Improved
- Redesigned dashboard: three work areas (Today, Jobs, Applications) and grouped settings, a calm look with one
  accent colour, system font and no cards-in-cards. Today shows the one thing that needs you, then the rest.
- Jobs are triaged like mail: list and job side by side, Apply / Save / Dismiss with A / S / X, undo with Z, multi-select
  with Ctrl/Shift; dismissed jobs leave the work lists and can be restored.
- Applications: one list grouped by stage (the pipeline board is the second view, now also keyboard-operable), detail
  page with status, follow-up and notes; the live run, search and autopilot open as a side panel from anywhere.
- Keyboard shortcuts (G then a letter, `?` for help), skip link, labelled form fields, WCAG AA contrast in both themes.
- The dashboard loads only the page you open (code splitting); libraries are cached separately across updates.
- The job list and job details show where a job came from (LinkedIn, Indeed, Arbeitsagentur, Greenhouse …).

### Fixed
- The overview no longer scrolls sideways on phones, and the live run can be opened and stopped on phones.
- Applications waiting for an approval or answer show as waiting for you instead of running.
- An invalid title regex in the exclusions no longer breaks the dashboard; it is rejected when added.
- The submit button can no longer be clicked past the review: a planner that lists it as a plain click action or as
  "next" is routed through approval / dry run.
- Claude may only read files in its own work folder when it gets screenshots (prompt injection from job pages).
- Demo folders are in demo mode: no crawling, applying, autopilot or notifications. The demo script no longer turns
  the autopilot on.
- Changing roles or locations no longer marks jobs as closed that are still online; capped Workday/amazon.jobs
  searches and careers pages read by Claude no longer close jobs they simply did not list.
- Arbeitnow jobs from its UK/French/Swiss/Dutch sites are no longer labelled as Germany.
- The CLI no longer crashes on Windows when its output is redirected (Task Scheduler, pipes).
- "Stop" ends the whole application run including browser processes; LinkedIn/Indeed are detected at every step,
  not only on the first page; a dry-run batch keeps only the last filled page open.
- Claude Code tests now also run on Windows.
- The rule planner recognises "Send" as a submit button (Recruitee).

## 1.0.0 – jobslop

The project formerly known as *jobpilot* becomes **jobslop**.

### New
- One command: `jobslop` starts the dashboard; a setup wizard connects Claude, imports your CV into the profile and
  configures the search – no config files to edit.
- Completely new dashboard (React, TypeScript, Tailwind CSS): overview, jobs, pipeline, applications, activity,
  settings; light/dark mode; German and English.
- Target roles for any field via templates (Cloud/DevOps/SRE, software, data & AI, IT admin, product & design).
- Pipeline with drag & drop, notes and follow-up reminders; statistics.
- Autopilot on a schedule (dashboard) or via `jobslop autopilot` (Task Scheduler/cron).
- Notifications: browser, ntfy, webhooks.
- Add any job by link (schema.org JobPosting, meta tags, Claude as fallback).
- Generic JSON import (`jobslop import`), `jobslop install-browser`.
- Install scripts for Windows, macOS and Linux.

### Improved
- Application engine: cookie banners are closed deterministically, lazy iframes are loaded, autofill buttons are
  used, hidden form sections and screen-reader shims are ignored, clicks fall back gracefully.
- More sources (Arbeitnow, Himalayas, more company boards), duplicates across sources, capped searches never close jobs.

### Migration
- `~/.jobpilot` is moved to `~/.jobslop` automatically on first start; `JOBPILOT_*` variables keep working.
- Database columns are added automatically.
