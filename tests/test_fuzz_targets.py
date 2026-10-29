"""Die Fuzz-Ziele aus fuzz/targets.py als normale Tests: jedes Ziel über seinen Seed-Korpus und über Zufallseingaben
(fester Startwert). Das richtige Fuzzing mit Atheris läuft im Workflow „Fuzz“ (nur Linux); hier fällt auf jeder
Plattform auf, wenn ein Ziel veraltet oder ein früherer Fund zurückkommt (die Funde liegen im Korpus)."""

from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "fuzz" / "corpus"
sys.path.insert(0, str(ROOT / "fuzz"))

import targets  # noqa: E402 – liegt in fuzz/, nicht im Paket


def _seeds() -> list[tuple[str, Path]]:
    return [(name, seed) for name in targets.TARGETS for seed in sorted((CORPUS / name).iterdir())]


def test_every_target_has_seeds():
    assert sorted(p.name for p in CORPUS.iterdir()) == sorted(targets.TARGETS)
    assert all(any((CORPUS / name).iterdir()) for name in targets.TARGETS)


@pytest.mark.parametrize(("name", "seed"), _seeds(), ids=lambda v: v if isinstance(v, str) else v.name)
def test_target_holds_for_its_seeds(name, seed):
    targets.TARGETS[name](seed.read_bytes())


@pytest.mark.parametrize("name", sorted(targets.TARGETS))
def test_target_holds_for_random_mutations(name):
    """Wie ein kurzer Fuzz-Lauf ohne Abdeckung: Seeds zerschneiden, kombinieren und Bytes kippen."""
    rnd = random.Random(f"jobslop-{name}")
    seeds = [seed.read_bytes() for _, seed in _seeds() if _ == name]
    for _ in range(300):
        data = bytearray(rnd.choice(seeds))
        for _ in range(rnd.randint(1, 8)):
            where = rnd.randint(0, len(data))
            match rnd.randint(0, 3):
                case 0:
                    data[where:where] = bytes([rnd.randint(0, 255)])
                case 1:
                    del data[where : where + rnd.randint(1, 16)]
                case 2:
                    other = rnd.choice(seeds)
                    start = rnd.randint(0, len(other))
                    data[where:where] = other[start : start + rnd.randint(1, 64)]
                case _:
                    data[where:where] = rnd.choice(
                        [b"<", b">", b'"', b"{", b"[", b"\\", b"%", b"&", b"\x00", b"?"]
                    )
        targets.TARGETS[name](bytes(data))
