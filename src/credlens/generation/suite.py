"""Counterfactual suites: one baseline run plus one run per CRN scenario,
sharing common random numbers, tied together by a suite manifest (Phase
4B sections 5, 9, 10, 16). See docs/common_random_numbers.md and
docs/counterfactual_scenarios.md.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from credlens.generation.comparison import compare_metrics, compute_metrics
from credlens.generation.config import (
    CRN_SCENARIOS,
    config_path_for_scenario,
    load_generation_config,
)
from credlens.generation.manifest import canonical_table_hash
from credlens.generation.orchestrator import GenerationOutcome, generate_scenario


class SuiteError(Exception):
    """Raised when a suite cannot be generated or an invariant it claims to hold does not."""


@dataclass
class SuiteOutcome:
    suite_id: str
    baseline_run_id: str
    scenario_run_ids: dict[str, str]
    outcomes: dict[str, GenerationOutcome]
    manifest: dict[str, object]
    manifest_path: Path


def _suite_id(scale_name: str, seed: int) -> str:
    return f"SUITE_{scale_name}_{seed}"


def _drop_run_metadata_columns(df: pd.DataFrame) -> pd.DataFrame:
    return df.drop(columns=[c for c in df.columns if c == "generation_run_id"], errors="ignore")


def _population_hashes(operational_dir: Path) -> dict[str, str]:
    hashes = {}
    for table in ("customers", "application_features", "fairness_attributes"):
        path = operational_dir / f"{table}.parquet"
        if path.is_file():
            hashes[table] = canonical_table_hash(_drop_run_metadata_columns(pd.read_parquet(path)))
    applications_path = operational_dir / "applications.parquet"
    if applications_path.is_file():
        applications = pd.read_parquet(applications_path)
        # applications.status legitimately differs when a scenario changes the
        # policy cutoff (policy_expansion/policy_tightening) - excluded from
        # the population hash for exactly that reason; every other column
        # (submission-time content) is still checked. generation_run_id is
        # metadata (identifies the RUN, not the entity) - excluded from
        # every table here for the same reason.
        comparable = _drop_run_metadata_columns(applications).drop(
            columns=["status"], errors="ignore"
        )
        hashes["applications"] = canonical_table_hash(comparable)
    return hashes


def _config_diff(
    baseline_config_dump: dict[str, object], scenario_config_dump: dict[str, object]
) -> dict[str, dict[str, object]]:
    diff: dict[str, dict[str, object]] = {}
    for key in sorted(set(baseline_config_dump) | set(scenario_config_dump)):
        b_val = baseline_config_dump.get(key)
        s_val = scenario_config_dump.get(key)
        if b_val != s_val:
            diff[key] = {"baseline": b_val, "scenario": s_val}
    return diff


def _directional_checks(
    scenario: str,
    baseline_outcome: GenerationOutcome,
    scenario_outcome: GenerationOutcome,
    baseline_dir: Path,
    scenario_dir: Path,
) -> list[dict[str, object]]:
    checks: list[dict[str, object]] = []

    if scenario in ("policy_expansion", "policy_tightening"):
        base_apps = pd.read_parquet(baseline_dir / "applications.parquet")
        scen_apps = pd.read_parquet(scenario_dir / "applications.parquet")
        base_approved = set(base_apps.loc[base_apps["status"] == "approved", "application_id"])
        scen_approved = set(scen_apps.loc[scen_apps["status"] == "approved", "application_id"])
        if scenario == "policy_expansion":
            passed = base_approved.issubset(scen_approved)
            checks.append(
                {
                    "name": "baseline_approved_subset_of_expansion_approved",
                    "type": "invariant",
                    "passed": passed,
                    "detail": f"baseline={len(base_approved)} approved, "
                    f"expansion={len(scen_approved)} approved",
                }
            )
        else:
            passed = scen_approved.issubset(base_approved)
            checks.append(
                {
                    "name": "tightening_approved_subset_of_baseline_approved",
                    "type": "invariant",
                    "passed": passed,
                    "detail": f"baseline={len(base_approved)} approved, "
                    f"tightening={len(scen_approved)} approved",
                }
            )

    if scenario == "macroeconomic_stress":
        shock_date = None
        cfg = load_generation_config(config_path_for_scenario(scenario))
        if cfg.macro_shock is not None:
            shock_date = cfg.macro_shock.shock_date.isoformat()
        if shock_date is not None:
            base_pay = pd.read_parquet(baseline_dir / "payments.parquet")
            scen_pay = pd.read_parquet(scenario_dir / "payments.parquet")
            cols = [
                "customer_id",
                "payment_timestamp",
                "amount",
                "channel",
                "status",
                "settlement_date",
            ]
            base_pre = (
                base_pay[base_pay["settlement_date"] < shock_date][cols]
                .sort_values(["customer_id", "settlement_date"])
                .reset_index(drop=True)
            )
            scen_pre = (
                scen_pay[scen_pay["settlement_date"] < shock_date][cols]
                .sort_values(["customer_id", "settlement_date"])
                .reset_index(drop=True)
            )
            identical = canonical_table_hash(base_pre) == canonical_table_hash(scen_pre)
            checks.append(
                {
                    "name": "pre_shock_payments_identical_to_baseline",
                    "type": "invariant",
                    "passed": identical,
                    "detail": f"shock_date={shock_date}, "
                    f"{len(base_pre)} baseline / {len(scen_pre)} stress pre-shock payments",
                }
            )

    if scenario == "collections_change":
        base_pay = pd.read_parquet(baseline_dir / "payments.parquet")
        scen_pay = pd.read_parquet(scenario_dir / "payments.parquet")
        checks.append(
            {
                "name": "collection_activity_present",
                "type": "invariant",
                "passed": (scenario_dir / "collection_events.parquet").is_file(),
                "detail": "collection_events.parquet exists for this run",
            }
        )
        # origin (customers/applications/features/fairness) identity is
        # already checked by common_population_hashes below - this check
        # only confirms payments exist so a direction comparison is meaningful.
        checks.append(
            {
                "name": "payments_exist_both_runs",
                "type": "invariant",
                "passed": len(base_pay) > 0 and len(scen_pay) > 0,
                "detail": f"baseline={len(base_pay)} payments, scenario={len(scen_pay)} payments",
            }
        )

    return checks


def generate_suite(
    *,
    scale_name: str,
    seed: int,
    force: bool = False,
    scenarios: tuple[str, ...] = CRN_SCENARIOS,
) -> SuiteOutcome:
    """Generates one baseline run and one run per `scenarios` (default:
    every CRN scenario), all sharing common random numbers for the same
    seed, and writes a suite manifest tying them together."""
    suite_id = _suite_id(scale_name, seed)

    baseline_outcome = generate_scenario(
        scenario="baseline", scale_name=scale_name, seed=seed, force=force, suite_id=suite_id
    )
    baseline_dir = baseline_outcome.operational_dir / "operational"
    baseline_config = load_generation_config()
    baseline_dump = baseline_config.model_dump(mode="json", exclude_none=True)

    outcomes: dict[str, GenerationOutcome] = {"baseline": baseline_outcome}
    scenario_run_ids: dict[str, str] = {}
    scenario_reports: dict[str, object] = {}

    for scenario in scenarios:
        outcome = generate_scenario(
            scenario=scenario,
            scale_name=scale_name,
            seed=seed,
            force=force,
            suite_id=suite_id,
            parent_run_id=baseline_outcome.generation_run_id,
        )
        outcomes[scenario] = outcome
        scenario_run_ids[scenario] = outcome.generation_run_id
        scenario_dir = outcome.operational_dir / "operational"

        scenario_config = load_generation_config(config_path_for_scenario(scenario))
        scenario_dump = scenario_config.model_dump(mode="json", exclude_none=True)
        config_diff = _config_diff(baseline_dump, scenario_dump)

        baseline_pop_hashes = _population_hashes(baseline_dir)
        scenario_pop_hashes = _population_hashes(scenario_dir)
        population_crn_ok = baseline_pop_hashes == scenario_pop_hashes

        baseline_metrics = compute_metrics(
            baseline_outcome.generation_run_id, baseline_dir, baseline_outcome.truth_dir
        )
        scenario_metrics = compute_metrics(
            outcome.generation_run_id, scenario_dir, outcome.truth_dir
        )
        metric_comparisons = compare_metrics(baseline_metrics, scenario_metrics)

        directional_checks = _directional_checks(
            scenario, baseline_outcome, outcome, baseline_dir, scenario_dir
        )

        scenario_reports[scenario] = {
            "run_id": outcome.generation_run_id,
            "config_diff": config_diff,
            "population_crn_preserved": population_crn_ok,
            "population_hashes": {"baseline": baseline_pop_hashes, "scenario": scenario_pop_hashes},
            "baseline_metrics": baseline_metrics.to_dict(),
            "scenario_metrics": scenario_metrics.to_dict(),
            "metric_comparisons": [c.to_dict() for c in metric_comparisons],
            "directional_checks": directional_checks,
        }

    manifest = {
        "suite_id": suite_id,
        "baseline_run_id": baseline_outcome.generation_run_id,
        "scenario_run_ids": scenario_run_ids,
        "seed": seed,
        "scale": scale_name,
        "dgp_version": baseline_outcome.manifest.get("generator_version"),
        "scenarios": scenario_reports,
    }

    manifest_dir = Path("reports/synthetic_validation/suites")
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / f"{suite_id}.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    return SuiteOutcome(
        suite_id=suite_id,
        baseline_run_id=baseline_outcome.generation_run_id,
        scenario_run_ids=scenario_run_ids,
        outcomes=outcomes,
        manifest=manifest,
        manifest_path=manifest_path,
    )


def load_suite_manifest(suite_id: str) -> dict[str, object]:
    path = Path("reports/synthetic_validation/suites") / f"{suite_id}.json"
    if not path.is_file():
        raise SuiteError(f"No suite manifest found for '{suite_id}' at '{path}'.")
    payload: dict[str, object] = json.loads(path.read_text(encoding="utf-8"))
    return payload
