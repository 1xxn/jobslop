# Security

jobslop handles personal data (your CV, contact details, application answers) and controls a browser on your behalf.

## Design

- All data stays in `~/.jobslop` on your machine. There is no jobslop server or telemetry.
- The dashboard binds to `127.0.0.1`, rejects unknown `Host` headers and requires a custom header on every
  state-changing request, so other websites cannot drive it (CSRF / DNS rebinding).
- Claude is called through your local Claude Code login; `ANTHROPIC_API_KEY` and similar variables are removed
  from the environment so nothing is billed via the API by accident.
- The only commands jobslop launches are fixed ones (`claude`, `playwright install chromium`, its own apply runner).

## Reporting a vulnerability

Please open a [private security advisory](https://github.com/1xxn/jobslop/security/advisories/new) instead of a
public issue. Include steps to reproduce and the affected version (`jobslop --version`).
