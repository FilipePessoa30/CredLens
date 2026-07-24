"""Tests for credlens.contracts.financial_rules: reconciliation, DPD
bucketing, and monotonicity business rules."""

from __future__ import annotations

import pandas as pd

from credlens.contracts import financial_rules


class TestInstallmentTotalReconciled:
    def test_mismatched_total_is_flagged(self) -> None:
        df = pd.DataFrame(
            {
                "installment_id": ["inst-1"],
                "scheduled_total": [100],
                "scheduled_principal": [80],
                "scheduled_interest": [10],
                "scheduled_fees": [5],
            }
        )
        findings = financial_rules.installment_total_reconciled(
            {"installments": df}, "installments"
        )

        assert len(findings) == 1
        assert findings[0].code == "INSTALLMENT_TOTAL_NOT_RECONCILED"

    def test_matching_total_is_fine(self) -> None:
        df = pd.DataFrame(
            {
                "installment_id": ["inst-1"],
                "scheduled_total": [95],
                "scheduled_principal": [80],
                "scheduled_interest": [10],
                "scheduled_fees": [5],
            }
        )
        findings = financial_rules.installment_total_reconciled(
            {"installments": df}, "installments"
        )

        assert findings == []

    def test_within_tolerance_is_fine(self) -> None:
        df = pd.DataFrame(
            {
                "installment_id": ["inst-1"],
                "scheduled_total": [95.005],
                "scheduled_principal": [80],
                "scheduled_interest": [10],
                "scheduled_fees": [5],
            }
        )
        findings = financial_rules.installment_total_reconciled(
            {"installments": df}, "installments"
        )

        assert findings == []


class TestAllocationTotalReconciled:
    def test_mismatched_total_is_flagged(self) -> None:
        df = pd.DataFrame(
            {
                "allocation_id": ["alloc-1"],
                "allocated_total": [100],
                "allocated_principal": [50],
                "allocated_interest": [10],
                "allocated_fees": [5],
            }
        )
        findings = financial_rules.allocation_total_reconciled(
            {"payment_allocations": df}, "payment_allocations"
        )

        assert len(findings) == 1
        assert findings[0].code == "ALLOCATION_TOTAL_NOT_RECONCILED"


class TestAllocationAmountNotNegative:
    def test_negative_component_is_flagged(self) -> None:
        df = pd.DataFrame(
            {
                "allocation_id": ["alloc-1"],
                "allocated_principal": [-10],
                "allocated_interest": [5],
                "allocated_fees": [0],
                "allocated_total": [-5],
            }
        )
        findings = financial_rules.allocation_amount_not_negative(
            {"payment_allocations": df}, "payment_allocations"
        )

        assert len(findings) == 1
        assert findings[0].code == "NEGATIVE_ALLOCATION_AMOUNT"

    def test_all_non_negative_is_fine(self) -> None:
        df = pd.DataFrame(
            {
                "allocation_id": ["alloc-1"],
                "allocated_principal": [10],
                "allocated_interest": [5],
                "allocated_fees": [0],
                "allocated_total": [15],
            }
        )
        findings = financial_rules.allocation_amount_not_negative(
            {"payment_allocations": df}, "payment_allocations"
        )

        assert findings == []


class TestWriteOffAmountReconciled:
    def test_mismatched_amount_is_flagged(self) -> None:
        df = pd.DataFrame(
            {
                "write_off_id": ["wo-1"],
                "amount": [1000],
                "principal": [800],
                "interest": [50],
                "fees": [0],
            }
        )
        findings = financial_rules.write_off_amount_reconciled(
            {"write_off_events": df}, "write_off_events"
        )

        assert len(findings) == 1
        assert findings[0].code == "WRITE_OFF_AMOUNT_NOT_RECONCILED"


class TestTotalBalanceReconciled:
    def test_mismatched_balance_is_flagged(self) -> None:
        df = pd.DataFrame(
            {
                "contract_id": ["ctr-1"],
                "snapshot_date": ["2024-01-31"],
                "total_balance": [1000],
                "outstanding_principal": [800],
                "outstanding_interest": [50],
                "outstanding_fees": [0],
            }
        )
        findings = financial_rules.total_balance_reconciled(
            {"account_monthly_snapshots": df}, "account_monthly_snapshots"
        )

        assert len(findings) == 1
        assert findings[0].code == "TOTAL_BALANCE_NOT_RECONCILED"


class TestDpdMatchesBucket:
    def test_mismatched_bucket_is_flagged(self) -> None:
        df = pd.DataFrame(
            {
                "contract_id": ["ctr-1"],
                "snapshot_date": ["2024-01-31"],
                "dpd": [45],
                "delinquency_bucket": ["current"],
            }
        )
        findings = financial_rules.dpd_matches_bucket(
            {"account_monthly_snapshots": df}, "account_monthly_snapshots"
        )

        assert len(findings) == 1
        assert findings[0].code == "DPD_BUCKET_MISMATCH"

    def test_bucket_boundaries_are_inclusive_both_ends(self) -> None:
        """CredLens's own convention (docs/metric_semantics.md): 0=current,
        1-29, 30-59, 60-89, 90+, each range inclusive on both ends."""
        df = pd.DataFrame(
            {
                "contract_id": ["c1", "c2", "c3", "c4", "c5", "c6", "c7", "c8", "c9", "c10"],
                "snapshot_date": ["2024-01-31"] * 10,
                "dpd": [0, 1, 29, 30, 59, 60, 89, 90, 200, 999],
                "delinquency_bucket": [
                    "current",
                    "1-29",
                    "1-29",
                    "30-59",
                    "30-59",
                    "60-89",
                    "60-89",
                    "90+",
                    "90+",
                    "90+",
                ],
            }
        )
        findings = financial_rules.dpd_matches_bucket(
            {"account_monthly_snapshots": df}, "account_monthly_snapshots"
        )

        assert findings == []


class TestCumulativePaidNonDecreasing:
    def test_decrease_is_flagged_as_warning_not_error(self) -> None:
        """Contract declares this rule as `warning` severity - a documented
        reversal is a valid exception (see docs/business_rules.md)."""
        df = pd.DataFrame(
            {
                "contract_id": ["ctr-1", "ctr-1"],
                "snapshot_date": ["2024-01-31", "2024-02-29"],
                "cumulative_paid": [500, 300],
            }
        )
        findings = financial_rules.cumulative_paid_non_decreasing(
            {"account_monthly_snapshots": df}, "account_monthly_snapshots"
        )

        assert len(findings) == 1
        assert findings[0].code == "CUMULATIVE_PAID_DECREASED"
        assert findings[0].severity == "warning"

    def test_non_decreasing_across_months_is_fine(self) -> None:
        df = pd.DataFrame(
            {
                "contract_id": ["ctr-1", "ctr-1"],
                "snapshot_date": ["2024-01-31", "2024-02-29"],
                "cumulative_paid": [500, 700],
            }
        )
        findings = financial_rules.cumulative_paid_non_decreasing(
            {"account_monthly_snapshots": df}, "account_monthly_snapshots"
        )

        assert findings == []

    def test_decrease_across_different_contracts_is_not_flagged(self) -> None:
        df = pd.DataFrame(
            {
                "contract_id": ["ctr-1", "ctr-2"],
                "snapshot_date": ["2024-01-31", "2024-01-31"],
                "cumulative_paid": [500, 10],
            }
        )
        findings = financial_rules.cumulative_paid_non_decreasing(
            {"account_monthly_snapshots": df}, "account_monthly_snapshots"
        )

        assert findings == []


class TestCumulativeWriteOffNonDecreasing:
    def test_decrease_stays_error_severity(self) -> None:
        """Unlike cumulative_paid, this rule has no documented reversal
        exception and stays `error`."""
        df = pd.DataFrame(
            {
                "contract_id": ["ctr-1", "ctr-1"],
                "snapshot_date": ["2024-01-31", "2024-02-29"],
                "cumulative_write_off": [1000, 500],
            }
        )
        findings = financial_rules.cumulative_write_off_non_decreasing(
            {"account_monthly_snapshots": df}, "account_monthly_snapshots"
        )

        assert len(findings) == 1
        assert findings[0].severity == "error"


class TestPromiseFieldsRequirePromiseFlag:
    def test_promise_true_without_amount_or_date_is_flagged(self) -> None:
        df = pd.DataFrame(
            {
                "collection_event_id": ["ce-1"],
                "promise_to_pay": ["true"],
                "promised_amount": [None],
                "promised_date": [None],
            }
        )
        findings = financial_rules.promise_fields_require_promise_flag(
            {"collection_events": df}, "collection_events"
        )

        assert len(findings) == 1
        assert findings[0].code == "PROMISE_FIELDS_INCONSISTENT"

    def test_promise_false_with_amount_set_is_flagged(self) -> None:
        df = pd.DataFrame(
            {
                "collection_event_id": ["ce-1"],
                "promise_to_pay": ["false"],
                "promised_amount": [100.0],
                "promised_date": [None],
            }
        )
        findings = financial_rules.promise_fields_require_promise_flag(
            {"collection_events": df}, "collection_events"
        )

        assert len(findings) == 1

    def test_consistent_promise_true_is_fine(self) -> None:
        df = pd.DataFrame(
            {
                "collection_event_id": ["ce-1"],
                "promise_to_pay": ["true"],
                "promised_amount": [100.0],
                "promised_date": ["2024-02-01"],
            }
        )
        findings = financial_rules.promise_fields_require_promise_flag(
            {"collection_events": df}, "collection_events"
        )

        assert findings == []

    def test_consistent_promise_false_is_fine(self) -> None:
        df = pd.DataFrame(
            {
                "collection_event_id": ["ce-1"],
                "promise_to_pay": ["false"],
                "promised_amount": [None],
                "promised_date": [None],
            }
        )
        findings = financial_rules.promise_fields_require_promise_flag(
            {"collection_events": df}, "collection_events"
        )

        assert findings == []


def test_rules_registry_contains_every_function() -> None:
    assert set(financial_rules.RULES) == {
        "installment_total_reconciled",
        "allocation_total_reconciled",
        "allocation_amount_not_negative",
        "write_off_amount_reconciled",
        "total_balance_reconciled",
        "dpd_matches_bucket",
        "cumulative_paid_non_decreasing",
        "cumulative_write_off_non_decreasing",
        "promise_fields_require_promise_flag",
    }
