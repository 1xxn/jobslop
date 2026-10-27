# Configuration

Everything below can be changed in the dashboard (**Settings**). The files are plain text, so you can also edit
them by hand – restart `jobslop` afterwards.

## Precedence

`defaults` < `~/.jobslop/settings.toml` (dashboard) < `.env` (project folder or `~/.jobslop/.env`) <
environment variables `JOBSLOP_*`. The old prefix `JOBPILOT_*` is still understood.

## Settings (`settings.toml` / `JOBSLOP_*`)

| Key | Default | Meaning |
|---|---|---|
| `home` | `~/.jobslop` | Data folder (environment only) |
| `apply_mode` | `review` | `review` · `auto` · `dry-run` |
| `llm_model` | `sonnet` | Model for forms and cover letters (`sonnet`, `opus`, `haiku` or a full model name) |
| `llm_model_fast` | `haiku` | Model for ranking and reading careers pages |
| `claude_parallel` | `2` | Parallel Claude calls |
| `claude_effort` | – | Optional `low` · `medium` · `high` |
| `claude_bin` | auto | Path to `claude` if it is not on `PATH` (environment only) |
| `vision` | `auto` | Screenshots to Claude: `auto` · `always` · `never` |
| `autofill` | `true` | Use autofill buttons on forms |
| `headless` | `false` | Hide the browser (only for unattended runs) |
| `max_steps_per_application` | `14` | Safety limit per application |
| `autopilot_enabled` | `false` | Run the autopilot on a schedule |
| `autopilot_days` | `[0,1,2,3,4]` | Weekdays, 0 = Monday |
| `autopilot_time` | `08:00` | Local time |
| `autopilot_apply` | `true` | Apply after searching |
| `autopilot_apply_max` | `5` | Max applications per autopilot run |
| `autopilot_apply_mode` | `review` | Mode for autopilot applications |
| `notify_desktop` | `true` | Browser notifications |
| `notify_ntfy_url` | – | e.g. `https://ntfy.sh/your-secret-topic` |
| `notify_webhook_url` | – | Receives `{"title","message","content","text","url"}` |
| `follow_up_days` | `10` | Follow-up reminder after submitting |
| `dashboard_host` / `dashboard_port` | `127.0.0.1` / `8765` | Where the dashboard listens (environment only) |
| `demo` | `false` | Demo folder: crawling, applying, autopilot, add-by-link and notifications are blocked. Set by `scripts/demo_data.py`, not editable in the dashboard |

## Search (`search.toml`)

```toml
[[roles]]                       # in priority order
name = "SRE"
keywords = ["site reliability", "sre", "observability"]

[filters]
include_titles = []             # empty = keywords of all roles
exclude_titles = ["intern", "werkstudent", "lead"]
stretch_markers = ["senior", "(senior)"]   # kept, but ranked lower
onsite_locations = ["berlin"]
allow_remote = true
remote_regions = ["germany", "europe", "emea"]

[limits]
max_per_company_window = 2      # applications per company …
company_window_days = 30        # … within this many days
max_applications_per_run = 15
min_delay_seconds = 40
min_score_for_auto_queue = 14.0
max_enrich_per_crawl = 60

[sources]
greenhouse = ["n26", "gitlab"]  # board names from job-boards.greenhouse.io/<name>
ashby = ["deepl"]               # jobs.ashbyhq.com/<name>
lever = ["spotify"]             # jobs.lever.co/<name>
smartrecruiters = ["Auto1"]     # jobs.smartrecruiters.com/<ID>
personio = ["tado"]             # <name>.jobs.personio.de
amazon_queries = ["devops"]
arbeitnow = true
himalayas_queries = ["devops", "platform engineer"]

[[sources.workday]]
company = "Example AG"
host = "example.wd3.myworkdayjobs.com"
tenant = "example"
site = "Careers"
search_text = "devops"

[[sources.generic]]             # any careers page – Claude extracts the jobs
company = "Example"
url = "https://example.com/careers"

skills = ["kubernetes", "terraform", "python"]   # stack fit (●●●)
```

## Job import format

`jobslop import jobs.json` accepts a list or `{"jobs": [...]}`:

```json
{
  "jobs": [
    {
      "company": "Example GmbH",
      "title": "Platform Engineer",
      "url": "https://example.com/jobs/42",
      "location": "Berlin",
      "notes": "Referral from Anna",
      "status": "applied"
    }
  ]
}
```

Required: `company`, `title`, `url`. Optional: `location`, `description`, `notes`, `posted`, `alt_urls`,
`status` (`applied` = already applied, `saved` = bookmarked) and `category`/`level`/`where`/`segment`/`fit` to
override the automatic ranking. Importing the same file twice does not create duplicates.

## Running without the dashboard

Windows Task Scheduler:

```powershell
schtasks /Create /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 08:00 /TN jobslop /TR "jobslop autopilot"
```

cron (macOS/Linux):

```
0 8 * * 1-5  jobslop autopilot
```

Unattended runs park open questions (`needs_input`) – answer them in the dashboard later; the next run uses the answers.
