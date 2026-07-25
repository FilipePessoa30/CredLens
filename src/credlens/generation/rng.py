"""Reproducible, independent random-number substreams for each generation
step, built on numpy's SeedSequence/Generator (never the legacy global
numpy.random state, never Python's stdlib `random`).

Each named stream is derived once, in a fixed declared order, from the
run's single seed via SeedSequence.spawn(). Adding a new stream in the
future appends to STREAM_NAMES without disturbing the substreams already
spawned for existing names, as long as it's added at the end - see
docs/synthetic_generation_implementation.md "Reproducibility" for why
this ordering matters (a new step must never silently reshuffle every
earlier step's draws just by being added).
"""

from __future__ import annotations

import numpy as np

STREAM_NAMES: tuple[str, ...] = (
    "customers",
    "applications",
    "features",
    "decisions",
    "booking",
    "behavior",
    "payments",
    "collections",
    "write_off",
    "recovery",
    "macro",
    "truth",
)


class RunRandomStreams:
    """One independent numpy Generator per named step, all derived from a
    single run seed via SeedSequence.spawn() - not from re-seeding the
    same generator repeatedly, which would correlate streams."""

    def __init__(self, seed: int) -> None:
        self.seed = seed
        root = np.random.SeedSequence(seed)
        children = root.spawn(len(STREAM_NAMES))
        self._generators: dict[str, np.random.Generator] = {
            name: np.random.default_rng(child)
            for name, child in zip(STREAM_NAMES, children, strict=True)
        }

    def stream(self, name: str) -> np.random.Generator:
        try:
            return self._generators[name]
        except KeyError:
            raise KeyError(f"Unknown RNG stream '{name}'. Known streams: {STREAM_NAMES}") from None
