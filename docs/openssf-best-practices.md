# OpenSSF Best Practices – answers and evidence

Answers for the [OpenSSF Best Practices badge](https://www.bestpractices.dev/) (formerly CII Best Practices),
level **passing**, with the evidence in this repository. OpenSSF Scorecard reads the badge level from
bestpractices.dev (check *CII-Best-Practices*: in progress 2, passing 5, silver 7, gold 10). The entry itself is made
by the maintainer on bestpractices.dev; this file keeps the answers and their sources in one place.

Base URL of the evidence: `https://github.com/1xxn/jobslop/blob/main/`.

## Basics

| Criterion | Answer | Justification and evidence |
|---|---|---|
| `description_good` | Met | README, first section: what jobslop does (crawls job sources, ranks jobs against a profile, fills application forms in a real browser). `README.md` |
| `interact` | Met | README: Quickstart (how to obtain), Development and CONTRIBUTING (how to contribute), issues for feedback. `README.md#quickstart`, `CONTRIBUTING.md` |
| `contribution` | Met | `CONTRIBUTING.md` (setup, checks, pull requests). URL: `CONTRIBUTING.md` |
| `contribution_requirements` | Met | Required checks, coding conventions, guard rails, tests per change: `CONTRIBUTING.md#checks`, `CONTRIBUTING.md#guidelines` |
| `floss_license` | Met | MIT. `LICENSE` |
| `floss_license_osi` | Met | MIT is OSI-approved. |
| `license_location` | Met | `LICENSE` in the repository root. |
| `documentation_basics` | Met | README (quickstart, usage, FAQ), `docs/architecture.md`, `docs/configuration.md`, `docs/security.md` |
| `documentation_interface` | Met | CLI: `jobslop --help` and README → Usage; configuration: `docs/configuration.md`; local HTTP API is internal to the dashboard (documented in `docs/architecture.md`). |
| `sites_https` | Met | Project site and repository on github.com (HTTPS only); releases and installers are fetched over HTTPS. |
| `discussion` | Met | GitHub issues and pull requests: searchable, addressable by URL, open to everyone. `https://github.com/1xxn/jobslop/issues` |
| `english` | Met | Documentation, issues, commits and the UI (English and German) are in English. |
| `maintained` | Met | Active development (see commit history and closed issues of the milestones). |

## Change control

| Criterion | Answer | Justification and evidence |
|---|---|---|
| `repo_public` | Met | `https://github.com/1xxn/jobslop` (public). |
| `repo_track` | Met | Git: every change with author and date; `main` changes only through pull requests (ruleset). |
| `repo_interim` | Met | All work happens in pull requests against `main` between releases. |
| `repo_distributed` | Met | Git. |
| `version_unique` | Met | Version in `pyproject.toml` and `frontend/package.json`, tags `vX.Y.Z` (the release workflow refuses a tag that does not match both). `CONTRIBUTING.md#releasing` |
| `version_semver` | Met | Semantic versioning (`X.Y.Z`). |
| `version_tags` | Met | Releases are git tags `v*`, protected by a tag ruleset (only maintainers). |
| `release_notes` | Met | `CHANGELOG.md`; the release workflow publishes the section of the tagged version as release notes and fails without one. URL: `CHANGELOG.md` |
| `release_notes_vulns` | Met | `CHANGELOG.md` has a *Security* section per version; fixed vulnerabilities are published as GitHub security advisories (`https://github.com/1xxn/jobslop/security/advisories`). None has a CVE yet. |

## Reporting

| Criterion | Answer | Justification and evidence |
|---|---|---|
| `report_process` | Met | Bugs and ideas as GitHub issues (`CONTRIBUTING.md`, README → Development). URL: `https://github.com/1xxn/jobslop/issues` |
| `report_tracker` | Met | GitHub issues. |
| `report_responses` | Met | Every issue so far was answered or closed with a pull request. |
| `enhancement_responses` | Met | Enhancement requests are answered in their issue. |
| `report_archive` | Met | `https://github.com/1xxn/jobslop/issues?q=is%3Aissue` (public, searchable). |
| `vulnerability_report_process` | Met | `SECURITY.md` → Reporting a vulnerability. URL: `SECURITY.md` |
| `vulnerability_report_private` | Met | Private vulnerability reporting on GitHub is enabled: `https://github.com/1xxn/jobslop/security/advisories/new` |
| `vulnerability_report_response` | Met | `SECURITY.md`: answer within a week (the criterion asks for 14 days). |

## Quality

| Criterion | Answer | Justification and evidence |
|---|---|---|
| `build` | Met | `uv build` (hatchling) builds wheel and sdist; `npm run build` builds the dashboard (`CONTRIBUTING.md`, `.github/workflows/release.yml`). |
| `build_common_tools` | Met | uv/hatchling, npm/Vite. |
| `build_floss_tools` | Met | All build tools are FLOSS. |
| `test` | Met | pytest suite (`tests/`, incl. real Chromium against local form fixtures and end-to-end tests of dashboard and extension) and Vitest (`frontend/src/**/*.test.ts(x)`). |
| `test_invocation` | Met | `uv run pytest -m "not live"`, `npm test` – standard invocations, documented in `CONTRIBUTING.md#checks`. |
| `test_most` | Met | The suite covers rules, crawl, apply engine (real browser), API, extension, UI units, security controls (`tests/test_security.py`) and fuzz targets. |
| `test_continuous_integration` | Met | `.github/workflows/ci.yml` on every pull request and push to `main`: Linux, Windows (3.12, 3.15) and macOS; required checks of the `main` ruleset. |
| `test_policy` | Met | `CONTRIBUTING.md#guidelines`: new functionality and every bug fix come with tests. |
| `tests_are_added` | Met | E.g. the hardening pull requests (#26, #27) and the fuzzing pull request added tests for every fix (`tests/test_security.py`, `tests/test_fuzz_targets.py`). |
| `tests_documented_added` | Met | `CONTRIBUTING.md#guidelines` (tests per change, fixtures for new form quirks). |
| `warnings` | Met | Ruff (incl. flake8-bandit rules), mypy, TypeScript `tsc --noEmit`, zizmor for workflows. `pyproject.toml`, `.github/workflows/ci.yml` |
| `warnings_fixed` | Met | CI fails on any warning of these tools; `main` has none. |
| `warnings_strict` | Met | zizmor in its strictest persona (`auditor`), Ruff security rules, `warn_unused_ignores` in mypy. |

## Security

| Criterion | Answer | Justification and evidence |
|---|---|---|
| `know_secure_design` | Met | Threat model, trust boundaries and controls: `docs/security.md` (least privilege for Claude and the extension, fail-safe defaults such as loopback-only binding and review mode, input validation everywhere). |
| `know_common_errors` | Met | `docs/security.md` → Findings (SSRF, CSRF/DNS rebinding, ReDoS, path traversal, prompt injection) with fixes and tests. |
| `crypto_published` | Met | jobslop implements no cryptography; it uses TLS from Python's `ssl`/httpx and Chromium, and Python's `secrets` module. |
| `crypto_call` | Met | Cryptography only through those libraries. |
| `crypto_floss` | Met | All of them are FLOSS. |
| `crypto_keylength` | N/A | jobslop creates no keys; TLS parameters come from Python/OpenSSL and Chromium defaults. |
| `crypto_working` | Met | No broken algorithms: SHA-1/SHA-256 only as non-security fingerprints of job postings. |
| `crypto_weaknesses` | Met | Same as above. |
| `crypto_pfs` | N/A | jobslop runs no TLS server; outbound TLS uses the library defaults (forward-secret suites). |
| `crypto_password_storage` | N/A | jobslop has no user passwords; the dashboard uses a random session token. The IMAP app password for your own mailbox is stored in the OS keyring (`docs/security.md` → Secrets and files). |
| `crypto_random` | Met | Dashboard session and extension pairing tokens: `secrets.token_urlsafe` (32/24 bytes), compared with `secrets.compare_digest` (`src/jobslop/web/app.py`, `src/jobslop/assist.py`). |
| `delivery_mitm` | Met | Install scripts and packages come over HTTPS from GitHub; the uv installer is pinned to a version and verified against its SHA-256 (`install.sh`, `install.ps1`); releases carry Sigstore-signed provenance. |
| `delivery_unsigned` | Met | No hash is fetched over HTTP; the uv installer hash is part of the install script. |
| `vulnerabilities_fixed_60_days` | Met | No publicly known unpatched vulnerability; published advisories were fixed before publication. |
| `vulnerabilities_critical_fixed` | Met | Fixes are developed in private advisories and merged before publication (`SECURITY.md`). |
| `no_leaked_credentials` | Met | Gitleaks over the full history (`.github/workflows/secrets.yml`), GitHub secret scanning with push protection. |

## Analysis

| Criterion | Answer | Justification and evidence |
|---|---|---|
| `static_analysis` | Met | CodeQL for Python, TypeScript/JavaScript and the workflows on every pull request (`.github/workflows/codeql.yml`); Ruff with flake8-bandit rules and mypy in CI; zizmor for workflows. |
| `static_analysis_common_vulnerabilities` | Met | CodeQL security queries and the bandit rules look for common vulnerabilities (injection, SSRF, unsafe deserialisation, …). |
| `static_analysis_fixed` | Met | No open CodeQL alerts; findings were fixed in pull requests (e.g. #10, #11). |
| `static_analysis_often` | Met | On every pull request and push to `main`, plus weekly. |
| `dynamic_analysis` | Met | Coverage-guided fuzzing with Atheris of every parser of foreign input (`fuzz/targets.py`, `.github/workflows/fuzz.yml`: on pull requests and nightly), property-based tests with fast-check in the dashboard, end-to-end tests in a real browser. |
| `dynamic_analysis_unsafe` | N/A | Python and TypeScript are memory-safe. |
| `dynamic_analysis_enable_assertions` | Met | Fuzz targets check properties with assertions (e.g. an accepted regex stays fast for any title); the test suite runs with assertions on. |
| `dynamic_analysis_fixed` | Met | Fuzzing findings were fixed with regression tests (`CONTRIBUTING.md#fuzzing`, `tests/test_fuzz_targets.py`). |

## Next level: silver

Silver (Scorecard 7) needs, besides passing, among others:

| Criterion | Status | What it needs |
|---|---|---|
| `governance`, `roles_responsibilities` | Missing | A short `GOVERNANCE.md`: one maintainer decides, how decisions are made, who may merge and release. |
| `code_of_conduct` | Missing | A `CODE_OF_CONDUCT.md` (e.g. Contributor Covenant). |
| `access_continuity` | Unmet | The project must survive the loss of its only maintainer within a week (a second person with admin rights). Not possible for a single anonymous maintainer without a second person. |
| `bus_factor` (SHOULD) | Unmet | Same reason. |
| `documentation_roadmap` | Missing | A roadmap for the next year (could be a pinned issue). |
| `test_statement_coverage80` | Unknown | Statement coverage is not measured yet (pytest-cov in CI). |
| `signed_releases` | Met | Every release carries Sigstore-signed provenance and SBOM bundles (`jobslop-vX.Y.Z.intoto.jsonl`); PyPI files carry PEP 740 attestations. |
| `dco` (SHOULD) | Missing | Developer Certificate of Origin sign-off for contributions. |
| `assurance_case` | Met | `docs/security.md` (threat model, trust boundaries, controls, findings). |

Gold (Scorecard 10) additionally requires two unassociated significant contributors and two-person review of most
changes – not reachable for a single-maintainer project.
