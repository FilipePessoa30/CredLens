"""Tests for credlens.contracts.models: the Pydantic contract-metadata schema.

These tests validate the *schema* (small-N YAML structure), never table
data - see docs/adr/0006-audit-vs-strict-validation.md for why that split
exists.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from credlens.contracts.models import (
    Classification,
    ColumnSpec,
    ColumnType,
    ContractStatus,
    DataContract,
    DomainSpec,
    ForeignKeySpec,
    Severity,
    UniquenessRule,
)


def _column(name: str, **overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "name": name,
        "type": "string",
        "nullable": False,
        "domain": None,
        "unit": None,
        "temporality": None,
        "sensitivity": "synthetic_operational",
        "available_for_modeling": False,
        "description": "A column.",
    }
    base.update(overrides)
    return base


def _contract(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "name": "fixture_contract",
        "version": 1,
        "description": "A fixture contract.",
        "owner": "Test owner",
        "classification": "synthetic_operational",
        "grain": "one row per fixture",
        "status": "draft",
        "evolution_policy": "Additive only.",
        "format": "csv",
        "primary_key": ["id"],
        "foreign_keys": [],
        "columns": [_column("id")],
        "uniqueness_rules": [],
        "business_rules": [],
    }
    base.update(overrides)
    return base


class TestDomainSpec:
    def test_requires_at_least_one_constraint(self) -> None:
        with pytest.raises(ValidationError, match="at least one"):
            DomainSpec()

    def test_in_set_alone_is_valid(self) -> None:
        domain = DomainSpec(in_set=[1, 2, 3])
        assert domain.in_set == [1, 2, 3]

    def test_min_max_alone_is_valid(self) -> None:
        domain = DomainSpec(min=0, max=10)
        assert domain.min == 0
        assert domain.max == 10

    def test_regex_alone_is_valid(self) -> None:
        domain = DomainSpec(regex=r"^\d+$")
        assert domain.regex == r"^\d+$"

    def test_rejects_unknown_field(self) -> None:
        with pytest.raises(ValidationError):
            DomainSpec.model_validate({"in_set": [1], "eval": "1+1"})


class TestColumnSpec:
    def test_minimal_valid_column(self) -> None:
        column = ColumnSpec.model_validate(_column("amount", type="decimal"))
        assert column.name == "amount"
        assert column.type == ColumnType.DECIMAL

    def test_rejects_unknown_field(self) -> None:
        payload = _column("amount")
        payload["unexpected"] = "nope"
        with pytest.raises(ValidationError):
            ColumnSpec.model_validate(payload)

    def test_rejects_unknown_type(self) -> None:
        with pytest.raises(ValidationError):
            ColumnSpec.model_validate(_column("amount", type="money"))

    def test_rejects_unknown_sensitivity(self) -> None:
        with pytest.raises(ValidationError):
            ColumnSpec.model_validate(_column("amount", sensitivity="top_secret"))


class TestUniquenessRule:
    def test_requires_non_empty_columns(self) -> None:
        with pytest.raises(ValidationError, match="at least one column"):
            UniquenessRule.model_validate({"name": "no_columns", "columns": []})

    def test_defaults_severity_to_error(self) -> None:
        rule = UniquenessRule.model_validate({"name": "r", "columns": ["a"]})
        assert rule.severity == Severity.ERROR


class TestForeignKeySpec:
    def test_defaults_severity_to_error(self) -> None:
        fk = ForeignKeySpec.model_validate(
            {
                "column": "customer_id",
                "references_contract": "customers",
                "references_column": "customer_id",
            }
        )
        assert fk.severity == Severity.ERROR


class TestDataContract:
    def test_minimal_valid_contract_loads(self) -> None:
        contract = DataContract.model_validate(_contract())
        assert contract.name == "fixture_contract"
        assert contract.classification == Classification.SYNTHETIC_OPERATIONAL
        assert contract.status == ContractStatus.DRAFT
        assert contract.column_names == ["id"]

    def test_column_lookup_by_name(self) -> None:
        contract = DataContract.model_validate(_contract())
        assert contract.column("id").name == "id"

    def test_column_lookup_missing_raises_keyerror(self) -> None:
        contract = DataContract.model_validate(_contract())
        with pytest.raises(KeyError):
            contract.column("does_not_exist")

    def test_primary_key_must_reference_declared_column(self) -> None:
        with pytest.raises(ValidationError, match="primary_key references undeclared"):
            DataContract.model_validate(_contract(primary_key=["missing_column"]))

    def test_uniqueness_rule_must_reference_declared_columns(self) -> None:
        payload = _contract(uniqueness_rules=[{"name": "dup_check", "columns": ["missing_column"]}])
        with pytest.raises(ValidationError, match="uniqueness_rules"):
            DataContract.model_validate(payload)

    def test_foreign_key_must_reference_declared_column(self) -> None:
        payload = _contract(
            foreign_keys=[
                {
                    "column": "missing_column",
                    "references_contract": "other",
                    "references_column": "id",
                }
            ]
        )
        with pytest.raises(ValidationError, match="foreign_keys reference undeclared"):
            DataContract.model_validate(payload)

    def test_rejects_unknown_top_level_field(self) -> None:
        payload = _contract()
        payload["unexpected_field"] = True
        with pytest.raises(ValidationError):
            DataContract.model_validate(payload)

    def test_strict_unexpected_columns_defaults_false(self) -> None:
        contract = DataContract.model_validate(_contract())
        assert contract.strict_unexpected_columns is False
