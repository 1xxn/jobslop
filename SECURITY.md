# Security

jobslop handles personal data (your CV, contact details, application answers, optionally your mailbox) and controls a
browser on your behalf. The threat model, the controls and the findings of the last review are in
[docs/security.md](docs/security.md).

## Supported versions

| Version | Supported |
|---|---|
| `main` and the latest release | ✅ security fixes |
| older releases | ❌ – update with `uv tool upgrade jobslop` (or re-run the install script) |

## Reporting a vulnerability

Please report privately through GitHub's
[private vulnerability reporting](https://github.com/1xxn/jobslop/security/advisories/new) – not in a public issue,
discussion or pull request. Include:

- what an attacker can do and what they need (a malicious job page, a link you paste, another local user …),
- steps to reproduce with fictional data (never send your real profile or CV),
- the affected version (`jobslop --version`) and your operating system.

You get an answer within a week. Fixes are developed in the advisory, released, and the advisory is published with
credit (unless you prefer not to be named).

## Design in short

- All data stays in `~/.jobslop` on your machine (private to your user account). There is no jobslop server or
  telemetry.
- The dashboard listens on `127.0.0.1` only, rejects foreign `Host` headers, requires a custom header on every
  state-changing request and cannot be framed (CSRF, DNS rebinding, clickjacking).
- Links from job sources and pages are only opened when they point to public web addresses – never into your own
  computer or network.
- Claude is called through your local Claude Code login with no tools except reading its own work folder; API keys are
  removed from its environment, so nothing is billed via the API by accident.
- Nothing is submitted without your approval in review mode, nothing twice; the browser extension only submits after
  your click and never touches CAPTCHAs.
- The only commands jobslop launches are fixed ones (`claude`, `playwright install chromium`, its own apply runner,
  and on Windows `taskkill`/`icacls` from System32).
