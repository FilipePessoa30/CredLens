"""Tests for credlens.contracts.relational_rules: relationship/cardinality
business rules. Each rule function takes `(tables, contract_name)` and
needs only the small, hand-built DataFrames a given rule reads."""

from __future__ import annotations

import pandas as pd

from credlens.contracts import relational_rules


class TestSingleFinalDecision:
    def test_two_final_decisions_for_one_application_is_flagged(self) -> None:
        decisions = pd.DataFrame(
            {
                "application_id": ["app-1", "app-1"],
                "decision_id": ["dec-1", "dec-2"],
                "is_final": ["true", "true"],
                "outcome": ["approved", "rejected"],
            }
        )
        findings = relational_rules.single_final_decision(
            {"credit_decisions": decisions}, "credit_decisions"
        )

        assert len(findings) == 1
        assert findings[0].code == "MULTIPLE_FINAL_DECISIONS"
        assert findings[0].count == 1

    def test_one_final_decision_per_application_is_fine(self) -> None:
        decisions = pd.DataFrame(
            {
                "application_id": ["app-1", "app-2"],
                "decision_id": ["dec-1", "dec-2"],
                "is_final": ["true", "true"],
                "outcome": ["approved", "rejected"],
            }
        )
        findings = relational_rules.single_final_decision(
            {"credit_decisions": decisions}, "credit_decisions"
        )

        assert findings == []

    def test_non_final_decisions_do_not_count(self) -> None:
        decisions = pd.DataFrame(
            {
                "application_id": ["app-1", "app-1"],
                "decision_id": ["dec-1", "dec-2"],
                "is_final": ["false", "true"],
                "outcome": ["approved", "approved"],
            }
        )
        findings = relational_rules.single_final_decision(
            {"credit_decisions": decisions}, "credit_decisions"
        )

        assert findings == []

    def test_missing_table_reports_info(self) -> None:
        findings = relational_rules.single_final_decision({}, "credit_decisions")

        assert findings[0].severity == "info"
        assert findings[0].code == "RULE_NOT_EVALUATED"


class TestContractRequiresApprovedFinalDecision:
    def test_contract_without_approved_decision_is_flagged(self) -> None:
        decisions = pd.DataFrame(
            {
                "application_id": ["app-1"],
                "decision_id": ["dec-1"],
                "is_final": ["true"],
                "outcome": ["rejected"],
            }
        )
        contracts_df = pd.DataFrame({"application_id": ["app-1"], "contract_id": ["ctr-1"]})

        findings = relational_rules.contract_requires_approved_final_decision(
            {"credit_decisions": decisions, "contracts": contracts_df}, "contracts"
        )

        assert len(findings) == 1
        assert findings[0].code == "CONTRACT_WITHOUT_APPROVED_DECISION"

    def test_contract_with_approved_decision_is_fine(self) -> None:
        decisions = pd.DataFrame(
            {
                "application_id": ["app-1"],
                "decision_id": ["dec-1"],
                "is_final": ["true"],
                "outcome": ["approved"],
            }
        )
        contracts_df = pd.DataFrame({"application_id": ["app-1"], "contract_id": ["ctr-1"]})

        findings = relational_rules.contract_requires_approved_final_decision(
            {"credit_decisions": decisions, "contracts": contracts_df}, "contracts"
        )

        assert findings == []


class TestApprovalRequiresValidPolicy:
    def test_decision_before_policy_effective_from_is_flagged(self) -> None:
        decisions = pd.DataFrame(
            {
                "decision_id": ["dec-1"],
                "policy_version_id": ["pv-1"],
                "decision_timestamp": ["2024-01-01T00:00:00Z"],
            }
        )
        policies = pd.DataFrame(
            {
                "policy_version_id": ["pv-1"],
                "name": ["policy A"],
                "effective_from": ["2024-06-01T00:00:00Z"],
                "effective_to": [None],
            }
        )
        findings = relational_rules.approval_requires_valid_policy(
            {"credit_decisions": decisions, "policy_versions": policies}, "credit_decisions"
        )

        assert len(findings) == 1
        assert findings[0].code == "DECISION_POLICY_NOT_VALID_AT_DECISION_TIME"

    def test_decision_after_policy_effective_to_is_flagged(self) -> None:
        decisions = pd.DataFrame(
            {
                "decision_id": ["dec-1"],
                "policy_version_id": ["pv-1"],
                "decision_timestamp": ["2024-12-01T00:00:00Z"],
            }
        )
        policies = pd.DataFrame(
            {
                "policy_version_id": ["pv-1"],
                "name": ["policy A"],
                "effective_from": ["2024-01-01T00:00:00Z"],
                "effective_to": ["2024-06-01T00:00:00Z"],
            }
        )
        findings = relational_rules.approval_requires_valid_policy(
            {"credit_decisions": decisions, "policy_versions": policies}, "credit_decisions"
        )

        assert len(findings) == 1

    def test_decision_within_policy_window_is_fine(self) -> None:
        decisions = pd.DataFrame(
            {
                "decision_id": ["dec-1"],
                "policy_version_id": ["pv-1"],
                "decision_timestamp": ["2024-03-01T00:00:00Z"],
            }
        )
        policies = pd.DataFrame(
            {
                "policy_version_id": ["pv-1"],
                "name": ["policy A"],
                "effective_from": ["2024-01-01T00:00:00Z"],
                "effective_to": ["2024-06-01T00:00:00Z"],
            }
        )
        findings = relational_rules.approval_requires_valid_policy(
            {"credit_decisions": decisions, "policy_versions": policies}, "credit_decisions"
        )

        assert findings == []

    def test_unknown_policy_version_id_is_flagged(self) -> None:
        decisions = pd.DataFrame(
            {
                "decision_id": ["dec-1"],
                "policy_version_id": ["pv-missing"],
                "decision_timestamp": ["2024-03-01T00:00:00Z"],
            }
        )
        policies = pd.DataFrame(
            {
                "policy_version_id": ["pv-1"],
                "name": ["policy A"],
                "effective_from": ["2024-01-01T00:00:00Z"],
                "effective_to": [None],
            }
        )
        findings = relational_rules.approval_requires_valid_policy(
            {"credit_decisions": decisions, "policy_versions": policies}, "credit_decisions"
        )

        assert len(findings) == 1


class TestAllocationSameContract:
    def test_allocation_crossing_contracts_is_flagged(self) -> None:
        allocations = pd.DataFrame(
            {
                "allocation_id": ["alloc-1"],
                "payment_id": ["pay-1"],
                "installment_id": ["inst-1"],
                "contract_id": ["ctr-1"],
            }
        )
        payments = pd.DataFrame({"payment_id": ["pay-1"], "contract_id": ["ctr-1"]})
        installments = pd.DataFrame({"installment_id": ["inst-1"], "contract_id": ["ctr-2"]})

        findings = relational_rules.allocation_same_contract(
            {
                "payment_allocations": allocations,
                "payments": payments,
                "installments": installments,
            },
            "payment_allocations",
        )

        assert len(findings) == 1
        assert findings[0].code == "ALLOCATION_CROSSES_CONTRACTS"

    def test_allocation_matching_contracts_is_fine(self) -> None:
        allocations = pd.DataFrame(
            {
                "allocation_id": ["alloc-1"],
                "payment_id": ["pay-1"],
                "installment_id": ["inst-1"],
                "contract_id": ["ctr-1"],
            }
        )
        payments = pd.DataFrame({"payment_id": ["pay-1"], "contract_id": ["ctr-1"]})
        installments = pd.DataFrame({"installment_id": ["inst-1"], "contract_id": ["ctr-1"]})

        findings = relational_rules.allocation_same_contract(
            {
                "payment_allocations": allocations,
                "payments": payments,
                "installments": installments,
            },
            "payment_allocations",
        )

        assert findings == []


class TestPaymentAllocationNotExceedPayment:
    def test_allocations_exceeding_payment_amount_is_flagged(self) -> None:
        allocations = pd.DataFrame({"payment_id": ["pay-1", "pay-1"], "allocated_total": [30, 60]})
        payments = pd.DataFrame({"payment_id": ["pay-1"], "amount": [50]})

        findings = relational_rules.payment_allocation_not_exceed_payment(
            {"payment_allocations": allocations, "payments": payments}, "payment_allocations"
        )

        assert len(findings) == 1
        assert findings[0].code == "ALLOCATION_EXCEEDS_PAYMENT"

    def test_allocations_within_payment_amount_is_fine(self) -> None:
        allocations = pd.DataFrame({"payment_id": ["pay-1"], "allocated_total": [50]})
        payments = pd.DataFrame({"payment_id": ["pay-1"], "amount": [50]})

        findings = relational_rules.payment_allocation_not_exceed_payment(
            {"payment_allocations": allocations, "payments": payments}, "payment_allocations"
        )

        assert findings == []


def test_rules_registry_contains_every_function() -> None:
    assert set(relational_rules.RULES) == {
        "single_final_decision",
        "contract_requires_approved_final_decision",
        "approval_requires_valid_policy",
        "allocation_same_contract",
        "payment_allocation_not_exceed_payment",
        "macro_context_provenance_consistent",
    }
