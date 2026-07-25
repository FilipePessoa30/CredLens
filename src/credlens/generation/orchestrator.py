"""Ties every generation step together into one baseline run.

Order matches the causal chain this phase requires (customer ->
application -> frozen features -> decision -> contract -> schedule ->
payment behavior -> allocation -> snapshot -> collections -> write-off ->
recovery -> macro context), see docs/temporal_semantics.md.
"""

from __future__ import annotations

import platform
import time
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from credlens.contracts.registry import load_all_contracts
from credlens.generation.applications import apply_cancellations, generate_applications
from credlens.generation.config import GenerationConfig, Scale, load_generation_config
from credlens.generation.contracts import generate_contracts
from credlens.generation.decisions import generate_credit_decisions
from credlens.generation.ids import IdFactory, run_short_hash
from credlens.generation.macro import generate_macro_context
from credlens.generation.manifest import (
    build_manifest,
    canonical_config_hash,
    canonical_run_hash,
    canonical_table_hash,
    write_manifest,
)
from credlens.generation.payments import simulate_portfolio_ledger
from credlens.generation.policies import generate_policy_versions
from credlens.generation.population import generate_customers
from credlens.generation.rng import RunRandomStreams
from credlens.generation.schedules import generate_installments
from credlens.generation.truth import attach_contract_truth, generate_latent_customer_truth
from credlens.generation.validation import GenerationValidationOutcome, validate_generated_portfolio
from credlens.generation.writers import (
    discard_staging,
    promote_staging,
    resolve_within_directory,
    stage_directory,
    write_operational_tables,
    write_truth_tables,
)

GENERATOR_VERSION = "0.4.0"


class GenerationError(Exception):
    """Raised for a rejected or failed generation request."""


class ScenarioNotCalibratedError(GenerationError):
    """Raised when a non-baseline scenario is requested - Phase 4A only implements baseline."""


class RunAlreadyExistsError(GenerationError):
    """Raised when a run directory already exists and --force was not given."""


@dataclass
class GenerationOutcome:
    generation_run_id: str
    operational_dir: Path
    truth_dir: Path
    manifest: dict[str, object]
    validation: GenerationValidationOutcome
    status: str  # "completed" | "failed"


def _compute_generation_run_id(scenario: str, scale: str, seed: int, config_hash: str) -> str:
    """Deterministic: the same (scenario, scale, seed, config) always
    produces the same run id - required so a re-run with identical
    inputs is recognizably "the same run" (and so --force is meaningful)."""
    short = run_short_hash(config_hash, length=8)
    return f"RUN_{scenario}_{scale}_{seed}_{short}"


def generate_baseline(
    *,
    scenario: str,
    scale_name: str,
    seed: int,
    config_path: Path | None = None,
    force: bool = False,
) -> GenerationOutcome:
    if scenario != "baseline":
        raise ScenarioNotCalibratedError(
            f"Scenario '{scenario}' is not calibrated in Phase 4A - only 'baseline' has an "
            f"executable configuration. See config/synthetic/scenarios/{scenario}.blueprint.yaml "
            "(status: requires_calibration)."
        )

    config = load_generation_config(config_path) if config_path else load_generation_config()
    try:
        scale = Scale(scale_name)
    except ValueError as exc:
        raise GenerationError(
            f"Unknown scale '{scale_name}'. Known scales: {[s.value for s in Scale]}"
        ) from exc
    if scale not in config.scales:
        raise GenerationError(f"Scale '{scale.value}' has no preset in the generation config.")

    started_at = pd.Timestamp.utcnow()
    t0 = time.monotonic()

    config_hash = canonical_config_hash(config)
    generation_run_id = _compute_generation_run_id(scenario, scale.value, seed, config_hash)
    short_hash = run_short_hash(config_hash, length=8)

    operational_final_dir = resolve_within_directory(
        Path(config.output.operational_dir), generation_run_id
    )
    truth_final_dir = resolve_within_directory(Path(config.output.truth_dir), generation_run_id)

    if operational_final_dir.exists() and not force:
        raise RunAlreadyExistsError(
            f"Run '{generation_run_id}' already exists at '{operational_final_dir}'. Pass --force "
            "to overwrite."
        )

    n_customers = config.scales[scale].customers
    streams = RunRandomStreams(seed)

    customers = generate_customers(
        n_customers,
        config.period,
        generation_run_id,
        IdFactory("customer", short_hash),
        streams.stream("customers"),
    )
    applications, features, fairness = generate_applications(
        customers,
        config.period,
        config.applications,
        config.population,
        generation_run_id,
        IdFactory("application", short_hash),
        streams.stream("applications"),
    )
    applications = apply_cancellations(
        applications, config.applications.cancellation_rate, streams.stream("applications")
    )

    policy_versions = generate_policy_versions(
        config.period, IdFactory("policy_version", short_hash)
    )
    credit_decisions, applications = generate_credit_decisions(
        applications,
        features,
        policy_versions["policy_version_id"].iloc[0],
        config.policy,
        config.population.declared_income_min,
        config.population.declared_income_max,
        IdFactory("decision", short_hash),
        streams.stream("decisions"),
    )

    contracts_df = generate_contracts(
        applications,
        credit_decisions,
        config.booking,
        config.contract,
        config.currency_unit,
        IdFactory("contract", short_hash),
        streams.stream("booking"),
    )
    installments = generate_installments(contracts_df, IdFactory("installment", short_hash))

    customer_truth = generate_latent_customer_truth(customers, streams.stream("truth"))
    contract_truth = attach_contract_truth(contracts_df, customer_truth)

    id_factories = {
        "payment": IdFactory("payment", short_hash),
        "allocation": IdFactory("allocation", short_hash),
        "write_off": IdFactory("write_off", short_hash),
        "collection_event": IdFactory("collection_event", short_hash),
        "recovery": IdFactory("recovery", short_hash),
    }
    rng_streams = {
        "payments": streams.stream("payments"),
        "collections": streams.stream("collections"),
        "write_off": streams.stream("write_off"),
        "recovery": streams.stream("recovery"),
    }
    ledger = simulate_portfolio_ledger(
        contracts_df,
        installments,
        contract_truth,
        config,
        pd.Timestamp(config.period.end),
        id_factories,
        rng_streams,
    )

    macro_context = generate_macro_context(
        pd.Timestamp(config.period.start), pd.Timestamp(config.period.end)
    )

    generation_runs = pd.DataFrame(
        {
            "generation_run_id": [generation_run_id],
            "generator_version": [GENERATOR_VERSION],
            "config_version": [str(config.version)],
            "seed": [seed],
            "scenario": [scenario],
            "period_start": [config.period.start.isoformat()],
            "period_end": [config.period.end.isoformat()],
            "generated_at": [started_at.strftime("%Y-%m-%dT%H:%M:%SZ")],
            "config_hash": [config_hash],
            "contract_version_set": ["phase4a-v1"],
            "status": ["completed"],
            "planned_customers": [n_customers],
            "planned_applications": [len(applications)],
            "is_synthetic": [True],
            "scale": [scale.value],
        }
    )

    operational_tables: dict[str, pd.DataFrame] = {
        "generation_runs": generation_runs,
        "customers": customers,
        "applications": applications,
        "application_features": features,
        "fairness_attributes": fairness,
        "policy_versions": policy_versions,
        "credit_decisions": credit_decisions,
        "contracts": contracts_df,
        "installments": ledger.installments,
        "payments": ledger.payments,
        "payment_allocations": ledger.payment_allocations,
        "account_monthly_snapshots": ledger.account_monthly_snapshots,
        "collection_events": ledger.collection_events,
        "write_off_events": ledger.write_off_events,
        "recovery_events": ledger.recovery_events,
        "macro_context_monthly": macro_context,
    }

    all_contracts = load_all_contracts()
    validation = validate_generated_portfolio(operational_tables, all_contracts)

    # generation_runs is run METADATA (it records generated_at, a wall-clock
    # timestamp that legitimately differs between two otherwise-identical
    # invocations) - it is excluded from the reproducibility hash so "same
    # seed -> same content" is judged on the generated PORTFOLIO, not on
    # when a given execution happened to run. Still written to disk and
    # still counted in table_row_counts below.
    hashable_tables = {
        name: df for name, df in operational_tables.items() if name != "generation_runs"
    }
    table_hashes = {name: canonical_table_hash(df) for name, df in hashable_tables.items()}
    global_hash = canonical_run_hash(table_hashes, config_hash, seed, scenario, scale.value)

    finished_at = pd.Timestamp.utcnow()
    duration = time.monotonic() - t0
    status = "completed" if validation.passed else "failed"

    warnings = [
        f"{check.name}: {check.detail}"
        for check in validation.statistical_checks
        if not check.passed
    ]
    if not validation.pii_safe:
        warnings.append(f"PII safety: {validation.pii_detail}")

    manifest = build_manifest(
        generation_run_id=generation_run_id,
        generator_version=GENERATOR_VERSION,
        seed=seed,
        scenario=scenario,
        scale=scale.value,
        period_start=config.period.start.isoformat(),
        period_end=config.period.end.isoformat(),
        config_hash=config_hash,
        contract_version_set="phase4a-v1",
        table_row_counts={name: len(df) for name, df in operational_tables.items()},
        table_hashes=table_hashes,
        global_content_hash=global_hash,
        started_at=started_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        finished_at=finished_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        duration_seconds=round(duration, 3),
        status=status,
        validation_passed=validation.passed,
        warnings=warnings,
        python_version=platform.python_version(),
    )

    operational_staging = stage_directory(Path(config.output.operational_dir))
    truth_staging = stage_directory(Path(config.output.truth_dir))
    try:
        write_operational_tables(operational_tables, operational_staging / "operational")
        write_truth_tables(
            {"latent_customer_truth": customer_truth, "latent_contract_truth": contract_truth},
            truth_staging,
        )
        write_manifest(manifest, operational_staging / "manifest.json")
        (operational_staging / "config_snapshot.yaml").write_text(
            _config_snapshot_yaml(config), encoding="utf-8"
        )
        (operational_staging / "contract_validation.json").write_text(
            _validation_report_json(validation), encoding="utf-8"
        )
        (operational_staging / "generation_summary.json").write_text(
            _generation_summary_json(manifest, validation), encoding="utf-8"
        )
        (truth_staging / "truth_manifest.json").write_text(
            _truth_manifest_json(generation_run_id, customer_truth, contract_truth),
            encoding="utf-8",
        )

        if validation.passed:
            if operational_final_dir.exists() and force:
                discard_staging(operational_final_dir)
            if truth_final_dir.exists() and force:
                discard_staging(truth_final_dir)
            promote_staging(operational_staging, operational_final_dir)
            promote_staging(truth_staging, truth_final_dir)
            final_operational_dir = operational_final_dir
            final_truth_dir = truth_final_dir
        else:
            # Keep the diagnostic staging directories in place (under
            # .staging/) rather than promoting - a failed run is never
            # presented as valid, per this phase's requirement.
            final_operational_dir = operational_staging
            final_truth_dir = truth_staging
    except Exception:
        discard_staging(operational_staging)
        discard_staging(truth_staging)
        raise

    return GenerationOutcome(
        generation_run_id=generation_run_id,
        operational_dir=final_operational_dir,
        truth_dir=final_truth_dir,
        manifest=manifest,
        validation=validation,
        status=status,
    )


def _config_snapshot_yaml(config: GenerationConfig) -> str:
    import yaml

    return yaml.safe_dump(config.model_dump(mode="json"), sort_keys=True)


def _validation_report_json(validation: GenerationValidationOutcome) -> str:
    import json

    return json.dumps(
        {name: report.to_dict() for name, report in validation.contract_reports.items()},
        indent=2,
        sort_keys=True,
    )


def _generation_summary_json(
    manifest: dict[str, object], validation: GenerationValidationOutcome
) -> str:
    import json

    return json.dumps(
        {
            "generation_run_id": manifest["generation_run_id"],
            "status": manifest["status"],
            "contracts_passed": validation.contracts_passed,
            "statistical_checks_passed": validation.statistical_passed,
            "pii_safe": validation.pii_safe,
            "statistical_checks": [
                {"name": c.name, "passed": c.passed, "detail": c.detail}
                for c in validation.statistical_checks
            ],
        },
        indent=2,
        sort_keys=True,
    )


def _truth_manifest_json(
    run_id: str, customer_truth: pd.DataFrame, contract_truth: pd.DataFrame
) -> str:
    import json

    return json.dumps(
        {
            "generation_run_id": run_id,
            "tables": {
                "latent_customer_truth": {"row_count": len(customer_truth)},
                "latent_contract_truth": {"row_count": len(contract_truth)},
            },
            "isolation_note": (
                "This directory is physically separate from data/synthetic/, "
                "git-ignored, and never read by any operational command without "
                "an explicit --include-truth-layer-style opt-in (not implemented "
                "in Phase 4A - no command reads this directory at all today). "
                "See docs/adr/0007-synthetic-truth-isolation.md."
            ),
        },
        indent=2,
        sort_keys=True,
    )
