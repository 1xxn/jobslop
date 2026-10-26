# Contributing

Thanks for helping make the slop a little less sloppy.

## Setup

```bash
git clone https://github.com/1xxn/jobslop.git && cd jobslop
uv sync
uv run jobslop install-browser
cd frontend && npm ci && cd ..
```

Work with fictional data, never your own:

```bash
uv run python scripts/demo_data.py --home .demo-home
JOBSLOP_HOME=.demo-home uv run jobslop            # PowerShell: $env:JOBSLOP_HOME=".demo-home"; uv run jobslop
cd frontend && npm run dev                       # hot reload on :5173, proxies the API to :8765
```

## Checks

```bash
uv run ruff check . && uv run ruff format --check .
uv run pytest -m "not live"                      # includes real-Chromium tests against tests/fixtures/site
cd frontend && npm run typecheck && npm run build
```

`npm run build` writes into `src/jobslop/web/dist`. **Commit the build output** together with frontend changes –
users install jobslop without Node, and CI checks that the committed build matches the sources.

Tests marked `live` call the real Claude Code and use your subscription; they only run with `JOBSLOP_LIVE=1`.

## Guidelines

- Keep the guard rails: nothing may invent applicant data, submit twice, or automate LinkedIn/Indeed.
- New form quirks belong in a fixture under `tests/fixtures/site/` plus a browser test.
- UI text lives in `frontend/src/lib/messages.ts` – German and English, the type checker enforces both.
- No personal data in commits, fixtures or screenshots. Use `scripts/demo_data.py`.
- Code comments are mostly German; English is welcome too.
