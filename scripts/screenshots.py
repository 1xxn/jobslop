"""Screenshots aller Seiten für die README (gegen einen laufenden Demo-Server).

uv run python scripts/demo_data.py --home .demo-home
JOBSLOP_HOME=.demo-home uv run jobslop start --no-open --port 8799
uv run python scripts/screenshots.py --url http://127.0.0.1:8799 --out docs/screenshots
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

PAGES = [
    ("overview", "/"),
    ("jobs", "/jobs"),
    ("job", "/jobs?job=3"),
    ("pipeline", "/pipeline"),
    ("applications", "/applications"),
    ("application", "/applications/1"),
    ("activity", "/activity"),
    ("settings-profile", "/settings/profile"),
    ("settings-search", "/settings/search"),
    ("settings-system", "/settings/system"),
]


async def shoot(
    url: str,
    out: Path,
    *,
    token: str,
    schemes: tuple[str, ...],
    lang: str,
    width: int,
    height: int,
    only: set[str],
) -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        for scheme in schemes:
            ctx = await browser.new_context(
                viewport={"width": width, "height": height},
                device_scale_factor=2,
                color_scheme=scheme,  # type: ignore[arg-type]
                locale="de-DE" if lang == "de" else "en-US",
            )
            await ctx.add_init_script(
                f"localStorage.setItem('jobslop.lang', '{lang}'); localStorage.setItem('jobslop.theme', 'system');"
            )
            page = await ctx.new_page()
            # Anmelden wie nach `jobslop` (Token aus dem Demo-Ordner)
            await page.goto(f"{url}/#login={token}", wait_until="networkidle")
            for name, path in PAGES:
                if only and name not in only:
                    continue
                await page.goto(url + path, wait_until="networkidle")
                await page.wait_for_timeout(700)
                target = out / f"{name}-{scheme}.png"
                await page.screenshot(path=str(target))
                print(target)
            await ctx.close()
        await browser.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8799")
    parser.add_argument("--home", type=Path, default=Path(".demo-home"), help="Demo-Ordner (Anmelde-Token)")
    parser.add_argument("--out", type=Path, default=Path("docs/screenshots"))
    parser.add_argument("--lang", default="de")
    parser.add_argument("--width", type=int, default=1440)
    parser.add_argument("--height", type=int, default=900)
    parser.add_argument("--scheme", action="append", choices=["light", "dark"])
    parser.add_argument("--only", action="append", default=[])
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    asyncio.run(
        shoot(
            args.url,
            args.out,
            token=(args.home / "dashboard-token").read_text(encoding="utf-8").strip(),
            schemes=tuple(args.scheme or ["light", "dark"]),
            lang=args.lang,
            width=args.width,
            height=args.height,
            only=set(args.only),
        )
    )


if __name__ == "__main__":
    main()
