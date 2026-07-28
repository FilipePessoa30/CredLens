"""Orchestrates the Phase 9 independent-validation pipeline behind the
`credlens model validate-independent/audit-collinearity/audit-negative-
controls/compare-candidates/register-challenger` CLI subcommands - the
`credlens.model_validation` equivalent of `credlens.modeling.reporting`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from credlens.model_validation.calibration import ece_bin_sensitivity
from credlens.model_validation.challenger_review import (
    build_pareto_comparison,
    register_challenger,
)
from credlens.model_validation.coefficient_audit import (
    bootstrap_coefficient_samples,
    classify_coefficients,
    cv_fold_coefficient_samples,
    regularization_sensitivity_samples,
)
from credlens.model_validation.collinearity import iteratively_reduce_by_vif, run_collinearity_audit
from credlens.model_validation.decision import (
    ValidationGate,
    build_gate,
    make_decision,
    write_decision,
)
from credlens.model_validation.evidence import (
    EvidenceManifest,
    freeze_evidence,
    load_validation_config,
    write_evidence,
)
from credlens.model_validation.lifecycle import record_transition
from credlens.model_validation.negative_controls import run_permutation_negative_control
from credlens.model_validation.recomputation import run_recomputation
from credlens.model_validation.robustness_review import spot_check_robustness
from credlens.model_validation.subgroup_validation import run_subgroup_validation
from credlens.modeling.contracts import (
    load_evaluation_config,
    load_feature_registry,
    load_target_contract,
)
from credlens.modeling.data import load_uci_default_credit
from credlens.modeling.evaluation import full_metrics
from credlens.modeling.features import FEATURE_COLUMNS, engineer_features
from credlens.modeling.input_contract import validate_input_contract
from credlens.modeling.registry import (
    Experiment,
    dependency_versions,
    load_experiment,
    load_model_candidate_manifest,
    validate_model_candidate,
    write_experiment,
)
from credlens.modeling.splitting import apply_split_assignment_table, load_split_assignment_table
from credlens.modeling.training import fit_model, predict_proba_positive
from credlens.modeling.tuning import tune_logistic_regression

EXPERIMENTS_DIR = Path("reports/modeling/experiments")
MODELING_TABLES_DIR = Path("reports/modeling/tables")
MODELS_DIR = Path("reports/modeling/models")
VALIDATION_TABLES_DIR = Path("reports/model_validation/tables")
VALIDATION_REPORTS_DIR = Path("reports/model_validation")


class ModelValidationError(Exception):
    """Raised for pipeline-ordering/IO failures in the validation layer."""


def resolve_experiment_id_from_model(model_id: str, repo_root: Path) -> str:
    manifest = load_model_candidate_manifest(model_id, repo_root / MODELS_DIR)
    return manifest.experiment_id


def _sensitive_columns_absent_from_feature_set(feature_set: list[str]) -> bool:
    return not any(c in feature_set for c in ("X2", "X3", "X4", "X5"))


def _documentation_complete(repo_root: Path) -> tuple[bool, str]:
    card_en = repo_root / "reports" / "modeling" / "model_card.md"
    card_pt = repo_root / "reports" / "modeling" / "model_card.pt-BR.md"
    tech_en = repo_root / "reports" / "modeling" / "technical_report.md"
    if not (card_en.is_file() and card_pt.is_file() and tech_en.is_file()):
        return (
            False,
            "One or more of model_card.md/model_card.pt-BR.md/technical_report.md is missing.",
        )
    if "Not suitable for real lending decisions." not in card_en.read_text(encoding="utf-8"):
        return False, "model_card.md is missing the mandatory 'Not suitable...' sentence."
    if "Não é adequado para decisões reais" not in card_pt.read_text(encoding="utf-8"):
        return False, "model_card.pt-BR.md is missing the mandatory PT-BR sentence."
    return True, "model_card.md/.pt-BR.md/technical_report.md present with mandatory disclosures."


@dataclass(frozen=True)
class IndependentValidationResult:
    experiment_id: str
    model_id: str
    evidence: EvidenceManifest
    decision: Any
    n_permutations: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "model_id": self.model_id,
            "decision": self.decision.to_dict(),
            "n_permutations": self.n_permutations,
        }


def validate_independent(
    model_id: str, *, full_permutations: bool = True, repo_root: Path | None = None
) -> IndependentValidationResult:
    repo_root = repo_root or Path.cwd()
    experiment_id = resolve_experiment_id_from_model(model_id, repo_root)
    validation_config = load_validation_config(repo_root)

    evidence = freeze_evidence(experiment_id, model_id, repo_root=repo_root)
    write_evidence(evidence, repo_root=repo_root)

    tolerance = float(validation_config.recomputation["metric_absolute_tolerance"])
    recomputation = run_recomputation(
        evidence,
        tolerance,
        operating_point_tolerance=float(
            validation_config.recomputation["operating_point_tolerance"]
        ),
        repo_root=repo_root,
    )

    perm_cfg = validation_config.permutation_test
    n_permutations = (
        int(perm_cfg["n_permutations_full"])
        if full_permutations
        else int(perm_cfg["n_permutations_ci"])
    )
    permutation_report = run_permutation_negative_control(
        experiment_id,
        n_permutations=n_permutations,
        base_seed=int(perm_cfg["base_seed"]),
        alpha=float(perm_cfg["alpha"]),
        max_permutation_mean_deviation=float(
            perm_cfg["max_permutation_mean_deviation_from_random_roc_auc"]
        ),
        repo_root=repo_root,
    )

    experiment = load_experiment(repo_root / EXPERIMENTS_DIR / f"{experiment_id}.json")
    contract = load_target_contract(repo_root)
    config = load_evaluation_config(repo_root)
    df = load_uci_default_credit(repo_root)
    split_table = load_split_assignment_table(
        repo_root / EXPERIMENTS_DIR / experiment_id / "split_assignment.csv"
    )
    assignment = apply_split_assignment_table(df, split_table, id_column=contract.identifier_column)
    features = engineer_features(df)
    target = df[contract.target_column]
    x_train = features.loc[assignment.train_index]
    y_train = target.loc[assignment.train_index]
    y_test = target.loc[assignment.test_index]
    raw_test = df.loc[assignment.test_index]

    collinearity_cfg = validation_config.collinearity
    collinearity = run_collinearity_audit(x_train, collinearity_cfg)

    bootstrap_samples = bootstrap_coefficient_samples(
        x_train,
        y_train,
        n_resamples=int(collinearity_cfg["coefficient_bootstrap_n_resamples"]),
        seed=int(collinearity_cfg["coefficient_bootstrap_seed"]),
    )
    cv_samples = cv_fold_coefficient_samples(
        x_train, y_train, n_folds=int(collinearity_cfg["cv_folds_for_stability"]), seed=42
    )
    regularization_samples = regularization_sensitivity_samples(
        x_train, y_train, c_grid=list(collinearity_cfg["regularization_sensitivity_grid"])
    )

    coefficients_table = pd.read_csv(
        repo_root / MODELING_TABLES_DIR / f"{experiment_id}__coefficients.csv"
    )
    original_coefficients = dict(
        zip(coefficients_table["feature"], coefficients_table["coefficient"], strict=True)
    )
    coefficient_classifications = classify_coefficients(
        original_coefficients,
        bootstrap_samples,
        cv_samples,
        regularization_samples,
        collinearity,
        collinearity_cfg,
    )

    predictions_test = pd.read_csv(
        repo_root / MODELING_TABLES_DIR / f"{experiment_id}__predictions_test.csv"
    )
    p_test_main = predictions_test["logistic_regression"]
    threshold_row = pd.read_csv(
        repo_root / MODELING_TABLES_DIR / f"{experiment_id}__thresholds.csv"
    )
    top10_threshold = float(
        threshold_row[threshold_row["name"] == "top_10_pct"].iloc[0]["threshold"]
    )
    subgroup_validation = run_subgroup_validation(
        raw_test,
        pd.Series(predictions_test["y_true"].to_numpy(), index=raw_test.index),
        pd.Series(p_test_main.to_numpy(), index=raw_test.index),
        threshold=top10_threshold,
        age_buckets=config.subgroup_audit["age_buckets"],
        bootstrap_cfg=validation_config.subgroup_bootstrap,
    )

    import joblib

    from credlens.modeling.training import FittedModel

    logistic_pipeline_path = (
        repo_root / EXPERIMENTS_DIR / experiment_id / "models" / "logistic_regression.joblib"
    )
    if not logistic_pipeline_path.is_file():
        raise ModelValidationError(
            f"No trained logistic regression artifact at '{logistic_pipeline_path}'."
        )
    fitted_logistic = FittedModel(
        model_kind="logistic_regression",
        pipeline=joblib.load(logistic_pipeline_path),
        hyperparameters=experiment.hyperparameters,
        seed=experiment.seed,
        n_jobs=1,
        fit_seconds=0.0,
        feature_columns=list(FEATURE_COLUMNS),
    )
    original_robustness_table = pd.read_csv(
        repo_root / MODELING_TABLES_DIR / f"{experiment_id}__robustness.csv"
    )
    robustness_comparisons = spot_check_robustness(
        fitted_logistic,
        raw_test,
        y_test,
        original_robustness_table,
        robustness_cfg=config.robustness,
        tolerance=tolerance,
        stochastic_tolerance=float(
            validation_config.recomputation["robustness_stochastic_tolerance"]
        ),
    )

    strict_probes = _run_input_contract_self_test(df.head(5))
    artifact_ok = validate_model_candidate(model_id, repo_root / MODELS_DIR)
    reproducibility_ok, reproducibility_detail = _check_reproducibility(evidence, repo_root)
    documentation_ok, documentation_detail = _documentation_complete(repo_root)

    gates_cfg = validation_config.gates
    gates: list[ValidationGate] = []
    gates.append(
        build_gate(
            "dataset_integrity",
            evidence.dataset_hash.lower() == contract.acquired_hash_sha256.lower(),
            severity="blocking",
            evidence=f"evidence.dataset_hash={evidence.dataset_hash[:16]}...",
            threshold="matches config/modeling/behavioral_default.yml's acquired_hash_sha256",
        )
    )
    gates.append(
        build_gate(
            "split_integrity",
            evidence.split_hash == experiment.split_hash,
            severity="blocking",
            evidence=(
                f"recomputed split hash matches experiment record ({evidence.split_hash[:16]}...)"
            ),
            threshold="combined split hash unchanged since training",
        )
    )
    gates.append(
        build_gate(
            "leakage",
            not experiment.warnings
            and _sensitive_columns_absent_from_feature_set(experiment.feature_set),
            severity="blocking",
            evidence=f"experiment.warnings={experiment.warnings}",
            threshold="no Phase 8 negative-control failures; no sensitive column in feature_set",
        )
    )
    gates.append(
        build_gate(
            "negative_controls",
            permutation_report.passed,
            severity="blocking",
            evidence=permutation_report.reason,
            threshold=f"empirical p<={permutation_report.alpha}, |null mean - 0.5|<="
            f"{permutation_report.max_permutation_mean_deviation_from_random_roc_auc}",
        )
    )
    gates.append(
        build_gate(
            "discrimination",
            all(c.within_tolerance for c in recomputation.discrimination_comparisons)
            and evidence.original_test_metrics["discrimination"]["roc_auc"]
            >= float(gates_cfg["min_test_roc_auc"]),
            severity="blocking",
            evidence=(
                f"{len(recomputation.discrimination_comparisons)} metric(s) recomputed "
                "within tolerance"
            ),
            threshold=f"tolerance={tolerance}, min_test_roc_auc={gates_cfg['min_test_roc_auc']}",
        )
    )
    gates.append(
        build_gate(
            "calibration",
            all(c.within_tolerance for c in recomputation.calibration_comparisons),
            severity="blocking",
            evidence=(
                f"{len(recomputation.calibration_comparisons)} calibration metric(s) "
                "recomputed within tolerance"
            ),
            threshold=f"tolerance={tolerance}",
        )
    )
    gates.append(
        build_gate(
            "stability",
            all(c.within_tolerance for c in recomputation.stability.comparisons)
            and recomputation.stability.roc_auc_stdev
            <= float(gates_cfg["max_split_stability_roc_auc_stdev"]),
            severity="blocking",
            evidence=f"roc_auc_stdev={recomputation.stability.roc_auc_stdev:.4f}",
            threshold=f"max_split_stability_roc_auc_stdev={gates_cfg['max_split_stability_roc_auc_stdev']}",
        )
    )
    unstable_features = [
        c.feature
        for c in coefficient_classifications
        if c.category in ("unstable_direction", "redundant")
    ]
    gates.append(
        build_gate(
            "coefficient_stability",
            not unstable_features,
            severity="non_blocking",
            evidence=f"unstable/redundant features: {unstable_features}"
            if unstable_features
            else "none flagged",
            threshold=f"sign_flip_rate_unstable_threshold={collinearity_cfg['sign_flip_rate_unstable_threshold']}",
            warn_instead_of_fail=True,
        )
    )
    max_selection_gap = max(
        (
            g.absolute_gap
            for g in subgroup_validation.gap_reports
            if g.metric == "selection_rate" and g.absolute_gap is not None
        ),
        default=0.0,
    )
    gates.append(
        build_gate(
            "subgroup_audit",
            (max_selection_gap or 0.0) <= float(gates_cfg["max_subgroup_selection_rate_gap"]),
            severity="non_blocking",
            evidence=f"max selection-rate absolute_gap={max_selection_gap:.4f}",
            threshold=f"max_subgroup_selection_rate_gap={gates_cfg['max_subgroup_selection_rate_gap']}",
            warn_instead_of_fail=True,
        )
    )
    gates.append(
        build_gate(
            "robustness",
            all(c.within_tolerance for c in robustness_comparisons),
            severity="blocking",
            evidence=f"{len(robustness_comparisons)} spot-checked perturbation(s) reproduced",
            threshold="see robustness_stochastic_tolerance / metric_absolute_tolerance",
        )
    )
    gates.append(
        build_gate(
            "input_contract",
            strict_probes,
            severity="blocking",
            evidence="strict-mode self-test rejected every injected violation type",
            threshold="all built-in adversarial probes correctly blocked",
        )
    )
    gates.append(
        build_gate(
            "artifact_integrity",
            artifact_ok,
            severity="blocking",
            evidence="validate_model_candidate hash-verified and scored a probe row",
            threshold="artifact SHA-256 matches manifest; probe score in [0, 1]",
        )
    )
    gates.append(
        build_gate(
            "reproducibility",
            reproducibility_ok,
            severity="blocking",
            evidence=reproducibility_detail,
            threshold="frozen evidence hashes match current on-disk artifacts",
        )
    )
    gates.append(
        build_gate(
            "documentation",
            documentation_ok,
            severity="blocking",
            evidence=documentation_detail,
            threshold=(
                "model card (EN/PT-BR) and technical report present with mandatory disclosure"
            ),
        )
    )

    decision = make_decision(experiment_id, gates)
    write_decision(decision, repo_root=repo_root)
    record_transition(
        model_id,
        decision.decision,
        evidence_ref=f"reports/model_validation/evidence/{experiment_id}.json",
        gate_summary=decision.reason,
        repo_root=repo_root,
    )

    out_dir = repo_root / VALIDATION_TABLES_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([c.to_dict() for c in recomputation.discrimination_comparisons]).to_csv(
        out_dir / f"{experiment_id}__recomputed_discrimination.csv", index=False
    )
    pd.DataFrame([c.to_dict() for c in recomputation.calibration_comparisons]).to_csv(
        out_dir / f"{experiment_id}__recomputed_calibration.csv", index=False
    )
    pd.DataFrame([c.to_dict() for c in recomputation.operating_point_comparisons]).to_csv(
        out_dir / f"{experiment_id}__recomputed_operating_points.csv", index=False
    )
    (out_dir / f"{experiment_id}__permutation_test.json").write_text(
        json.dumps(permutation_report.to_dict(), indent=2), encoding="utf-8"
    )
    pd.DataFrame([row.to_dict() for row in collinearity.vif_table]).to_csv(
        out_dir / f"{experiment_id}__vif.csv", index=False
    )
    pd.DataFrame([p.to_dict() for p in collinearity.high_correlation_pairs_list]).to_csv(
        out_dir / f"{experiment_id}__high_correlation_pairs.csv", index=False
    )
    pd.DataFrame([c.to_dict() for c in coefficient_classifications]).to_csv(
        out_dir / f"{experiment_id}__coefficient_classification.csv", index=False
    )
    pd.DataFrame([m.to_dict() for m in subgroup_validation.metrics]).to_csv(
        out_dir / f"{experiment_id}__subgroup_validation.csv", index=False
    )
    pd.DataFrame([g.to_dict() for g in subgroup_validation.gap_reports]).to_csv(
        out_dir / f"{experiment_id}__subgroup_gaps.csv", index=False
    )
    pd.DataFrame([c.to_dict() for c in robustness_comparisons]).to_csv(
        out_dir / f"{experiment_id}__robustness_spot_check.csv", index=False
    )
    ece_sensitivity = ece_bin_sensitivity(
        y_test, pd.Series(p_test_main.to_numpy(), index=y_test.index)
    )
    pd.DataFrame([r.to_dict() for r in ece_sensitivity]).to_csv(
        out_dir / f"{experiment_id}__ece_bin_sensitivity.csv", index=False
    )

    return IndependentValidationResult(
        experiment_id=experiment_id,
        model_id=model_id,
        evidence=evidence,
        decision=decision,
        n_permutations=n_permutations,
    )


_STRICT_PROBE_CASES: list[tuple[str, str]] = [
    ("missing_required_column", "drop_X6"),
    ("unexpected_extra_column", "add_bogus"),
    ("domain_violation", "delinquency_15"),
    ("non_finite_value", "inject_nan"),
    ("range_violation", "impossible_bill"),
    ("duplicate_id", "dup_id"),
]


def _run_input_contract_self_test(sample: pd.DataFrame) -> bool:
    from credlens.modeling.input_contract import InputContractError

    for kind, _ in _STRICT_PROBE_CASES:
        probe = sample.copy()
        if kind == "missing_required_column":
            probe = probe.drop(columns=["X6"])
        elif kind == "unexpected_extra_column":
            probe["BOGUS_COLUMN"] = 1
        elif kind == "domain_violation":
            probe.loc[probe.index[0], "X6"] = 15
        elif kind == "non_finite_value":
            probe.loc[probe.index[0], "X12"] = float("nan")
        elif kind == "range_violation":
            probe.loc[probe.index[0], "X12"] = 1e12
        elif kind == "duplicate_id":
            probe.loc[probe.index[-1], "ID"] = probe.loc[probe.index[0], "ID"]

        if kind in ("missing_required_column", "unexpected_extra_column"):
            try:
                validate_input_contract(probe, "strict")
                return False  # should have raised
            except InputContractError:
                continue
        else:
            report = validate_input_contract(probe, "strict")
            if report.n_quarantined_rows < 1:
                return False
    return True


def _check_reproducibility(evidence: EvidenceManifest, repo_root: Path) -> tuple[bool, str]:
    from credlens.data.checksums import compute_sha256

    prediction_path = (
        repo_root / MODELING_TABLES_DIR / f"{evidence.experiment_id}__predictions_test.csv"
    )
    current_hash = compute_sha256(prediction_path)
    if current_hash.lower() != evidence.prediction_hash.lower():
        return False, (
            f"predictions_test.csv hash changed since evidence freeze "
            f"(frozen={evidence.prediction_hash[:16]}..., current={current_hash[:16]}...)."
        )
    return True, "predictions_test.csv hash matches the frozen evidence manifest."


# --- Reduced logistic regression (Phase 9 section 7.3) ---------------------


def build_reduced_experiment(
    original_experiment_id: str,
    reduced_experiment_id: str,
    *,
    seed: int = 42,
    repo_root: Path | None = None,
) -> Experiment | None:
    """Only creates a new experiment if the collinearity audit's iterative
    VIF elimination actually drops at least one feature - otherwise
    returns `None` (Phase 9 section 7.3: "Se a auditoria justificar").
    Reuses the SAME locked split as `original_experiment_id` - the test
    set is never re-split."""
    repo_root = repo_root or Path.cwd()
    validation_config = load_validation_config(repo_root)
    contract = load_target_contract(repo_root)
    registry = load_feature_registry(repo_root)
    config = load_evaluation_config(repo_root)
    df = load_uci_default_credit(repo_root)

    split_table = load_split_assignment_table(
        repo_root / EXPERIMENTS_DIR / original_experiment_id / "split_assignment.csv"
    )
    assignment = apply_split_assignment_table(df, split_table, id_column=contract.identifier_column)
    features = engineer_features(df)
    target = df[contract.target_column]
    x_train_full = features.loc[assignment.train_index]

    kept_features, steps = iteratively_reduce_by_vif(
        x_train_full, float(validation_config.collinearity["vif_action_threshold"])
    )
    if len(kept_features) == len(FEATURE_COLUMNS):
        return None

    x_train = x_train_full[kept_features]
    y_train = target.loc[assignment.train_index]
    x_val = features.loc[assignment.validation_index, kept_features]
    y_val = target.loc[assignment.validation_index]
    x_test = features.loc[assignment.test_index, kept_features]
    y_test = target.loc[assignment.test_index]

    tuned = tune_logistic_regression(x_train, y_train, config, registry=registry, contract=contract)
    p_val = predict_proba_positive(tuned.fitted, x_val)
    p_test = predict_proba_positive(tuned.fitted, x_test)

    exp_dir = repo_root / EXPERIMENTS_DIR / reduced_experiment_id
    models_dir = exp_dir / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    import joblib

    joblib.dump(tuned.fitted.pipeline, models_dir / "logistic_regression_reduced.joblib")

    stability_seeds = list(config.uncertainty["split_stability"]["seeds"])[:3]
    stability_roc_aucs = []
    for stability_seed in stability_seeds:
        from credlens.modeling.splitting import create_split

        fresh_assignment = create_split(
            df,
            id_column=contract.identifier_column,
            target_column=contract.target_column,
            config=config,
            seed=stability_seed,
        )
        fresh_x_train = features.loc[fresh_assignment.train_index, kept_features]
        fresh_y_train = target.loc[fresh_assignment.train_index]
        fresh_x_test = features.loc[fresh_assignment.test_index, kept_features]
        fresh_y_test = target.loc[fresh_assignment.test_index]
        fresh_fitted = fit_model(
            "logistic_regression",
            fresh_x_train,
            fresh_y_train,
            registry=registry,
            contract=contract,
            seed=stability_seed,
        )
        fresh_p_test = predict_proba_positive(fresh_fitted, fresh_x_test)
        from credlens.modeling.evaluation import roc_auc as _roc_auc

        stability_roc_aucs.append(_roc_auc(fresh_y_test, fresh_p_test))

    experiment = Experiment(
        experiment_id=reduced_experiment_id,
        dataset_id="uci-default-credit",
        dataset_hash=contract.acquired_hash_sha256,
        split_hash="reused_from:" + original_experiment_id,
        target_column=contract.target_column,
        feature_set=kept_features,
        feature_registry_version=registry.registry_version,
        preprocessing="median imputation + standardization (reduced feature set)",
        estimator="logistic_regression (reduced, VIF-audited)",
        hyperparameters=tuned.best_params,
        seed=seed,
        cv_description=(
            f"StratifiedKFold(n_splits={tuned.cv_folds}), scoring=average_precision, train-only"
        ),
        metrics={
            "validation": full_metrics(y_val, p_val),
            "test": full_metrics(y_test, p_test),
            "vif_elimination_steps": steps,
            "split_stability_roc_auc": {
                "seeds": stability_seeds,
                "values": stability_roc_aucs,
                "mean": float(np.mean(stability_roc_aucs)),
                "stdev": float(np.std(stability_roc_aucs, ddof=1))
                if len(stability_roc_aucs) > 1
                else 0.0,
            },
        },
        calibration={
            "selected_method": "none",
            "reason": "Not recalibrated for the reduced model.",
        },
        threshold_policy="Illustrative review-capacity scenario (never profit-optimized)",
        subgroup_audit_summary={},
        robustness_summary={},
        artifact_hash=None,
        dependency_versions=dependency_versions(),
        status="evaluated",
        warnings=[],
    )
    write_experiment(experiment, repo_root / EXPERIMENTS_DIR)
    return experiment


# --- Challenger registration + candidate/challenger comparison (section 8) -


def register_challenger_experiment(
    experiment_id: str, challenger_model_id: str | None = None, *, repo_root: Path | None = None
) -> Any:
    repo_root = repo_root or Path.cwd()
    challenger_model_id = challenger_model_id or f"{experiment_id}_challenger"
    experiment = load_experiment(repo_root / EXPERIMENTS_DIR / f"{experiment_id}.json")

    import joblib

    from credlens.modeling.training import FittedModel

    models_dir = repo_root / EXPERIMENTS_DIR / experiment_id / "models"
    pipeline_path = models_dir / "hist_gradient_boosting.joblib"
    if not pipeline_path.is_file():
        raise ModelValidationError(
            f"No trained HistGradientBoosting artifact at '{pipeline_path}'."
        )
    pipeline = joblib.load(pipeline_path)
    fitted = FittedModel(
        model_kind="hist_gradient_boosting",
        pipeline=pipeline,
        hyperparameters=experiment.hyperparameters,
        seed=experiment.seed,
        n_jobs=1,
        fit_seconds=0.0,
        feature_columns=list(FEATURE_COLUMNS),
    )

    test_metrics = experiment.metrics["test"]["hist_gradient_boosting"]
    manifest = register_challenger(
        fitted,
        model_id=challenger_model_id,
        experiment_id=experiment_id,
        output_dir=repo_root / MODELS_DIR,
        feature_registry_version=experiment.feature_registry_version,
        test_metrics=test_metrics,
        limitations=[
            "Historical public benchmark (UCI, Taiwan, 2005) - not a Brazilian population.",
            "Non-linear ensemble - interpretability limited to permutation importance/partial "
            "dependence, no closed-form coefficients.",
            "Not suitable for real lending decisions.",
        ],
    )
    record_transition(
        challenger_model_id,
        "challenger",
        evidence_ref=f"reports/modeling/models/{challenger_model_id}.manifest.json",
        gate_summary="Registered as challenger per Phase 9 section 8 - never candidate/production.",
        repo_root=repo_root,
    )
    return manifest


def _find_manifest_by_status(status: str, experiment_id: str, repo_root: Path) -> str:
    models_dir = repo_root / MODELS_DIR
    matches: list[str] = []
    for path in sorted(models_dir.glob("*.manifest.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("status") == status and raw.get("experiment_id") == experiment_id:
            matches.append(str(raw["model_id"]))
    if not matches:
        raise ModelValidationError(
            f"No registered model with status='{status}' for experiment_id='{experiment_id}' in "
            f"'{models_dir}'."
        )
    return matches[-1]


def compare_candidates(
    experiment_id: str | None = None, *, repo_root: Path | None = None
) -> pd.DataFrame:
    repo_root = repo_root or Path.cwd()
    if experiment_id is None:
        experiments = load_experiment
        candidates_dir = repo_root / MODELS_DIR
        experiment_ids = set()
        for path in sorted(candidates_dir.glob("*.manifest.json")):
            raw = json.loads(path.read_text(encoding="utf-8"))
            experiment_ids.add(raw["experiment_id"])
        if len(experiment_ids) != 1:
            raise ModelValidationError(
                "Cannot auto-detect a single experiment_id with both a registered candidate and "
                f"challenger - found {sorted(experiment_ids)}. Pass --experiment-id explicitly."
            )
        experiment_id = next(iter(experiment_ids))
        _ = experiments

    candidate_model_id = _find_manifest_by_status("candidate", experiment_id, repo_root)
    challenger_model_id = _find_manifest_by_status("challenger", experiment_id, repo_root)

    experiment = load_experiment(repo_root / EXPERIMENTS_DIR / f"{experiment_id}.json")
    contract = load_target_contract(repo_root)
    registry = load_feature_registry(repo_root)
    config = load_evaluation_config(repo_root)
    df = load_uci_default_credit(repo_root)
    split_table = load_split_assignment_table(
        repo_root / EXPERIMENTS_DIR / experiment_id / "split_assignment.csv"
    )
    assignment = apply_split_assignment_table(df, split_table, id_column=contract.identifier_column)
    raw_test = df.loc[assignment.test_index]
    y_test = df.loc[assignment.test_index, contract.target_column]

    import joblib

    from credlens.modeling.training import FittedModel

    models_dir = repo_root / EXPERIMENTS_DIR / experiment_id / "models"
    candidate_fitted = FittedModel(
        model_kind="logistic_regression",
        pipeline=joblib.load(models_dir / "logistic_regression.joblib"),
        hyperparameters=experiment.hyperparameters,
        seed=experiment.seed,
        n_jobs=1,
        fit_seconds=0.0,
        feature_columns=list(FEATURE_COLUMNS),
    )
    challenger_fitted = FittedModel(
        model_kind="hist_gradient_boosting",
        pipeline=joblib.load(models_dir / "hist_gradient_boosting.joblib"),
        hyperparameters=experiment.hyperparameters,
        seed=experiment.seed,
        n_jobs=1,
        fit_seconds=0.0,
        feature_columns=list(FEATURE_COLUMNS),
    )
    threshold_row = pd.read_csv(
        repo_root / MODELING_TABLES_DIR / f"{experiment_id}__thresholds.csv"
    )
    threshold = float(threshold_row[threshold_row["name"] == "top_10_pct"].iloc[0]["threshold"])

    table = build_pareto_comparison(
        df=df,
        raw_test=raw_test,
        y_test=y_test,
        candidate_fitted=candidate_fitted,
        challenger_fitted=challenger_fitted,
        candidate_artifact_path=repo_root / MODELS_DIR / f"{candidate_model_id}.joblib",
        challenger_artifact_path=repo_root / MODELS_DIR / f"{challenger_model_id}.joblib",
        candidate_test_metrics=experiment.metrics["test"]["logistic_regression"],
        challenger_test_metrics=experiment.metrics["test"]["hist_gradient_boosting"],
        candidate_split_stability=experiment.metrics["split_stability"],
        candidate_max_robustness_pr_auc_degradation=max(
            (
                p["pr_auc_degradation"]
                for p in experiment.robustness_summary.get("perturbations", [])
                if not p.get("had_error_or_nan")
            ),
            default=0.0,
        ),
        registry=registry,
        contract=contract,
        config=config,
        threshold=threshold,
    )
    out_dir = repo_root / VALIDATION_TABLES_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    table.to_csv(out_dir / f"{experiment_id}__pareto_comparison.csv", index=False)
    return table


# --- Bilingual validation report (section 23) -------------------------------


def generate_validation_report(
    experiment_id: str, language: str, *, repo_root: Path | None = None
) -> str:
    repo_root = repo_root or Path.cwd()
    decision_path = repo_root / VALIDATION_REPORTS_DIR / "decision.json"
    decision = (
        json.loads(decision_path.read_text(encoding="utf-8")) if decision_path.is_file() else None
    )
    gate_lines = "\n".join(
        f"| {g['name']} | {g['status']} | {g['severity']} | {g['result']} | {g['justification']} |"
        for g in (decision["gates"] if decision else [])
    )
    decision_line = decision["decision"] if decision else "not_yet_run"
    reason_line = (
        decision["reason"] if decision else "credlens model validate-independent has not run yet."
    )

    if language == "pt-BR":
        return f"""# Relatório de Validação Independente (Fase 9)

## 1. Escopo e independência
Este relatório é produzido por `credlens.model_validation`, um pacote separado de
`credlens.modeling` (Fase 8). Toda métrica aqui é recomputada com uma implementação
independente a partir de evidência CONGELADA (`reports/model_validation/evidence/`), nunca
copiada do relatório original da Fase 8.

## 2. Experimento auditado
`{experiment_id}`

## 3. Gates de validação (14)
| Gate | Status | Severidade | Resultado | Justificativa |
|---|---|---|---|---|
{gate_lines}

## 4. Decisão final
**{decision_line}**

{reason_line}

## 5. Limitações
Benchmark público histórico (UCI, Taiwan, 2005). Esta validação independente não constitui
certificação de fairness, avaliação de conformidade legal, nem aprovação para uso em decisões
reais de crédito. **Não é adequado para decisões reais de concessão de crédito.**
"""

    return f"""# Independent Validation Report (Phase 9)

## 1. Scope and independence
This report is produced by `credlens.model_validation`, a package separate from
`credlens.modeling` (Phase 8). Every metric here is recomputed with an independent
implementation from FROZEN evidence (`reports/model_validation/evidence/`), never copied from
the original Phase 8 report.

## 2. Audited experiment
`{experiment_id}`

## 3. Validation gates (14)
| Gate | Status | Severity | Result | Justification |
|---|---|---|---|---|
{gate_lines}

## 4. Final decision
**{decision_line}**

{reason_line}

## 5. Limitations
Historical public benchmark (UCI, Taiwan, 2005). This independent validation is not a fairness
certification, not a legal compliance assessment, and not an approval for use in real lending
decisions. **Not suitable for real lending decisions.**
"""


def write_validation_reports(
    experiment_id: str, *, repo_root: Path | None = None
) -> dict[str, Path]:
    repo_root = repo_root or Path.cwd()
    out_dir = repo_root / VALIDATION_REPORTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    for filename, content in (
        (
            "validation_report.md",
            generate_validation_report(experiment_id, "en", repo_root=repo_root),
        ),
        (
            "validation_report.pt-BR.md",
            generate_validation_report(experiment_id, "pt-BR", repo_root=repo_root),
        ),
    ):
        path = out_dir / filename
        path.write_text(content, encoding="utf-8")
        written[filename] = path
    return written


# --- Figures (a handful, not the full Phase 8 set - section 20's tree lists ---
# figures/ but does not mandate a count for this diagnostic layer)


def generate_validation_figures(experiment_id: str, *, repo_root: Path | None = None) -> list[Path]:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise ModelValidationError(
            "Figure generation needs matplotlib - install with "
            "'uv sync --extra analysis --extra modeling'."
        ) from exc

    repo_root = repo_root or Path.cwd()
    figures_dir = repo_root / "reports" / "model_validation" / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    tables_dir = repo_root / VALIDATION_TABLES_DIR
    paths: list[Path] = []

    def _save(fig: Any, name: str) -> None:
        fig.text(
            0.5,
            0.01,
            "Independent validation - historical public benchmark",
            ha="center",
            fontsize=7,
            color="dimgray",
        )
        path = figures_dir / f"{experiment_id}__{name}.png"
        fig.savefig(path, dpi=110, bbox_inches="tight")
        plt.close(fig)
        paths.append(path)

    vif_path = tables_dir / f"{experiment_id}__vif.csv"
    if vif_path.is_file():
        vif = pd.read_csv(vif_path).head(10).iloc[::-1]
        fig, ax = plt.subplots(figsize=(6, 5))
        ax.barh(vif["feature"], vif["vif"].fillna(0), color="#8b1a1a")
        ax.set_xlabel("Variance Inflation Factor")
        ax.set_title("Multicollinearity audit - VIF (top 10)")
        _save(fig, "01_vif")

    perm_path = tables_dir / f"{experiment_id}__permutation_test.json"
    if perm_path.is_file():
        perm = json.loads(perm_path.read_text(encoding="utf-8"))
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.hist(perm["roc_auc_distribution"], bins=20, color="#1f5fa8")
        ax.axvline(
            perm["real_model_validation_roc_auc"],
            color="#8b1a1a",
            linestyle="--",
            label="Real model",
        )
        ax.axvline(0.5, color="gray", linestyle=":", label="Random (0.5)")
        ax.set_xlabel("Validation ROC-AUC under permuted target")
        ax.set_title(f"Permutation null distribution (n={perm['n_permutations']})")
        ax.legend()
        _save(fig, "02_permutation_null_distribution")

    gaps_path = tables_dir / f"{experiment_id}__subgroup_gaps.csv"
    if gaps_path.is_file():
        gaps = pd.read_csv(gaps_path)
        if not gaps.empty:
            fig, ax = plt.subplots(figsize=(7, 4))
            labels = [f"{r.attribute}/{r.metric}" for r in gaps.itertuples()]
            ax.barh(labels, gaps["absolute_gap"].fillna(0), color="#e6842e")
            ax.set_xlabel("absolute_gap = max - min (reportable groups only)")
            ax.set_title("Corrected subgroup gaps (never fairness certification)")
            _save(fig, "03_subgroup_gaps")

    pareto_path = tables_dir / f"{experiment_id}__pareto_comparison.csv"
    if pareto_path.is_file():
        pareto = pd.read_csv(pareto_path)
        fig, ax = plt.subplots(figsize=(6, 4))
        width = 0.35
        x = np.arange(len(pareto))
        ax.bar(x - width / 2, pareto["pr_auc"], width, label="PR-AUC", color="#1f5fa8")
        ax.bar(x + width / 2, pareto["roc_auc"], width, label="ROC-AUC", color="#e6842e")
        ax.set_xticks(x, pareto["model"], rotation=15, ha="right")
        ax.set_title("Candidate/challenger Pareto comparison")
        ax.legend()
        _save(fig, "04_pareto_comparison")

    return paths
