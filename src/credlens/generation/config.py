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


class MacroShockConfig(BaseModel):
    """A documented, dated, synthetic payment-behavior shock for the
    macroeconomic_stress scenario (Phase 4B). Applied from `shock_date`
    (inclusive) onward: origination and payment behavior before that date
    are byte-identical to baseline - see
    credlens.generation.payments._effective_payment_behavior and
    docs/counterfactual_scenarios.md."""

    model_config = ConfigDict(extra="forbid")

    shock_date: date
    on_time_probability_multiplier: float
    partial_payment_probability_multiplier: float
    prepayment_probability_multiplier: float
    cure_probability_multiplier: float
    synthetic_source_id: str
    synthetic_shock_value: float
    synthetic_shock_description: str


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
    macro_shock: MacroShockConfig | None = None

    @model_validator(mode="after")
    def _scenario_must_be_executable(self) -> GenerationConfig:
        if self.scenario not in EXECUTABLE_SCENARIOS:
            raise ValueError(
                f"GenerationConfig only supports executable scenarios {EXECUTABLE_SCENARIOS}, "
                f"got '{self.scenario}'. Every other scenario remains requires_calibration - see "
                f"config/synthetic/scenarios/{self.scenario}.blueprint.yaml."
            )
        return self


# Every scenario with a concrete, executable config/synthetic/<scenario>.generation.yaml
# file (Phase 4B). Every OTHER scenario blueprint remains requires_calibration - no
# generation config exists for it and generate_scenario() rejects it up front. Order
# matches this phase's own presentation order, not any priority ranking.
EXECUTABLE_SCENARIOS: tuple[str, ...] = (
    "baseline",
    "policy_expansion",
    "policy_tightening",
    "macroeconomic_stress",
    "collections_change",
    "contract_coverage",
)

# CRN (common random numbers, Phase 4B section 5): scenarios listed here MUST use a
# population/applications/features/fairness/truth layer that is BYTE-IDENTICAL to
# baseline's for the same seed - enforced by assert_crn_compatible() at generation
# time. contract_coverage is deliberately excluded: it is its own small, extreme-value
# fixture, never compared to baseline as a population (see its own generation.yaml).
CRN_SCENARIOS: tuple[str, ...] = (
    "policy_expansion",
    "policy_tightening",
    "macroeconomic_stress",
    "collections_change",
)

# Fields that determine the customers/applications/application_features/
# fairness_attributes/truth layer output for a given seed - a CRN scenario's config
# must match baseline's exactly on every one of these fields (policy/payment_behavior/
# collections/write_off/recovery/macro_shock are deliberately excluded: those are
# exactly the fields a counterfactual scenario is allowed to vary). "scales" compares
# only each preset's `customers` count, not its free-text `description` - the wording
# is allowed to differ (e.g. explaining a scenario's own CRN relationship to baseline)
# without that counting as a CRN-breaking difference.
_CRN_FIELDS: tuple[str, ...] = ("period", "population", "applications", "default_seed")


class CrnIncompatibleError(ConfigError):
    """Raised when a CRN scenario's config differs from baseline's on a
    population/applications-affecting field, which would break the common-random-
    numbers guarantee section 5 requires."""


def assert_crn_compatible(
    baseline_config: GenerationConfig, scenario_config: GenerationConfig
) -> None:
    baseline_payload = baseline_config.model_dump(mode="json")
    scenario_payload = scenario_config.model_dump(mode="json")
    mismatches = [
        field for field in _CRN_FIELDS if baseline_payload[field] != scenario_payload[field]
    ]
    baseline_customers = {
        scale.value: preset.customers for scale, preset in baseline_config.scales.items()
    }
    scenario_customers = {
        scale.value: preset.customers for scale, preset in scenario_config.scales.items()
    }
    if baseline_customers != scenario_customers:
        mismatches.append("scales.customers")
    if mismatches:
        raise CrnIncompatibleError(
            f"'{scenario_config.scenario}' config differs from baseline on "
            f"CRN-relevant field(s) {mismatches} - common random numbers requires "
            "identical population/applications config, see docs/common_random_numbers.md."
        )


def config_path_for_scenario(scenario: str) -> Path:
    if scenario == "baseline":
        return DEFAULT_CONFIG_PATH
    return Path(f"config/synthetic/{scenario}.generation.yaml")


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


def with_output_dirs(
    config: GenerationConfig, *, operational_dir: Path, truth_dir: Path
) -> GenerationConfig:
    """Returns a copy of `config` with its output roots overridden - the
    injection point tests use (Phase 6 gate B) to write generated data
    under an isolated `tmp_path` instead of the shared `data/synthetic/`
    and `data/synthetic_truth/` roots that official runs/demos/analytical
    builds also use. Since `operational_dir`/`truth_dir` are part of
    `canonical_config_hash`'s own payload (config.model_dump includes
    every field), overriding them also changes `config_hash` and
    therefore `generation_run_id` - so an isolated-root run is never
    merely written to a different place, it is a genuinely different,
    non-colliding run identity even for an otherwise-identical
    (scenario, scale, seed) triple. Never mutates the input config
    (pydantic models here are immutable-by-convention; this returns a
    new instance)."""
    return config.model_copy(
        update={
            "output": config.output.model_copy(
                update={
                    "operational_dir": str(operational_dir),
                    "truth_dir": str(truth_dir),
                }
            )
        }
    )
