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
- CV per job (opt-in): a CV tailored to the posting, rendered as an ATS-readable PDF and fact-checked against your
  profile and CV – unverified numbers, companies and skills are removed, otherwise the original CV is used.
  Preview and recreate it in the job details; the engine and the browser extension upload exactly that file.
- Replies from your inbox (opt-in, read-only IMAP): rejections, invitations and offers are matched to your
  applications and wait on Today for one click (with undo); receipts are logged on the application. Only mail
  that belongs to an application goes to Claude.

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
- Python 3.14 is supported. CI tests Ubuntu (3.12, 3.14), Windows and macOS, checks the workflows with zizmor, runs
  CodeQL and a dependency review on pull requests, pins all actions to commit SHAs and caches Chromium; releases
  carry build provenance attestations; a weekly job checks that the real job sources still work.
- CI checks Python types with mypy (Linux, Windows and macOS branches are clean); new tests cover approvals,
  questions and handoffs through the dashboard, the CV import and the security headers.

### Security
- The dashboard cannot be embedded in other websites (clickjacking: a page could lay it invisibly over a decoy and
  make you click "Submit"); it loads only its own scripts (Content-Security-Policy), sends no referrer and never lets
  the browser guess file types. The theme script moved out of `index.html` for that.
- `Host` headers are parsed exactly (`[::1]` without a port); the test-only host name is no longer accepted.
- Job sources that deliver `javascript:` or `file:` links instead of web addresses are skipped, and the browser only
  opens http(s) addresses.
- On Linux and macOS the jobslop folder (profile, CV, inbox password, extension token, browser logins) is readable
  only by you.
- A stopped run or a closing dashboard no longer leaves Claude running in the background (it used up your quota).

### Performance
- With thousands of jobs the dashboard stays fast: indexes for the job state and first-seen date (added to existing
  databases on start), the job list no longer loads job descriptions, exclusion rules are prepared once per request
  instead of once per job, and the status poll reads only the end of the run log. Measured with 5,000 jobs: status
  124 → 29 ms (polled every 3 s), job list 300 → 177 ms, statistics 92 → 21 ms.
- Crawling no longer slows down with the size of the database: the duplicate check for every new posting read all
  open jobs including their descriptions (SQLite picked the job-state index for it). A crawl that adds 1,337 jobs to a
  database of 5,000 takes 3.0 s instead of 20.3 s; a crawl without changes 2.0 s instead of 2.9 s.
- The job list reads plain rows and takes the job state from its index, and only the visible page is loaded
  completely: 210 → 48 ms with 5,000 jobs, 883 → 198 ms with 20,000. Dismissing or saving a job (X/S) updates the list
  in 204 ms instead of 316 ms (p95 212 instead of 821 ms).
- The status poll counts the jobs to review again only when something changed in the database (any process):
  43 → 9 ms with 5,000 jobs, 152 → 10 ms with 20,000.
- Applications, pipeline, statistics, job details and the CSV export no longer run one query per application or job:
  pipeline 246 → 73 ms (913 → 4 queries), CSV export 4.3 s → 0.1 s with 20,000 jobs.
- SQLite reads the database through a memory map (list queries up to three times faster on Windows);
  `synchronous=FULL` is now set explicitly so a submitted application always survives a power cut.
- The dashboard starts in 1.2 s instead of 5.1 s on Windows (checking the port waited twice for a 2-second connection
  retry).
- Pages appear 300 ms sooner on start and reload: the router loads the page code instead of `React.lazy`, whose
  placeholder React 19 shows for at least 300 ms. The first job appears after 0.2 s instead of 0.7 s.
- Moving through a long job list (J/K) re-renders only the rows that change: 50 → 18 ms per key with 600 jobs.
- Application forms: visually hidden radio buttons and checkboxes (custom styles as on Greenhouse) are set after
  1 s instead of 5 s each, and uploads into visible file fields wait once instead of twice – 5 s less on the
  Greenhouse-like test form.
- Developers: `scripts/bench.py` measures API, crawl, application engine, start-up, frontend and memory on invented
  data in a temporary folder; `tests/test_performance.py` keeps query counts, index use, the status cache and the
  port check from regressing.

### Updates
- Python 3.15 is supported and is the development version (`.python-version`); 3.12 stays the minimum. CI tests 3.12
  and 3.15 on Linux and Windows and 3.15 on macOS.
- The dashboard is built with Node 26 (current LTS).
- All Python and npm packages are on their latest stable versions (among them JobSpy 1.4.1, pypdf 6.21.4,
  pydantic-settings 2.16.2, lucide-react 1.63, React Router 8.5.1, Vitest 5.0.5, jsdom 30.1.3); the minimum versions in
  `pyproject.toml` are the tested ones, so an install never resolves older releases with known issues.
- CI actions and tools: setup-uv 10.3.3, CodeQL 4.39.1, zizmor 1.31.1.

### Fixed
- Found in a live test with real job boards: reposted job-board listings (same company, title and place) are merged;
  a company board that names its own country (e.g. "Krakow, Poland") is no longer turned into "remote Germany" by a
  job-board guess; legal roles ("Legal Counsel … Platform Workers") are excluded by the templates; confirmation pages
  such as "Thanks for applying" and "Application sent" are recognised; the approval shows real file names instead of
  `@cv_en`; only required fields of the application form count (not a newsletter field in the footer); when the
  Claude usage limit pauses a run, the browser window says so before it closes. JOIN, uploads into drop zones,
  self-closing login popups, Google's consent dialog and approvals that time out are handled as well.
- Errors are always visible and translated: failed actions show a toast, failed loads a retry instead of an endless
  placeholder, a crashed page an error page instead of a white screen, unexpected server errors a readable message.
- A stopped or crashed application run no longer leaves the application on "running" (which blocked the job) or
  questions nobody answers; crashes appear in the run panel and the log. Autopilot failures are logged and notified.
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
- An approval clicked in the last second of the waiting time is no longer lost (the dashboard said "answered" while
  the run had given up); a run whose question was closed by the dashboard stops waiting at once, and the waiting
  time includes the time spent checking the page.
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
