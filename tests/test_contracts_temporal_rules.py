"""Tests for credlens.contracts.temporal_rules: causal/temporal ordering
business rules."""

from __future__ import annotations

import pandas as pd

from credlens.contracts import temporal_rules


class TestDecisionNotBeforeSubmission:
    def test_decision_before_submission_is_flagged(self) -> None:
        applications = pd.DataFrame(
            {"application_id": ["app-1"], "submitted_at": ["2024-01-10T00:00:00Z"]}
        )
        decisions = pd.DataFrame(
            {
                "decision_id": ["dec-1"],
                "application_id": ["app-1"],
                "decision_timestamp": ["2024-01-05T00:00:00Z"],
            }
        )
        findings = temporal_rules.decision_not_before_submission(
            {"applications": applications, "credit_decisions": decisions}, "credit_decisions"
        )

        assert len(findings) == 1
        assert findings[0].code == "DECISION_BEFORE_SUBMISSION"

    def test_decision_after_submission_is_fine(self) -> None:
        applications = pd.DataFrame(
            {"application_id": ["app-1"], "submitted_at": ["2024-01-01T00:00:00Z"]}
        )
        decisions = pd.DataFrame(
            {
                "decision_id": ["dec-1"],
                "application_id": ["app-1"],
                "decision_timestamp": ["2024-01-05T00:00:00Z"],
            }
        )
        findings = temporal_rules.decision_not_before_submission(
            {"applications": applications, "credit_decisions": decisions}, "credit_decisions"
        )

        assert findings == []


class TestContractAfterDecision:
    def test_contract_before_decision_is_flagged(self) -> None:
        decisions = pd.DataFrame(
            {
                "application_id": ["app-1"],
                "decision_timestamp": ["2024-02-01T00:00:00Z"],
                "is_final": ["true"],
                "outcome": ["approved"],
            }
        )
        contracts_df = pd.DataFrame(
            {
                "application_id": ["app-1"],
                "contract_id": ["ctr-1"],
                "contract_date": ["2024-01-01T00:00:00Z"],
            }
        )
        findings = temporal_rules.contract_after_decision(
            {"credit_decisions": decisions, "contracts": contracts_df}, "contracts"
        )

        assert len(findings) == 1
        assert findings[0].code == "CONTRACT_BEFORE_DECISION"

    def test_contract_after_decision_is_fine(self) -> None:
        decisions = pd.DataFrame(
            {
                "application_id": ["app-1"],
                "decision_timestamp": ["2024-01-01T00:00:00Z"],
                "is_final": ["true"],
                "outcome": ["approved"],
            }
        )
        contracts_df = pd.DataFrame(
            {
                "application_id": ["app-1"],
                "contract_id": ["ctr-1"],
                "contract_date": ["2024-02-01T00:00:00Z"],
            }
        )
        findings = temporal_rules.contract_after_decision(
            {"credit_decisions": decisions, "contracts": contracts_df}, "contracts"
        )

        assert findings == []


class TestDisbursementNotBeforeContract:
    def test_disbursement_before_contract_is_flagged(self) -> None:
        contracts_df = pd.DataFrame(
            {
                "contract_id": ["ctr-1"],
                "contract_date": ["2024-02-01T00:00:00Z"],
                "disbursement_date": ["2024-01-01T00:00:00Z"],
            }
        )
        findings = temporal_rules.disbursement_not_before_contract(
            {"contracts": contracts_df}, "contracts"
        )

        assert len(findings) == 1
        assert findings[0].code == "DISBURSEMENT_BEFORE_CONTRACT"

    def test_disbursement_after_contract_is_fine(self) -> None:
        contracts_df = pd.DataFrame(
            {
                "contract_id": ["ctr-1"],
                "contract_date": ["2024-01-01T00:00:00Z"],
                "disbursement_date": ["2024-01-02T00:00:00Z"],
            }
        )
        findings = temporal_rules.disbursement_not_before_contract(
            {"contracts": contracts_df}, "contracts"
        )

        assert findings == []


class TestWriteOffNotBeforeContract:
    def test_write_off_before_contract_is_flagged(self) -> None:
        contracts_df = pd.DataFrame(
            {"contract_id": ["ctr-1"], "contract_date": ["2024-06-01T00:00:00Z"]}
        )
        write_offs = pd.DataFrame(
            {
                "write_off_id": ["wo-1"],
                "contract_id": ["ctr-1"],
                "write_off_date": ["2024-01-01T00:00:00Z"],
            }
        )
        findings = temporal_rules.write_off_not_before_contract(
            {"contracts": contracts_df, "write_off_events": write_offs}, "write_off_events"
        )

        assert len(findings) == 1
        assert findings[0].code == "WRITE_OFF_BEFORE_CONTRACT"

    def test_write_off_after_contract_is_fine(self) -> None:
        contracts_df = pd.DataFrame(
            {"contract_id": ["ctr-1"], "contract_date": ["2024-01-01T00:00:00Z"]}
        )
        write_offs = pd.DataFrame(
            {
                "write_off_id": ["wo-1"],
                "contract_id": ["ctr-1"],
                "write_off_date": ["2024-06-01T00:00:00Z"],
            }
        )
        findings = temporal_rules.write_off_not_before_contract(
            {"contracts": contracts_df, "write_off_events": write_offs}, "write_off_events"
        )

        assert findings == []


class TestRecoveryAfterWriteOff:
    def test_recovery_before_write_off_is_flagged(self) -> None:
        write_offs = pd.DataFrame(
            {"write_off_id": ["wo-1"], "write_off_date": ["2024-06-15T00:00:00Z"]}
        )
        recoveries = pd.DataFrame(
            {
                "recovery_id": ["rec-1"],
                "write_off_id": ["wo-1"],
                "recovery_date": ["2024-05-01T00:00:00Z"],
            }
        )
        findings = temporal_rules.recovery_after_write_off(
            {"write_off_events": write_offs, "recovery_events": recoveries}, "recovery_events"
        )

        assert len(findings) == 1
        assert findings[0].code == "RECOVERY_BEFORE_WRITE_OFF"

    def test_recovery_referencing_nonexistent_write_off_is_flagged(self) -> None:
        write_offs = pd.DataFrame(
            {"write_off_id": ["wo-1"], "write_off_date": ["2024-06-15T00:00:00Z"]}
        )
        recoveries = pd.DataFrame(
            {
                "recovery_id": ["rec-1"],
                "write_off_id": ["wo-missing"],
                "recovery_date": ["2024-07-01T00:00:00Z"],
            }
        )
        findings = temporal_rules.recovery_after_write_off(
            {"write_off_events": write_offs, "recovery_events": recoveries}, "recovery_events"
        )

        assert len(findings) == 1

    def test_recovery_after_write_off_is_fine(self) -> None:
        write_offs = pd.DataFrame(
            {"write_off_id": ["wo-1"], "write_off_date": ["2024-06-15T00:00:00Z"]}
        )
        recoveries = pd.DataFrame(
            {
                "recovery_id": ["rec-1"],
                "write_off_id": ["wo-1"],
                "recovery_date": ["2024-07-01T00:00:00Z"],
            }
        )
        findings = temporal_rules.recovery_after_write_off(
            {"write_off_events": write_offs, "recovery_events": recoveries}, "recovery_events"
        )

        assert findings == []


class TestReversalReferencesEarlierPayment:
    def test_reversal_not_after_original_is_flagged(self) -> None:
        payments = pd.DataFrame(
            {
                "payment_id": ["pay-1", "pay-2"],
                "payment_timestamp": ["2024-01-10T00:00:00Z", "2024-01-05T00:00:00Z"],
                "reversal_of_payment_id": [None, "pay-1"],
            }
        )
        findings = temporal_rules.reversal_references_earlier_payment(
            {"payments": payments}, "payments"
        )

        assert len(findings) == 1
        assert findings[0].code == "REVERSAL_NOT_AFTER_ORIGINAL"

    def test_reversal_after_original_is_fine(self) -> None:
        payments = pd.DataFrame(
            {
                "payment_id": ["pay-1", "pay-2"],
                "payment_timestamp": ["2024-01-05T00:00:00Z", "2024-01-10T00:00:00Z"],
                "reversal_of_payment_id": [None, "pay-1"],
            }
        )
        findings = temporal_rules.reversal_references_earlier_payment(
            {"payments": payments}, "payments"
        )

        assert findings == []

    def test_no_reversals_present_produces_no_findings(self) -> None:
        payments = pd.DataFrame(
            {
                "payment_id": ["pay-1"],
                "payment_timestamp": ["2024-01-05T00:00:00Z"],
                "reversal_of_payment_id": [None],
            }
        )
        findings = temporal_rules.reversal_references_earlier_payment(
            {"payments": payments}, "payments"
        )

        assert findings == []


class TestPolicyValidityWindowNotInverted:
    def test_effective_to_before_effective_from_is_flagged(self) -> None:
        policies = pd.DataFrame(
            {
                "policy_version_id": ["pv-1"],
                "effective_from": ["2024-06-01T00:00:00Z"],
                "effective_to": ["2024-01-01T00:00:00Z"],
            }
        )
        findings = temporal_rules.policy_validity_window_not_inverted(
            {"policy_versions": policies}, "policy_versions"
        )

        assert len(findings) == 1
        assert findings[0].code == "POLICY_WINDOW_INVERTED"

    def test_open_ended_window_is_fine(self) -> None:
        policies = pd.DataFrame(
            {
                "policy_version_id": ["pv-1"],
                "effective_from": ["2024-01-01T00:00:00Z"],
                "effective_to": [None],
            }
        )
        findings = temporal_rules.policy_validity_window_not_inverted(
            {"policy_versions": policies}, "policy_versions"
        )

        assert findings == []


class TestBcbDatesStrictlyIncreasing:
    def test_duplicate_date_is_flagged(self) -> None:
        """Regression test for the Phase 2 BCB chunking-boundary bug: a
        duplicate observation date (as happened at a chunk merge boundary)
        must be caught."""
        df = pd.DataFrame({"data": ["01/01/2020", "01/02/2020", "01/02/2020", "01/03/2020"]})
        findings = temporal_rules.bcb_dates_strictly_increasing(
            {"bcb_sgs_20570": df}, "bcb_sgs_20570"
        )

        assert len(findings) == 1
        assert findings[0].code == "BCB_DATES_NOT_STRICTLY_INCREASING"

    def test_unique_dates_out_of_row_order_are_not_flagged(self) -> None:
        """The check sorts dates before comparing diffs, so rows merely
        appearing out of order in the file (with no duplicate/collision)
        are not an error - only a same-or-earlier date after sorting is."""
        df = pd.DataFrame({"data": ["01/03/2020", "01/01/2020", "01/02/2020"]})
        findings = temporal_rules.bcb_dates_strictly_increasing(
            {"bcb_sgs_20570": df}, "bcb_sgs_20570"
        )

        assert findings == []

    def test_strictly_increasing_dates_produce_no_findings(self) -> None:
        df = pd.DataFrame({"data": ["01/01/2020", "01/02/2020", "01/03/2020"]})
        findings = temporal_rules.bcb_dates_strictly_increasing(
            {"bcb_sgs_20570": df}, "bcb_sgs_20570"
        )

        assert findings == []

    def test_missing_table_reports_info(self) -> None:
        findings = temporal_rules.bcb_dates_strictly_increasing({}, "bcb_sgs_20570")

        assert findings[0].severity == "info"


def test_rules_registry_contains_every_function() -> None:
    assert set(temporal_rules.RULES) == {
        "decision_not_before_submission",
        "contract_after_decision",
        "disbursement_not_before_contract",
        "write_off_not_before_contract",
        "recovery_after_write_off",
        "reversal_references_earlier_payment",
        "policy_validity_window_not_inverted",
        "bcb_dates_strictly_increasing",
    }
