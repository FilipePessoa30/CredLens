"""Deterministic, prefixed synthetic identifiers.

Never `uuid4()` (not reproducible), never an 11-digit or CPF-punctuated
value (see credlens.contracts.domain_rules.check_no_document_like_identifiers
and SECURITY.md). Each IdFactory hands out sequential, zero-padded,
run-scoped ids for one entity type - deterministic given the same
generation_run_id and the same call order, which is guaranteed because
generation itself runs its steps in a fixed order (see orchestrator.py).
"""

from __future__ import annotations

_PREFIXES: dict[str, str] = {
    "customer": "CUS",
    "application": "APP",
    "decision": "DEC",
    "policy_version": "POL",
    "contract": "CTR",
    "installment": "INS",
    "payment": "PAY",
    "allocation": "ALL",
    "collection_event": "COL",
    "write_off": "WOF",
    "recovery": "REC",
    "generation_run": "RUN",
}


class IdFactory:
    """Sequential id generator for one entity type, scoped to a run."""

    def __init__(self, entity: str, run_short_hash: str, width: int = 7) -> None:
        if entity not in _PREFIXES:
            raise KeyError(f"Unknown entity '{entity}'. Known entities: {sorted(_PREFIXES)}")
        self._prefix = _PREFIXES[entity]
        self._run_short_hash = run_short_hash
        self._width = width
        self._counter = 0

    def next(self) -> str:
        self._counter += 1
        return f"{self._prefix}_{self._run_short_hash}_{self._counter:0{self._width}d}"

    @property
    def count(self) -> int:
        return self._counter


def run_short_hash(config_hash: str, length: int = 8) -> str:
    """A short, filesystem/id-safe slice of the run's config hash - keeps
    ids stable across a re-run with the identical configuration+seed
    (since generation_run_id itself is a deterministic function of
    scenario/scale/seed/config_hash, see manifest.py), while keeping ids
    short and readable."""
    return config_hash[:length]
