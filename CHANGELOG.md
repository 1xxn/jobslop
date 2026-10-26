# Changelog

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
