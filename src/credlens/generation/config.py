"""Executable baseline generation configuration.

This is deliberately a SEPARATE schema from config/synthetic/scenarios/
baseline.blueprint.yaml (see docs/synthetic_generation_implementation.md
for why): the blueprint is a narrative design document (5 loosely-typed
sections, each parameter self-describing its own status) aimed at a human
reader deciding what the baseline scenario should even contain. This
module is the strongly-typed, validated configuration the generator code
actually reads. Every numeric parameter here is an explicit, documented
SYNTHETIC ASSUMPTION - never presented as calibrated from a real
institution (see docs/assumptions_and_limitations.md).
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, model_validator

DEFAULT_CONFIG_PATH = Path("config/synthetic/baseline.generation.yaml")


class ConfigError(Exception):
    """Raised when the generation configuration cannot be read or is invalid."""


class Scale(StrEnum):
    SMOKE = "smoke"
    SAMPLE = "sample"
    PORTFOLIO = "portfolio"


class ScalePreset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customers: int
    description: str


class PeriodConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: date
    end: date

    @model_validator(mode="after")
    def _end_after_start(self) -> PeriodConfig:
        if self.end <= self.start:
            raise ValueError("period.end must be after period.start")
        return self


class PopulationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    declared_income_min: float
    declared_income_max: float
    employment_months_max: int
    existing_relationship_share: float
    bureau_score_bucket_weights: dict[str, float]

    @model_validator(mode="after")
    def _weights_sum_to_one(self) -> PopulationConfig:
        total = sum(self.bureau_score_bucket_weights.values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"bureau_score_bucket_weights must sum to 1.0, got {total}")
        return self


class ApplicationsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    applications_per_customer_max: int
    channel_weights: dict[str, float]
    requested_amount_min: float
    requested_amount_max: float
    requested_term_months_choices: list[int]
    cancellation_rate: float


class PolicyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval_score_cutoff: float
    offered_rate: float
    approved_term_months_max: int


class BookingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    booking_rate_given_approved: float
    max_days_approval_to_contract: int


class ContractConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_days_contract_to_disbursement: int


class PaymentBehaviorConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    on_time_probability: float
    partial_payment_probability: float
    prepayment_probability: float
    cure_probability_per_month: float
    reversal_rate: float
    allocation_order: list[str]


class CollectionsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contact_dpd_thresholds: list[int]
    promise_to_pay_probability: float


class WriteOffConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dpd_threshold: int


class RecoveryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recovery_probability: float
    recovery_fraction_min: float
    recovery_fraction_max: float
    max_months_after_write_off: int


class ToleranceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    monetary_tolerance: float


class OutputConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: str
    operational_dir: str
    truth_dir: str


class GenerationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int
    scenario: str
    default_seed: int
    currency_unit: str
    period: PeriodConfig
    scales: dict[Scale, ScalePreset]
    population: PopulationConfig
    applications: ApplicationsConfig
    policy: PolicyConfig
    booking: BookingConfig
    contract: ContractConfig
    payment_behavior: PaymentBehaviorConfig
    collections: CollectionsConfig
    write_off: WriteOffConfig
    recovery: RecoveryConfig
    tolerance: ToleranceConfig
    output: OutputConfig

    @model_validator(mode="after")
    def _scenario_must_be_baseline(self) -> GenerationConfig:
        if self.scenario != "baseline":
            raise ValueError(
                f"GenerationConfig only supports scenario='baseline' in Phase 4A, got "
                f"'{self.scenario}'"
            )
        return self


def load_generation_config(path: Path = DEFAULT_CONFIG_PATH) -> GenerationConfig:
    """Load and validate the baseline executable generation configuration.

    Raises:
        ConfigError: missing file, invalid YAML, or a schema violation.
    """
    if not path.is_file():
        raise ConfigError(f"Generation config file not found at '{path}'.")

    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"Could not read generation config file '{path}': {exc}") from exc

    try:
        data = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"Generation config file '{path}' is not valid YAML: {exc}") from exc

    if not isinstance(data, dict):
        raise ConfigError(f"Generation config file '{path}' must contain a top-level mapping.")

    try:
        return GenerationConfig.model_validate(data)
    except Exception as exc:  # pydantic.ValidationError, kept broad for a single clean message
        raise ConfigError(
            f"Generation config file '{path}' failed schema validation:\n{exc}"
        ) from exc
