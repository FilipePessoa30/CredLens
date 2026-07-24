"""Tests for credlens.contracts.loader: reading a single contract YAML file."""

from __future__ import annotations

from pathlib import Path

import pytest

from credlens.contracts.loader import ContractError, load_contract


def test_load_contract_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ContractError, match="not found"):
        load_contract(tmp_path / "missing.yaml")


def test_load_contract_invalid_yaml_raises(tmp_path: Path) -> None:
    path = tmp_path / "broken.yaml"
    path.write_text("name: [unclosed", encoding="utf-8")

    with pytest.raises(ContractError, match="not valid YAML"):
        load_contract(path)


def test_load_contract_non_mapping_top_level_raises(tmp_path: Path) -> None:
    path = tmp_path / "list_top_level.yaml"
    path.write_text("- just\n- a\n- list\n", encoding="utf-8")

    with pytest.raises(ContractError, match="top-level mapping"):
        load_contract(path)


def test_load_contract_schema_violation_raises(tmp_path: Path) -> None:
    path = tmp_path / "bad_schema.yaml"
    path.write_text("name: fixture\nversion: 1\n", encoding="utf-8")

    with pytest.raises(ContractError, match="failed schema validation"):
        load_contract(path)


def test_load_contract_real_applications_contract() -> None:
    contract = load_contract(Path("contracts/operational/applications.yaml"))

    assert contract.name == "applications"
    assert contract.primary_key == ["application_id"]
    assert "customer_id" in contract.column_names


def test_load_contract_real_uci_default_credit_contract() -> None:
    contract = load_contract(Path("contracts/raw/uci_default_credit.yaml"))

    assert contract.name == "uci_default_credit"
    assert len(contract.columns) == 25
    education = contract.column("X3")
    assert education.domain is not None
    assert education.domain.in_set == [1, 2, 3, 4]


def test_load_contract_all_raw_and_operational_files_load_individually() -> None:
    """Every real contract file in the repo must load on its own, independent
    of registry.py's cross-reference validation (tested separately)."""
    for directory in (Path("contracts/raw"), Path("contracts/operational")):
        for path in sorted(directory.glob("*.yaml")):
            contract = load_contract(path)
            assert contract.name
