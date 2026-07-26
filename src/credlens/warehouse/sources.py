"""Safe selection of which generator runs feed the warehouse (Phase 5,
section 5). The warehouse must NEVER load a run that:

  - has no manifest, or a manifest that fails to parse;
  - did not finish with status "completed";
  - did not pass strict contract validation (manifest.validation_passed);
  - sits outside the generator's own configured output root
    (config.output.operational_dir) - this is what keeps a glob from ever
    accidentally reaching data/quarantine/, which lives in a sibling
    directory, not under data/synthetic/;
  - was produced by a generator/contract version this warehouse doesn't
    declare support for.

Selection is always explicit: exactly one of `run_id` or `suite_id`, never
an implicit "most recent" run - the caller (CLI) must say precisely which
run(s) feed a given build.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from credlens.generation.config import load_generation_config
from credlens.generation.suite import SuiteError, load_suite_manifest
from credlens.generation.writers import PathSafetyError, resolve_within_directory

# The only contract_version_set values this warehouse's staging models were
# built and tested against - see contracts/operational/payments.yaml (the
# payment_type column staging/int_/fct_ models below assume exists) and
# contracts/operational/generation_runs.yaml (suite_id/parent_run_id).
# Extend this set deliberately (and re-verify the dbt models) when a future
# generator version adds a genuinely new contract_version_set - never
# silently accept an unrecognized one.
SUPPORTED_CONTRACT_VERSION_SETS: tuple[str, ...] = ("phase5-v1",)


class SourceSelectionError(Exception):
    """Raised when a requested run/suite cannot be safely loaded into the warehouse."""


@dataclass(frozen=True)
class SourceRecord:
    """Everything the warehouse's raw layer and its own audit trail need to
    know about one generator run - see section 5's required fields."""

    run_id: str
    suite_id: str | None
    scenario: str
    seed: int
    scale: str
    generator_version: str
    contract_version_set: str
    config_hash: str
    global_content_hash: str
    source_path: str  # the run's .../operational directory, as a posix string
    row_counts: dict[str, int]
    selected_at: str  # when THIS selection happened, not when the run was generated

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "suite_id": self.suite_id,
            "scenario": self.scenario,
            "seed": self.seed,
            "scale": self.scale,
            "generator_version": self.generator_version,
            "contract_version_set": self.contract_version_set,
            "config_hash": self.config_hash,
            "global_content_hash": self.global_content_hash,
            "source_path": self.source_path,
            "row_counts": self.row_counts,
            "selected_at": self.selected_at,
        }


def _read_manifest(run_dir: Path) -> dict[str, object]:
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.is_file():
        raise SourceSelectionError(
            f"No manifest.json found for run at '{run_dir}' - refusing to load an "
            "unvalidated/incomplete run into the warehouse."
        )
    try:
        payload: dict[str, object] = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SourceSelectionError(f"manifest.json at '{run_dir}' is unreadable: {exc}") from exc
    return payload


def _validate_manifest(manifest: dict[str, object], run_id: str) -> None:
    if manifest.get("status") != "completed":
        raise SourceSelectionError(
            f"Run '{run_id}' has status '{manifest.get('status')}', not 'completed' - "
            "refusing to load a failed or incomplete run into the warehouse."
        )
    if manifest.get("validation_passed") is not True:
        raise SourceSelectionError(
            f"Run '{run_id}' did not pass strict contract validation "
            f"(validation_passed={manifest.get('validation_passed')}) - refusing to load it."
        )
    global_hash = manifest.get("global_content_hash")
    if not isinstance(global_hash, str) or not global_hash:
        raise SourceSelectionError(f"Run '{run_id}' has no valid global_content_hash.")
    contract_version_set = manifest.get("contract_version_set")
    if contract_version_set not in SUPPORTED_CONTRACT_VERSION_SETS:
        raise SourceSelectionError(
            f"Run '{run_id}' was generated against contract_version_set "
            f"'{contract_version_set}', which this warehouse does not declare support for "
            f"(supported: {SUPPORTED_CONTRACT_VERSION_SETS}). Regenerate the run with a "
            "supported generator version, or extend SUPPORTED_CONTRACT_VERSION_SETS after "
            "re-verifying the warehouse models against the new contract shape."
        )


def _load_one_run(run_id: str, operational_root: Path, suite_id: str | None) -> SourceRecord:
    try:
        run_dir = resolve_within_directory(operational_root, run_id)
    except PathSafetyError as exc:
        raise SourceSelectionError(f"Invalid run id '{run_id}': {exc}") from exc

    if not run_dir.is_dir():
        raise SourceSelectionError(
            f"No run found at '{run_dir}' (run_id='{run_id}'). Never guessed or defaulted - "
            "check the run_id/suite_id and try again."
        )

    # Defense in depth, even though resolve_within_directory already confines
    # run_dir under operational_root (data/synthetic/, never data/quarantine/):
    # explicitly reject anything whose path contains a "quarantine" segment.
    if "quarantine" in run_dir.parts:
        raise SourceSelectionError(
            f"Run '{run_id}' resolves under a quarantine path - refusing to load it."
        )

    manifest = _read_manifest(run_dir)
    _validate_manifest(manifest, run_id)

    operational_dir = run_dir / "operational"
    if not operational_dir.is_dir():
        raise SourceSelectionError(f"Run '{run_id}' has no operational/ directory.")

    tables_section = manifest.get("tables")
    row_counts: dict[str, int] = {}
    if isinstance(tables_section, dict):
        for name, info in tables_section.items():
            if isinstance(info, dict) and "row_count" in info:
                row_counts[str(name)] = int(info["row_count"])
    # generation_runs itself is excluded from manifest["tables"] (see
    # credlens.generation.orchestrator's reproducibility-hash comment) but
    # is a real parquet file on disk - count it directly for an accurate
    # row-count audit trail.
    generation_runs_path = operational_dir / "generation_runs.parquet"
    if generation_runs_path.is_file():
        import pandas as pd

        row_counts["generation_runs"] = len(pd.read_parquet(generation_runs_path))

    raw_seed = manifest.get("seed", 0)
    seed = int(raw_seed) if isinstance(raw_seed, (int, float, str)) else 0

    return SourceRecord(
        run_id=run_id,
        suite_id=suite_id,
        scenario=str(manifest.get("scenario", "")),
        seed=seed,
        scale=str(manifest.get("scale", "")),
        generator_version=str(manifest.get("generator_version", "")),
        contract_version_set=str(manifest.get("contract_version_set", "")),
        config_hash=str(manifest.get("config_hash", "")),
        global_content_hash=str(manifest.get("global_content_hash", "")),
        source_path=operational_dir.resolve().as_posix(),
        row_counts=row_counts,
        selected_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


def resolve_sources(
    *,
    run_id: str | None = None,
    suite_id: str | None = None,
) -> list[SourceRecord]:
    """Resolves exactly one of `run_id` (a single run) or `suite_id` (a
    baseline + every one of its CRN scenario runs) into a validated list of
    SourceRecord. Raises SourceSelectionError - never returns a partial or
    best-effort result - if any selected run fails a safety check."""
    if (run_id is None) == (suite_id is None):
        raise SourceSelectionError(
            "Exactly one of run_id or suite_id must be given (they are mutually exclusive) - "
            f"got run_id={run_id!r}, suite_id={suite_id!r}."
        )

    config = load_generation_config()
    operational_root = Path(config.output.operational_dir).resolve()

    if run_id is not None:
        return [_load_one_run(run_id, operational_root, suite_id=None)]

    assert suite_id is not None
    try:
        suite_manifest = load_suite_manifest(suite_id)
    except SuiteError as exc:
        raise SourceSelectionError(str(exc)) from exc

    run_ids = [str(suite_manifest["baseline_run_id"])]
    scenario_run_ids = suite_manifest.get("scenario_run_ids", {})
    if isinstance(scenario_run_ids, dict):
        run_ids.extend(str(v) for v in scenario_run_ids.values())

    return [_load_one_run(rid, operational_root, suite_id=suite_id) for rid in run_ids]
