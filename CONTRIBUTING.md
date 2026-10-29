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

The API answers only browsers with the session cookie (other local users and processes reach `127.0.0.1` too).
`jobslop` opens the browser signed in and prints a sign-in link; for the Vite dev server open
`http://localhost:5173/#login=<token>` once, with the token from `<JOBSLOP_HOME>/dashboard-token`.

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
- New functionality and every bug fix come with tests (pytest or Vitest) that fail without the change; pull
  requests without them are not merged.
- New form quirks belong in a fixture under `tests/fixtures/site/` plus a browser test.
- Bugs and ideas: open an issue. Security problems: report them privately (`SECURITY.md`).
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
| Fuzz targets over their seed corpus and random mutations | `tests/test_fuzz_targets.py` | CI |
| Coverage-guided fuzzing (Atheris) | `fuzz/fuzz.py` | `fuzz.yml` (Linux) |
| UI properties for any input (fast-check) | `frontend/src/**/*.property.test.ts` | `npm test` (CI) |

## Fuzzing

Everything that reads foreign input has a fuzz target in `fuzz/targets.py` (HTML of job descriptions and pages,
JSON-LD, title-exclusion regexes, upload names, steps of the browser extension). A target checks properties
that hold for every input, not only that nothing crashes – an accepted regex stays fast against any title, a
stored file name is one Windows keeps as it is. Atheris runs on Linux x86-64 with Python 3.12–3.14 (WSL on
Windows):

```bash
uv sync --group fuzz
uv run python fuzz/fuzz.py title_regex fuzz/corpus/title_regex -max_total_time=60
uv run python fuzz/fuzz.py title_regex crash-1234abcd      # replay a finding
```

`fuzz.yml` fuzzes every target for a minute on pull requests that touch `src/` and for ten minutes every night.
Its log names only the target, the kind of finding and libFuzzer's seed – never the input, because the logs of a
public repository are public. To reproduce a nightly finding run the target locally with `-seed=<seed from the
log>` on a copy of its corpus. A finding becomes a test (the input goes into `fuzz/corpus/<target>/`); if it is
exploitable, report it privately first (`SECURITY.md`).

## Releasing

1. Move the `## Unreleased` section in `CHANGELOG.md` to `## X.Y.Z – <short title>`.
2. Set the version in `pyproject.toml` and `frontend/package.json` (`jobslop.__version__` reads it from the
   package metadata), run `uv lock` and `npm run build` in `frontend/`, commit.
3. Tag and push: `git tag vX.Y.Z && git push origin main vX.Y.Z`.

The install scripts pin the uv installer to a release and its SHA-256 (`UV_VERSION`, `UV_INSTALLER_SHA256` in
`install.sh`, `$UvVersion`, `$UvInstallerSha256` in `install.ps1`; digests from the uv release page). Bump them
now and then – the pinned uv only installs jobslop, `uv self update` brings it up to date.

`.github/workflows/release.yml` re-runs all CI checks, verifies that tag, `pyproject.toml` and
`frontend/package.json` agree, builds wheel and sdist, writes CycloneDX SBOMs (Python packages from `uv.lock`, npm
packages of the dashboard), attests build provenance and the SBOM (`gh attestation verify <file> --repo 1xxn/jobslop`)
and – after you approve the `release` environment in the run – publishes a GitHub release with the changelog section.
The signed attestation bundles are release files too (`jobslop-vX.Y.Z.intoto.jsonl` for the provenance,
`jobslop-vX.Y.Z.sbom.intoto.jsonl` for the SBOM), so a download can be checked without the attestation API:
`gh attestation verify jobslop-X.Y.Z-py3-none-any.whl --repo 1xxn/jobslop --bundle jobslop-vX.Y.Z.intoto.jsonl`.
The workflow verifies both bundles before it uploads anything.
Only maintainers can create `v*` tags (tag ruleset).

## CI

| Workflow | When | What |
|---|---|---|
| `ci.yml` | every PR and push to `main` | Ruff, mypy, zizmor (workflow security, strictest persona), pytest on Ubuntu and Windows (3.12 and 3.15) and macOS (3.15), npm registry signatures, Vitest + build check, dependency review on PRs |
| `audit.yml` | PRs, `main`, daily | Known vulnerabilities in `uv.lock` (pip-audit, OSV – any finding fails) and `package-lock.json` (npm audit, high and critical) |
| `codeql.yml` | PRs, `main`, weekly | CodeQL for Python, TypeScript/JavaScript and the workflows |
| `secrets.yml` | PRs, `main`, weekly | Gitleaks: credentials in commits (the whole history on schedule) |
| `scorecard.yml` | `main`, weekly | OpenSSF Scorecard (badge in the README, results under Security → Code scanning) |
| `sources.yml` | weekly, manual | Read-only smoke test against real job sites – notices when a source changes its format |
| `fuzz.yml` | PRs touching `src/`, nightly, manual | Atheris fuzzes every target in `fuzz/targets.py` (1 min on PRs, 10 min nightly); not a required check |
| `release.yml` | tag `v*` | see above |

Every workflow starts without permissions and grants each job only what it needs; checkouts never keep the token.
Actions are pinned to commit SHAs (the repository only accepts pinned actions from GitHub and an allow list);
Dependabot updates them (and Python/npm packages) with a 14-day cooldown. `npm ci --ignore-scripts`: dependencies
may not run install scripts. The Python tools of the CI (zizmor, pip-audit) are dependency groups in `pyproject.toml`
(`workflows`, `audit`) and run from `uv.lock` with hashes (`uv run --only-group workflows zizmor …`), never as
`uvx tool==version`.
