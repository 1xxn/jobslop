# Contributing

Thanks for helping make the slop a little less sloppy.

## Setup

```bash
git clone https://github.com/1xxn/jobslop.git && cd jobslop
uv sync
uv run jobslop install-browser
cd frontend && npm ci && cd ..
```

Work with fictional data, never your own. The demo folder is in *demo mode* (`demo = true` in its
`settings.toml`): it cannot crawl, apply, run the autopilot or send notifications, so a demo server is safe to
leave running.

```bash
uv run python scripts/demo_data.py --home .demo-home
JOBSLOP_HOME=.demo-home uv run jobslop            # PowerShell: $env:JOBSLOP_HOME=".demo-home"; uv run jobslop
cd frontend && npm run dev                       # hot reload on :5173, proxies the API to :8765
```

## Checks

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest -m "not live"                      # includes real-Chromium tests against tests/fixtures/site
cd frontend && npm run typecheck && npm test && npm run build
```

`npm run build` writes into `src/jobslop/web/dist`. **Commit the build output** together with frontend changes –
users install jobslop without Node, and CI checks that the committed build matches the sources.

Tests marked `live` call the real Claude Code and use your subscription; they only run with `JOBSLOP_LIVE=1`.

## Guidelines

- Keep the guard rails: nothing may invent applicant data, submit twice or submit without approval in review
  mode; LinkedIn/Indeed only through the opt-in extension; never solve or bypass CAPTCHAs or other bot checks.
- Real-site smoke tests (`JOBSLOP_NETWORK=1 uv run pytest tests/test_real_sites.py`) only read pages – keep it
  that way: no filling, no submitting against real employers.
- New form quirks belong in a fixture under `tests/fixtures/site/` plus a browser test.
- UI text lives in `frontend/src/lib/messages.ts` – German and English, the type checker enforces both.
- No personal data in commits, fixtures or screenshots. Use `scripts/demo_data.py`.
- Code comments are mostly German; English is welcome too.

## Tests at a glance

| What | Where | Runs |
|---|---|---|
| Rules, crawl, API, LLM wrapper | `tests/test_*.py` | `uv run pytest -m "not live"` (CI) |
| Real Chromium against local form fixtures | `tests/test_browser.py` | CI |
| Dashboard end to end (demo data, built UI) | `tests/test_dashboard_e2e.py` | CI |
| Browser extension end to end | `tests/test_extension.py` | CI |
| UI units and components | `frontend/src/**/*.test.ts(x)` (Vitest) | `npm test` (CI) |
| Real job sites, read-only | `tests/test_real_sites.py` | `JOBSLOP_NETWORK=1` only; weekly in `sources.yml` |
| Real Claude Code | `tests/test_claude_code.py::test_live_*` | `JOBSLOP_LIVE=1` only |

## Releasing

1. Move the `## Unreleased` section in `CHANGELOG.md` to `## X.Y.Z – <short title>`.
2. Set the version in `pyproject.toml` and `frontend/package.json` (`jobslop.__version__` reads it from the
   package metadata), run `uv lock` and `npm run build` in `frontend/`, commit.
3. Tag and push: `git tag vX.Y.Z && git push origin main vX.Y.Z`.

`.github/workflows/release.yml` re-runs all CI checks, verifies that tag, `pyproject.toml` and
`frontend/package.json` agree, builds wheel and sdist, attests their build provenance
(`gh attestation verify <file> --repo 1xxn/jobslop`) and publishes a GitHub release with the changelog section.

## CI

| Workflow | When | What |
|---|---|---|
| `ci.yml` | every PR and push to `main` | Ruff, zizmor (workflow security), pytest on Ubuntu 3.12/3.14, Windows 3.12 and macOS 3.13, Vitest + build check, dependency review on PRs |
| `codeql.yml` | PRs, `main`, weekly | CodeQL for Python, TypeScript/JavaScript and the workflows |
| `sources.yml` | weekly, manual | Read-only smoke test against real job sites – notices when a source changes its format |
| `release.yml` | tag `v*` | see above |

Actions are pinned to commit SHAs; Dependabot updates them (and Python/npm packages) with a 14-day cooldown.
