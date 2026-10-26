## What & why

<!-- Short description of the change and the motivation. -->

## Checklist

- [ ] `uv run ruff check . && uv run ruff format --check .`
- [ ] `uv run pytest -m "not live"`
- [ ] Frontend changed? `npm run typecheck && npm run build` and the build in `src/jobslop/web/dist` is committed
- [ ] No personal data in code, fixtures, logs or screenshots
