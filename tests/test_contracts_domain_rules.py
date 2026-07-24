"""Tests for credlens.contracts.domain_rules: generic, schema-driven checks.

Each check is exercised with small, hand-built DataFrames and DataContract
objects constructed directly (not loaded from YAML) so each test isolates
exactly one behavior.
"""

from __future__ import annotations

import pandas as pd

from credlens.contracts import domain_rules
from credlens.contracts.models import ColumnSpec, DataContract, ForeignKeySpec, UniquenessRule


def _column(name: str, **overrides: object) -> ColumnSpec:
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
    return ColumnSpec.model_validate(base)


def _contract(
    name: str = "fixture",
    columns: list[ColumnSpec] | None = None,
    primary_key: list[str] | None = None,
    uniqueness_rules: list[UniquenessRule] | None = None,
    foreign_keys: list[ForeignKeySpec] | None = None,
    strict_unexpected_columns: bool = False,
) -> DataContract:
    cols = columns if columns is not None else [_column("id")]
    return DataContract(
        name=name,
        version=1,
        description="x",
        owner="x",
        classification="synthetic_operational",  # type: ignore[arg-type]
        grain="x",
        status="draft",  # type: ignore[arg-type]
        evolution_policy="x",
        format="csv",
        primary_key=primary_key if primary_key is not None else ["id"],
        foreign_keys=foreign_keys or [],
        columns=cols,
        uniqueness_rules=uniqueness_rules or [],
        business_rules=[],
        strict_unexpected_columns=strict_unexpected_columns,
    )


class TestRequiredAndUnexpectedColumns:
    def test_missing_required_column_is_error(self) -> None:
        contract = _contract(columns=[_column("id"), _column("name")])
        df = pd.DataFrame({"id": ["a"]})

        findings = domain_rules.check_required_and_unexpected_columns(df, contract, mode="audit")

        assert len(findings) == 1
        assert findings[0].code == "MISSING_COLUMN"
        assert findings[0].column == "name"
        assert findings[0].severity == "error"

    def test_unexpected_column_is_warning_in_audit_mode(self) -> None:
        contract = _contract(columns=[_column("id")])
        df = pd.DataFrame({"id": ["a"], "surprise": [1]})

        findings = domain_rules.check_required_and_unexpected_columns(df, contract, mode="audit")

        assert len(findings) == 1
        assert findings[0].code == "UNEXPECTED_COLUMN"
        assert findings[0].severity == "warning"

    def test_unexpected_column_is_error_in_strict_mode(self) -> None:
        contract = _contract(columns=[_column("id")])
        df = pd.DataFrame({"id": ["a"], "surprise": [1]})

        findings = domain_rules.check_required_and_unexpected_columns(df, contract, mode="strict")

        assert findings[0].severity == "error"

    def test_unexpected_column_is_error_when_contract_marks_strict_unexpected_columns(self) -> None:
        contract = _contract(columns=[_column("id")], strict_unexpected_columns=True)
        df = pd.DataFrame({"id": ["a"], "surprise": [1]})

        findings = domain_rules.check_required_and_unexpected_columns(df, contract, mode="audit")

        assert findings[0].severity == "error"

    def test_matching_columns_produce_no_findings(self) -> None:
        contract = _contract(columns=[_column("id")])
        df = pd.DataFrame({"id": ["a", "b"]})

        findings = domain_rules.check_required_and_unexpected_columns(df, contract, mode="strict")

        assert findings == []


class TestNullability:
    def test_null_in_non_nullable_column_is_error(self) -> None:
        contract = _contract(columns=[_column("id", nullable=False)])
        df = pd.DataFrame({"id": ["a", None, "c"]})

        findings = domain_rules.check_nullability(df, contract)

        assert len(findings) == 1
        assert findings[0].code == "NULL_VIOLATION"
        assert findings[0].count == 1
        assert findings[0].total == 3

    def test_null_in_nullable_column_is_fine(self) -> None:
        contract = _contract(columns=[_column("id", nullable=True)])
        df = pd.DataFrame({"id": ["a", None]})

        findings = domain_rules.check_nullability(df, contract)

        assert findings == []

    def test_column_absent_from_dataframe_is_skipped(self) -> None:
        contract = _contract(
            columns=[_column("id", nullable=False), _column("missing", nullable=False)]
        )
        df = pd.DataFrame({"id": ["a"]})

        findings = domain_rules.check_nullability(df, contract)

        assert findings == []  # MISSING_COLUMN is check_required_and_unexpected_columns' job


class TestDomain:
    def test_in_set_violation(self) -> None:
        contract = _contract(
            columns=[_column("status", domain={"in_set": ["approved", "rejected"]})],
            primary_key=[],
        )
        df = pd.DataFrame({"status": ["approved", "pending", "rejected"]})

        findings = domain_rules.check_domain(df, contract)

        assert len(findings) == 1
        assert findings[0].code == "DOMAIN_VIOLATION"
        assert findings[0].count == 1
        assert "pending" in findings[0].examples

    def test_min_max_violation(self) -> None:
        contract = _contract(
            columns=[_column("age", type="integer", domain={"min": 18, "max": 99})],
            primary_key=[],
        )
        df = pd.DataFrame({"age": [17, 25, 100]})

        findings = domain_rules.check_domain(df, contract)

        assert findings[0].count == 2

    def test_min_max_non_numeric_counts_as_violation(self) -> None:
        contract = _contract(
            columns=[_column("age", type="integer", domain={"min": 0})], primary_key=[]
        )
        df = pd.DataFrame({"age": ["not_a_number"]})

        findings = domain_rules.check_domain(df, contract)

        assert findings[0].count == 1

    def test_regex_violation(self) -> None:
        contract = _contract(
            columns=[_column("code", domain={"regex": r"^\d{3}$"})], primary_key=[]
        )
        df = pd.DataFrame({"code": ["123", "abc", "4567"]})

        findings = domain_rules.check_domain(df, contract)

        assert findings[0].count == 2

    def test_nulls_excluded_from_domain_check(self) -> None:
        contract = _contract(
            columns=[_column("status", domain={"in_set": ["approved"]})], primary_key=[]
        )
        df = pd.DataFrame({"status": ["approved", None]})

        findings = domain_rules.check_domain(df, contract)

        assert findings == []

    def test_no_domain_declared_is_skipped(self) -> None:
        contract = _contract(columns=[_column("status", domain=None)], primary_key=[])
        df = pd.DataFrame({"status": ["anything"]})

        findings = domain_rules.check_domain(df, contract)

        assert findings == []

    def test_real_uci_contract_flags_known_education_and_marriage_violations(self) -> None:
        """The real uci_default_credit contract's X3 (EDUCATION) domain is
        {1,2,3,4} and X4 (MARRIAGE) is {1,2,3} - reproduces the manually
        found Phase 2 violation in miniature."""
        from pathlib import Path

        from credlens.contracts.loader import load_contract

        contract = load_contract(Path("contracts/raw/uci_default_credit.yaml"))
        df = pd.DataFrame({"X3": [1, 2, 0, 5, 6], "X4": [1, 2, 3, 0, 1]})

        findings = domain_rules.check_domain(df, contract)
        by_column = {f.column: f for f in findings}

        assert by_column["X3"].count == 3  # 0, 5, 6
        assert by_column["X4"].count == 1  # 0


class TestPrimaryKey:
    def test_no_primary_key_declared_is_skipped(self) -> None:
        contract = _contract(primary_key=[])
        df = pd.DataFrame({"id": ["a", "a"]})

        findings = domain_rules.check_primary_key(df, contract)

        assert findings == []

    def test_null_primary_key_is_error(self) -> None:
        contract = _contract(columns=[_column("id", nullable=True)])
        df = pd.DataFrame({"id": ["a", None]})

        findings = domain_rules.check_primary_key(df, contract)

        codes = {f.code for f in findings}
        assert "PK_NULL" in codes

    def test_duplicate_primary_key_is_error(self) -> None:
        contract = _contract()
        df = pd.DataFrame({"id": ["a", "a", "b"]})

        findings = domain_rules.check_primary_key(df, contract)

        assert len(findings) == 1
        assert findings[0].code == "PK_DUPLICATE"
        assert findings[0].count == 2

    def test_unique_primary_key_produces_no_findings(self) -> None:
        contract = _contract()
        df = pd.DataFrame({"id": ["a", "b", "c"]})

        findings = domain_rules.check_primary_key(df, contract)

        assert findings == []

    def test_composite_primary_key_duplicate(self) -> None:
        contract = _contract(columns=[_column("a"), _column("b")], primary_key=["a", "b"])
        df = pd.DataFrame({"a": ["x", "x"], "b": ["1", "1"]})

        findings = domain_rules.check_primary_key(df, contract)

        assert findings[0].code == "PK_DUPLICATE"

    def test_primary_key_column_absent_from_dataframe_is_skipped(self) -> None:
        contract = _contract(primary_key=["id"])
        df = pd.DataFrame({"other": ["a"]})

        findings = domain_rules.check_primary_key(df, contract)

        assert findings == []


class TestUniquenessRules:
    def test_duplicate_uniqueness_columns_is_flagged(self) -> None:
        rule = UniquenessRule(name="unique_a_b", columns=["a", "b"])
        contract = _contract(
            columns=[_column("a"), _column("b")], uniqueness_rules=[rule], primary_key=[]
        )
        df = pd.DataFrame({"a": ["x", "x"], "b": ["1", "1"]})

        findings = domain_rules.check_uniqueness_rules(df, contract)

        assert len(findings) == 1
        assert findings[0].code == "UNIQUENESS_VIOLATION"

    def test_uniqueness_rule_respects_declared_severity(self) -> None:
        rule = UniquenessRule(name="unique_a", columns=["a"], severity="warning")  # type: ignore[arg-type]
        contract = _contract(columns=[_column("a")], uniqueness_rules=[rule], primary_key=[])
        df = pd.DataFrame({"a": ["x", "x"]})

        findings = domain_rules.check_uniqueness_rules(df, contract)

        assert findings[0].severity == "warning"

    def test_no_violation_when_unique(self) -> None:
        rule = UniquenessRule(name="unique_a", columns=["a"])
        contract = _contract(columns=[_column("a")], uniqueness_rules=[rule], primary_key=[])
        df = pd.DataFrame({"a": ["x", "y"]})

        findings = domain_rules.check_uniqueness_rules(df, contract)

        assert findings == []


class TestNoDocumentLikeIdentifiers:
    def test_cpf_shaped_value_in_id_column_is_flagged(self) -> None:
        contract = _contract()
        df = pd.DataFrame({"customer_id": ["123.456.789-01", "cust-002"]})

        findings = domain_rules.check_no_document_like_identifiers(df, contract)

        assert len(findings) == 1
        assert findings[0].code == "CPF_LIKE_IDENTIFIER"
        assert findings[0].column == "customer_id"

    def test_cpf_shaped_value_without_punctuation_is_flagged(self) -> None:
        contract = _contract()
        df = pd.DataFrame({"customer_id": ["12345678901"]})

        findings = domain_rules.check_no_document_like_identifiers(df, contract)

        assert findings[0].count == 1

    def test_letter_prefixed_synthetic_ids_are_not_flagged(self) -> None:
        contract = _contract()
        df = pd.DataFrame(
            {"customer_id": ["cust-001", "cust-002"], "application_id": ["app-001", "app-002"]}
        )

        findings = domain_rules.check_no_document_like_identifiers(df, contract)

        assert findings == []

    def test_non_id_columns_are_not_checked(self) -> None:
        contract = _contract()
        df = pd.DataFrame({"note": ["123.456.789-01"]})

        findings = domain_rules.check_no_document_like_identifiers(df, contract)

        assert findings == []


class TestForeignKeys:
    def test_orphan_value_is_flagged(self) -> None:
        fk = ForeignKeySpec(
            column="customer_id", references_contract="customers", references_column="customer_id"
        )
        contract = _contract(
            columns=[_column("customer_id")], foreign_keys=[fk], primary_key=["customer_id"]
        )
        df = pd.DataFrame({"customer_id": ["cust-001", "cust-999"]})
        tables = {"customers": pd.DataFrame({"customer_id": ["cust-001"]})}

        findings = domain_rules.check_foreign_keys(df, contract, tables)

        assert len(findings) == 1
        assert findings[0].code == "FK_ORPHAN"
        assert "cust-999" in findings[0].examples

    def test_all_values_present_produces_no_findings(self) -> None:
        fk = ForeignKeySpec(
            column="customer_id", references_contract="customers", references_column="customer_id"
        )
        contract = _contract(
            columns=[_column("customer_id")], foreign_keys=[fk], primary_key=["customer_id"]
        )
        df = pd.DataFrame({"customer_id": ["cust-001"]})
        tables = {"customers": pd.DataFrame({"customer_id": ["cust-001"]})}

        findings = domain_rules.check_foreign_keys(df, contract, tables)

        assert findings == []

    def test_referenced_table_absent_reports_info_not_error(self) -> None:
        fk = ForeignKeySpec(
            column="customer_id", references_contract="customers", references_column="customer_id"
        )
        contract = _contract(
            columns=[_column("customer_id")], foreign_keys=[fk], primary_key=["customer_id"]
        )
        df = pd.DataFrame({"customer_id": ["cust-001"]})

        findings = domain_rules.check_foreign_keys(df, contract, {})

        assert len(findings) == 1
        assert findings[0].code == "RULE_NOT_EVALUATED"
        assert findings[0].severity == "info"

    def test_fk_column_absent_from_dataframe_is_skipped(self) -> None:
        fk = ForeignKeySpec(
            column="customer_id", references_contract="customers", references_column="customer_id"
        )
        contract = _contract(
            columns=[_column("customer_id")], foreign_keys=[fk], primary_key=["customer_id"]
        )
        df = pd.DataFrame({"other": ["x"]})

        findings = domain_rules.check_foreign_keys(
            df, contract, {"customers": pd.DataFrame({"customer_id": []})}
        )

        assert findings == []

    def test_null_fk_values_are_not_orphans(self) -> None:
        fk = ForeignKeySpec(
            column="policy_version_id",
            references_contract="policies",
            references_column="policy_version_id",
        )
        contract = _contract(
            columns=[_column("policy_version_id", nullable=True)],
            foreign_keys=[fk],
            primary_key=[],
        )
        df = pd.DataFrame({"policy_version_id": [None]})
        tables = {"policies": pd.DataFrame({"policy_version_id": ["pv-001"]})}

        findings = domain_rules.check_foreign_keys(df, contract, tables)

        assert findings == []


class TestCheckAll:
    def test_runs_every_sub_check(self) -> None:
        contract = _contract(columns=[_column("id", nullable=False)])
        df = pd.DataFrame({"id": ["a", "a"]})

        findings = domain_rules.check_all(df, contract, {"fixture": df}, mode="strict")
        codes = {f.code for f in findings}

        assert "PK_DUPLICATE" in codes

    def test_clean_data_produces_no_findings(self) -> None:
        contract = _contract(
            columns=[_column("customer_id", nullable=False)], primary_key=["customer_id"]
        )
        df = pd.DataFrame({"customer_id": ["cust-001", "cust-002"]})

        findings = domain_rules.check_all(df, contract, {"fixture": df}, mode="strict")

        assert findings == []
