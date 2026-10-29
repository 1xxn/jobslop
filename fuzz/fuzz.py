"""Abdeckungsgesteuertes Fuzzing mit Atheris (libFuzzer für Python; nur Linux x86-64, Python 3.12–3.14).

    uv sync --group fuzz
    uv run python fuzz/fuzz.py <ziel> fuzz/corpus/<ziel> -max_total_time=60

Ziele und ihre Eigenschaften stehen in ``fuzz/targets.py``; libFuzzer-Optionen folgen nach dem Ziel. Ein Fund landet
als ``crash-…``/``timeout-…`` im Arbeitsordner (oder unter ``-artifact_prefix``) und lässt sich mit
``uv run python fuzz/fuzz.py <ziel> <datei>`` nachstellen.
"""

from __future__ import annotations

import sys

import atheris

# jobslop instrumentieren, damit libFuzzer sieht, welche Zweige eine Eingabe erreicht
with atheris.instrument_imports(include=["jobslop"]):
    import targets


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in targets.TARGETS:
        raise SystemExit(f"Ziel fehlt: {', '.join(targets.TARGETS)}")
    target = targets.TARGETS[sys.argv[1]]
    atheris.Setup([sys.argv[0], *sys.argv[2:]], target)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
