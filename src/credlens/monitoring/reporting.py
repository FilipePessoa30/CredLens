"""Orchestrates the `credlens monitor create-reference/simulate-batches/
run/report` CLI subcommands and the bilingual monitoring report (Phase 9
section 24).
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from credlens.monitoring.alerts import load_alerts
from credlens.monitoring.batches import build_batches, write_batches
from credlens.monitoring.contracts import (
    load_reference_config,
    load_scenarios_config,
    load_thresholds_config,
)
from credlens.monitoring.provenance import (
    MONITORING_SIMULATION_LABEL_EN,
    MONITORING_SIMULATION_LABEL_PT_BR,
    NOT_A_PRODUCTION_MONITORING_SYSTEM_EN,
    NOT_A_PRODUCTION_MONITORING_SYSTEM_PT_BR,
)
from credlens.monitoring.reference import build_reference, write_reference
from credlens.monitoring.runner import load_run, run_monitoring
from credlens.monitoring.thresholds import (
    calibrate_thresholds,
    load_calibrated_thresholds,
    write_calibrated_thresholds,
)

REPORTS_DIR = Path("reports/monitoring")


class MonitoringReportingError(Exception):
    """Raised for pipeline-ordering/IO failures in the monitoring layer."""


def create_reference(model_id: str, *, repo_root: Path | None = None) -> str:
    repo_root = repo_root or Path.cwd()
    reference_config = load_reference_config(repo_root)
    reference, population = build_reference(
        model_id, repo_root=repo_root, reference_config=reference_config
    )
    write_reference(reference, population, repo_root=repo_root)

    thresholds_config = load_thresholds_config(repo_root)
    scenarios_config = load_scenarios_config(repo_root)
    calibrated = calibrate_thresholds(
        population,
        reference.feature_stats,
        thresholds_config,
        batch_size=scenarios_config.batch_size,
        feature_columns=list(reference.feature_stats.keys()),
    )
    write_calibrated_thresholds(reference.reference_id, calibrated, repo_root=repo_root)
    return reference.reference_id


def calibrate_reference_family_wise(
    reference_id: str, *, repo_root: Path | None = None
) -> dict[str, Any]:
    """Phase 10 gate F - adds the family-wise PSI threshold (metric
    `psi_family_wise`) to an ALREADY-BUILT reference's calibrated-
    thresholds file, alongside (never replacing) the existing per-feature
    entries `calibrate_thresholds` already wrote. An empirical audit
    (`credlens.monitoring.calibration_study`) found the per-feature
    calibration alone produces a ~60% family-wise false-alert rate across
    18 simultaneous PSI checks; this threshold, calibrated on the MAX PSI
    across all features per resample, is what
    `credlens.monitoring.runner` and the gate G/H incident/severity logic
    use to decide whether a batch's feature drift is family-wise
    significant. Requires `credlens monitor create-reference` to have
    already run."""
    repo_root = repo_root or Path.cwd()
    from credlens.monitoring.calibration_study import calibrate_family_wise_psi_threshold
    from credlens.monitoring.reference import load_reference, load_reference_population

    reference = load_reference(reference_id, repo_root=repo_root)
    reference_population = load_reference_population(reference_id, repo_root=repo_root)
    thresholds_config = load_thresholds_config(repo_root)
    mc_cfg = thresholds_config.multiple_comparisons
    study_cfg = thresholds_config.calibration_study
    scenarios_config = load_scenarios_config(repo_root)

    family_wise = calibrate_family_wise_psi_threshold(
        reference_population,
        reference,
        batch_size=scenarios_config.batch_size,
        n_resamples=int(mc_cfg["family_wise_n_resamples"]),
        review_percentile=float(mc_cfg["family_wise_review_percentile"]),
        material_percentile=float(mc_cfg["family_wise_material_deviation_percentile"]),
        seed=int(study_cfg["seed"]),
    )
    calibrated = load_calibrated_thresholds(reference_id, repo_root=repo_root)
    calibrated["psi_family_wise"] = family_wise
    write_calibrated_thresholds(reference_id, calibrated, repo_root=repo_root)
    return {"reference_id": reference_id, "psi_family_wise": family_wise.to_dict()}


def simulate_batches(reference_id: str, *, repo_root: Path | None = None) -> str:
    repo_root = repo_root or Path.cwd()
    from credlens.monitoring.reference import load_reference

    reference = load_reference(reference_id, repo_root=repo_root)
    scenarios_config = load_scenarios_config(repo_root)
    batches = build_batches(reference.model_id, scenarios_config, repo_root=repo_root)
    batch_set_id = f"BATCHSET_{reference_id}"
    write_batches(batch_set_id, batches, repo_root=repo_root)
    return batch_set_id


def run(reference_id: str, batch_set_id: str, *, repo_root: Path | None = None) -> str:
    run_id, _results, _alerts = run_monitoring(reference_id, batch_set_id, repo_root=repo_root)
    return run_id


def status(run_id: str, *, repo_root: Path | None = None) -> dict[str, Any]:
    return load_run(run_id, repo_root=repo_root)


def false_alert_rate(run_id: str, *, repo_root: Path | None = None) -> float:
    """The fraction of alerts raised on the `baseline_like` batch
    (sequence 1, unperturbed) - this batch is drawn from the SAME
    distribution as the reference, so any alert here is, by construction,
    a false alert (Phase 9 section 16: "taxa de falso alerta no batch
    normal")."""
    run_record = load_run(run_id, repo_root=repo_root)
    alerts = load_alerts(run_id, repo_root=repo_root)
    baseline_batch = next(
        (b for b in run_record["batches"] if b["simulation_scenario"] == "baseline_like"), None
    )
    if baseline_batch is None:
        return 0.0
    baseline_alerts = [a for a in alerts if a["batch_sequence"] == baseline_batch["batch_sequence"]]
    n_checks = (
        len(baseline_batch.get("feature_drift", [])) + 3
    )  # +score/perf/subgroup checks, approx
    return len(baseline_alerts) / max(n_checks, 1)


def _content_fingerprint(payload: dict[str, Any]) -> str:
    cleaned = {k: v for k, v in payload.items() if k != "generated_at_utc"}
    return hashlib.sha256(json.dumps(cleaned, sort_keys=True).encode("utf-8")).hexdigest()


def generate_monitoring_report(run_id: str, language: str, *, repo_root: Path | None = None) -> str:
    repo_root = repo_root or Path.cwd()
    run_record = load_run(run_id, repo_root=repo_root)
    alerts = load_alerts(run_id, repo_root=repo_root)
    rate = false_alert_rate(run_id, repo_root=repo_root)

    batch_lines = "\n".join(
        f"| {b['batch_sequence']} | {b['simulation_scenario']} | {b['label_availability']} | "
        f"{'blocked' if b['blocked'] else 'scored'} | {b['n_rows']} | {b['n_quarantined']} |"
        for b in run_record["batches"]
    )
    alert_lines = "\n".join(
        f"| {a['alert_id']} | {a['batch_sequence']} | {a['severity']} | {a['category']} | "
        f"{a['metric']} | {a['status']} |"
        for a in alerts
    )

    if language == "pt-BR":
        return f"""# Relatório de Monitoramento (Fase 9)

**{MONITORING_SIMULATION_LABEL_PT_BR}**

{NOT_A_PRODUCTION_MONITORING_SYSTEM_PT_BR}

## Execução
`{run_id}` - referência `{run_record["reference_id"]}`,
conjunto de batches `{run_record["batch_set_id"]}`, modelo `{run_record["model_id"]}`.

## Batches simulados
| Sequência | Cenário | Rótulos | Status | Linhas | Quarentena |
|---|---|---|---|---|---|
{batch_lines}

## Alertas ({len(alerts)})
| Alert ID | Batch | Severidade | Categoria | Métrica | Status |
|---|---|---|---|---|---|
{alert_lines if alerts else "| (nenhum alerta) | | | | | |"}

## Taxa de falso alerta (batch baseline-like)
{rate:.4f}

## Limitações
Batches simulados a partir do conjunto de teste bloqueado da UCI, particionado por ID - nunca datas
reais de produção. Ações diagnósticas são sugestões, nunca decisões automáticas.
"""

    return f"""# Monitoring Report (Phase 9)

**{MONITORING_SIMULATION_LABEL_EN}**

{NOT_A_PRODUCTION_MONITORING_SYSTEM_EN}

## Run
`{run_id}` - reference `{run_record["reference_id"]}`,
batch set `{run_record["batch_set_id"]}`, model `{run_record["model_id"]}`.

## Simulated batches
| Sequence | Scenario | Labels | Status | Rows | Quarantined |
|---|---|---|---|---|---|
{batch_lines}

## Alerts ({len(alerts)})
| Alert ID | Batch | Severity | Category | Metric | Status |
|---|---|---|---|---|---|
{alert_lines if alerts else "| (no alerts) | | | | | |"}

## False-alert rate (baseline-like batch)
{rate:.4f}

## Limitations
Batches are simulated partitions of the UCI locked test set, sliced by ID - never real dated
production data. Diagnostic actions are suggestions, never automated decisions.
"""


def write_monitoring_reports(run_id: str, *, repo_root: Path | None = None) -> dict[str, Path]:
    repo_root = repo_root or Path.cwd()
    out_dir = repo_root / REPORTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    for filename, content in (
        ("monitoring_report.md", generate_monitoring_report(run_id, "en", repo_root=repo_root)),
        (
            "monitoring_report.pt-BR.md",
            generate_monitoring_report(run_id, "pt-BR", repo_root=repo_root),
        ),
    ):
        path = out_dir / filename
        path.write_text(content, encoding="utf-8")
        written[filename] = path

    manifest = {
        "run_id": run_id,
        "reports_written": sorted(written.keys()),
        "generated_at_utc": datetime.now(UTC).isoformat(),
    }
    manifest["content_fingerprint"] = _content_fingerprint(manifest)
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    written["manifest.json"] = manifest_path
    return written


def validate_run(run_id: str, *, repo_root: Path | None = None) -> bool:
    """A lightweight structural check: the run record parses, references
    an existing reference/batch-set, and every batch's row accounting is
    internally consistent (n_rows >= n_quarantined)."""
    repo_root = repo_root or Path.cwd()
    run_record = load_run(run_id, repo_root=repo_root)
    reference_path = (
        repo_root / "reports" / "monitoring" / "reference" / f"{run_record['reference_id']}.json"
    )
    if not reference_path.is_file():
        return False
    return all(batch["n_quarantined"] <= batch["n_rows"] for batch in run_record["batches"])
