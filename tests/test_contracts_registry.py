"""Tests for credlens.contracts.registry: loading all contracts and
cross-validating their references."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from credlens.contracts.financial_rules import RULES as FINANCIAL_RULES
from credlens.contracts.registry import (
    KNOWN_BUSINESS_RULE_CODES,
    RegistryError,
    get_contract,
    load_all_contracts,
)
from credlens.contracts.relational_rules import RULES as RELATIONAL_RULES
from credlens.contracts.temporal_rules import RULES as TEMPORAL_RULES

REAL_RAW_DIR = Path("contracts/raw")
REAL_OPERATIONAL_DIR = Path("contracts/operational")


def test_load_all_contracts_loads_every_real_file() -> None:
    contracts = load_all_contracts(REAL_RAW_DIR, REAL_OPERATIONAL_DIR)

    assert len(contracts) == 20  # 4 raw + 16 operational
    assert "applications" in contracts
    assert "uci_default_credit" in contracts


def test_load_all_contracts_missing_directories_returns_empty(tmp_path: Path) -> None:
    contracts = load_all_contracts(tmp_path / "raw", tmp_path / "operational")
    assert contracts == {}


def test_load_all_contracts_duplicate_name_raises(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    payload = {
        "name": "dup",
        "version": 1,
        "description": "x",
        "owner": "x",
        "classification": "synthetic_operational",
        "grain": "x",
        "status": "draft",
        "evolution_policy": "x",
        "format": "csv",
        "primary_key": ["id"],
        "columns": [
            {
                "name": "id",
                "type": "string",
                "nullable": False,
                "sensitivity": "synthetic_operational",
                "available_for_modeling": False,
                "description": "x",
            }
        ],
    }
    (raw_dir / "a.yaml").write_text(yaml.safe_dump(payload), encoding="utf-8")
    (raw_dir / "b.yaml").write_text(yaml.safe_dump(payload), encoding="utf-8")

    with pytest.raises(RegistryError, match="Duplicate contract name"):
        load_all_contracts(raw_dir, tmp_path / "operational")


def test_load_all_contracts_wraps_contract_error_as_registry_error(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / "broken.yaml").write_text("name: [unclosed", encoding="utf-8")

    with pytest.raises(RegistryError):
        load_all_contracts(raw_dir, tmp_path / "operational")


def test_validate_cross_references_unknown_fk_contract_raises(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    payload = {
        "name": "with_bad_fk",
        "version": 1,
        "description": "x",
        "owner": "x",
        "classification": "synthetic_operational",
        "grain": "x",
        "status": "draft",
        "evolution_policy": "x",
        "format": "csv",
        "primary_key": ["id"],
        "foreign_keys": [
            {"column": "id", "references_contract": "nonexistent", "references_column": "id"}
        ],
        "columns": [
            {
                "name": "id",
                "type": "string",
                "nullable": False,
                "sensitivity": "synthetic_operational",
                "available_for_modeling": False,
                "description": "x",
            }
        ],
    }
    (raw_dir / "a.yaml").write_text(yaml.safe_dump(payload), encoding="utf-8")

    with pytest.raises(RegistryError, match="unknown contract"):
        load_all_contracts(raw_dir, tmp_path / "operational")


def test_validate_cross_references_unknown_fk_column_raises(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    referenced = {
        "name": "referenced",
        "version": 1,
        "description": "x",
        "owner": "x",
        "classification": "synthetic_operational",
        "grain": "x",
        "status": "draft",
        "evolution_policy": "x",
        "format": "csv",
        "primary_key": ["id"],
        "columns": [
            {
                "name": "id",
                "type": "string",
                "nullable": False,
                "sensitivity": "synthetic_operational",
                "available_for_modeling": False,
                "description": "x",
            }
        ],
    }
    referencer = {
        "name": "referencer",
        "version": 1,
        "description": "x",
        "owner": "x",
        "classification": "synthetic_operational",
        "grain": "x",
        "status": "draft",
        "evolution_policy": "x",
        "format": "csv",
        "primary_key": ["ref_id"],
        "foreign_keys": [
            {
                "column": "ref_id",
                "references_contract": "referenced",
                "references_column": "missing_column",
            }
        ],
        "columns": [
            {
                "name": "ref_id",
                "type": "string",
                "nullable": False,
                "sensitivity": "synthetic_operational",
                "available_for_modeling": False,
                "description": "x",
            }
        ],
    }
    (raw_dir / "referenced.yaml").write_text(yaml.safe_dump(referenced), encoding="utf-8")
    (raw_dir / "referencer.yaml").write_text(yaml.safe_dump(referencer), encoding="utf-8")

    with pytest.raises(RegistryError, match="unknown column"):
        load_all_contracts(raw_dir, tmp_path / "operational")


def test_validate_cross_references_unimplemented_rule_code_raises(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    payload = {
        "name": "with_bad_rule",
        "version": 1,
        "description": "x",
        "owner": "x",
        "classification": "synthetic_operational",
        "grain": "x",
        "status": "draft",
        "evolution_policy": "x",
        "format": "csv",
        "primary_key": ["id"],
        "business_rules": [{"code": "not_a_real_rule", "description": "x"}],
        "columns": [
            {
                "name": "id",
                "type": "string",
                "nullable": False,
                "sensitivity": "synthetic_operational",
                "available_for_modeling": False,
                "description": "x",
            }
        ],
    }
    (raw_dir / "a.yaml").write_text(yaml.safe_dump(payload), encoding="utf-8")

    with pytest.raises(RegistryError, match="unimplemented rule code"):
        load_all_contracts(raw_dir, tmp_path / "operational")


def test_get_contract_returns_known_contract() -> None:
    contracts = load_all_contracts(REAL_RAW_DIR, REAL_OPERATIONAL_DIR)
    contract = get_contract(contracts, "applications")
    assert contract.name == "applications"


def test_get_contract_unknown_name_raises() -> None:
    contracts = load_all_contracts(REAL_RAW_DIR, REAL_OPERATIONAL_DIR)
    with pytest.raises(RegistryError, match="Unknown contract"):
        get_contract(contracts, "does_not_exist")


def test_known_business_rule_codes_is_union_of_all_rule_modules() -> None:
    assert KNOWN_BUSINESS_RULE_CODES == {
        **RELATIONAL_RULES,
        **TEMPORAL_RULES,
        **FINANCIAL_RULES,
    }
    assert len(KNOWN_BUSINESS_RULE_CODES) == 22


def test_every_real_contracts_business_rule_code_is_known() -> None:
    contracts = load_all_contracts(REAL_RAW_DIR, REAL_OPERATIONAL_DIR)
    for contract in contracts.values():
        for rule in contract.business_rules:
            assert rule.code in KNOWN_BUSINESS_RULE_CODES
