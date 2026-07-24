"""End-to-end tests over tests/fixtures/contracts/: the valid scenario
must pass every operational contract with zero findings in strict mode,
and each purpose-built invalid scenario must fail strict-mode validation
with exactly the finding code it was designed to trigger.

These fixtures are small, clearly artificial CSVs (see
tests/fixtures/contracts/README.md-equivalent docstrings in each
scenario) - never real business data, never placed under data/raw/.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from credlens.contracts.registry import get_contract, load_all_contracts
from credlens.contracts.validators import validate

FIXTURES_DIR = Path("tests/fixtures/contracts")
CONTRACTS = load_all_contracts()

VALID_SCENARIO_DIR = FIXTURES_DIR / "valid_minimal_scenario"

# (scenario directory name, contract to validate, expected finding code)
INVALID_SCENARIOS = [
    ("invalid_pk_duplicate", "applications", "PK_DUPLICATE"),
    ("invalid_fk_orphan", "applications", "FK_ORPHAN"),
    ("invalid_domain", "applications", "DOMAIN_VIOLATION"),
    ("invalid_causally_impossible_date", "credit_decisions", "DECISION_BEFORE_SUBMISSION"),
    (
        "invalid_approval_without_valid_policy",
        "credit_decisions",
        "DECISION_POLICY_NOT_VALID_AT_DECISION_TIME",
    ),
    ("invalid_contract_from_rejection", "contracts", "CONTRACT_WITHOUT_APPROVED_DECISION"),
    ("invalid_payment_allocation_exceeds", "payment_allocations", "ALLOCATION_EXCEEDS_PAYMENT"),
    ("invalid_allocation_cross_contract", "payment_allocations", "ALLOCATION_CROSSES_CONTRACTS"),
    ("invalid_dpd_bucket_mismatch", "account_monthly_snapshots", "DPD_BUCKET_MISMATCH"),
    ("invalid_snapshot_duplicate", "account_monthly_snapshots", "PK_DUPLICATE"),
    ("invalid_recovery_before_writeoff", "recovery_events", "RECOVERY_BEFORE_WRITE_OFF"),
]

# Every operational contract that has a matching file in the valid scenario.
_VALID_SCENARIO_CONTRACT_NAMES = sorted(path.stem for path in VALID_SCENARIO_DIR.glob("*.csv"))


def test_valid_scenario_directory_covers_every_operational_contract() -> None:
    """ "Operational" here means "defined under contracts/operational/" -
    generation_runs (technical_metadata) and fairness_attributes
    (evaluation_only) live there too but aren't classified
    synthetic_operational; the valid fixture still covers all 16 files."""
    operational_dir_names = {p.stem for p in Path("contracts/operational").glob("*.yaml")}
    assert set(_VALID_SCENARIO_CONTRACT_NAMES) == operational_dir_names
    assert len(_VALID_SCENARIO_CONTRACT_NAMES) == 16


@pytest.mark.parametrize("contract_name", _VALID_SCENARIO_CONTRACT_NAMES)
def test_valid_scenario_passes_every_operational_contract_with_zero_findings(
    contract_name: str,
) -> None:
    contract = get_contract(CONTRACTS, contract_name)

    report = validate(contract, VALID_SCENARIO_DIR, mode="strict", all_contracts=CONTRACTS)

    assert report.findings == [], (
        f"{contract_name} produced unexpected findings on the valid fixture: "
        f"{[f.to_dict() for f in report.findings]}"
    )
    assert report.passed is True


@pytest.mark.parametrize(
    "scenario_dir,contract_name,expected_code",
    INVALID_SCENARIOS,
    ids=[s[0] for s in INVALID_SCENARIOS],
)
def test_invalid_scenario_fails_with_expected_code(
    scenario_dir: str, contract_name: str, expected_code: str
) -> None:
    path = FIXTURES_DIR / scenario_dir
    contract = get_contract(CONTRACTS, contract_name)

    report = validate(contract, path, mode="strict", all_contracts=CONTRACTS)

    codes = {f.code for f in report.findings}
    assert expected_code in codes, (
        f"Expected '{expected_code}' among findings for {scenario_dir}, got: {sorted(codes)}"
    )
    assert report.has_errors is True
    assert report.passed is False


def test_every_invalid_scenario_directory_is_covered_by_a_test_case() -> None:
    """Guards against a fixture directory silently going untested."""
    on_disk = {
        p.name for p in FIXTURES_DIR.iterdir() if p.is_dir() and p.name.startswith("invalid_")
    }
    covered = {name for name, _, _ in INVALID_SCENARIOS}
    assert on_disk == covered
