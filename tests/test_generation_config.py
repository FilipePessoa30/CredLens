"""Tests for credlens.generation.config: the executable baseline
generation configuration schema."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from credlens.generation.config import ConfigError, Scale, load_generation_config

REAL_CONFIG_PATH = Path("config/synthetic/baseline.generation.yaml")


def _minimal_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "version": 1,
        "scenario": "baseline",
        "default_seed": 1,
        "currency_unit": "credlens_synthetic_unit",
        "period": {"start": "2024-01-01", "end": "2024-12-31"},
        "scales": {"smoke": {"customers": 10, "description": "x"}},
        "population": {
            "declared_income_min": 100,
            "declared_income_max": 1000,
            "employment_months_max": 60,
            "existing_relationship_share": 0.3,
            "bureau_score_bucket_weights": {"thin_file": 0.5, "low": 0.5},
        },
        "applications": {
            "applications_per_customer_max": 1,
            "channel_weights": {"app": 1.0},
            "requested_amount_min": 100,
            "requested_amount_max": 1000,
            "requested_term_months_choices": [12],
            "cancellation_rate": 0.0,
        },
        "policy": {
            "approval_score_cutoff": 0.5,
            "offered_rate": 0.03,
            "approved_term_months_max": 12,
        },
        "booking": {"booking_rate_given_approved": 0.9, "max_days_approval_to_contract": 5},
        "contract": {"max_days_contract_to_disbursement": 2},
        "payment_behavior": {
            "on_time_probability": 0.7,
            "partial_payment_probability": 0.1,
            "prepayment_probability": 0.05,
            "cure_probability_per_month": 0.2,
            "reversal_rate": 0.01,
            "allocation_order": ["fees", "interest", "principal"],
        },
        "collections": {"contact_dpd_thresholds": [15, 45], "promise_to_pay_probability": 0.3},
        "write_off": {"dpd_threshold": 150},
        "recovery": {
            "recovery_probability": 0.25,
            "recovery_fraction_min": 0.05,
            "recovery_fraction_max": 0.4,
            "max_months_after_write_off": 6,
        },
        "tolerance": {"monetary_tolerance": 0.01},
        "output": {
            "format": "parquet",
            "operational_dir": "data/synthetic",
            "truth_dir": "data/synthetic_truth",
        },
    }
    payload.update(overrides)
    return payload


def test_load_real_baseline_config() -> None:
    config = load_generation_config(REAL_CONFIG_PATH)
    assert config.scenario == "baseline"
    assert Scale.SMOKE in config.scales
    assert Scale.SAMPLE in config.scales
    assert Scale.PORTFOLIO in config.scales


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_generation_config(tmp_path / "missing.yaml")


def test_invalid_yaml_raises(tmp_path: Path) -> None:
    path = tmp_path / "broken.yaml"
    path.write_text("version: [unclosed", encoding="utf-8")
    with pytest.raises(ConfigError, match="not valid YAML"):
        load_generation_config(path)


def test_non_baseline_scenario_rejected(tmp_path: Path) -> None:
    path = tmp_path / "cfg.yaml"
    path.write_text(yaml.safe_dump(_minimal_payload(scenario="policy_expansion")), encoding="utf-8")
    with pytest.raises(ConfigError, match="failed schema validation"):
        load_generation_config(path)


def test_period_end_before_start_rejected(tmp_path: Path) -> None:
    path = tmp_path / "cfg.yaml"
    payload = _minimal_payload(period={"start": "2024-12-31", "end": "2024-01-01"})
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    with pytest.raises(ConfigError):
        load_generation_config(path)


def test_bureau_weights_must_sum_to_one(tmp_path: Path) -> None:
    path = tmp_path / "cfg.yaml"
    payload = _minimal_payload()
    payload["population"]["bureau_score_bucket_weights"] = {"thin_file": 0.9, "low": 0.9}  # type: ignore[index]
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    with pytest.raises(ConfigError, match=r"sum to 1\.0"):
        load_generation_config(path)


def test_unknown_top_level_field_rejected(tmp_path: Path) -> None:
    path = tmp_path / "cfg.yaml"
    payload = _minimal_payload()
    payload["unexpected_field"] = True
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    with pytest.raises(ConfigError):
        load_generation_config(path)


def test_valid_minimal_config_loads(tmp_path: Path) -> None:
    path = tmp_path / "cfg.yaml"
    path.write_text(yaml.safe_dump(_minimal_payload()), encoding="utf-8")
    config = load_generation_config(path)
    assert config.default_seed == 1
    assert config.scales[Scale.SMOKE].customers == 10
