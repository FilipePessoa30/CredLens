"""Tests for credlens.generation.allocations and .snapshots: the
deterministic fees->interest->principal allocation order and the DPD/
bucket derivation formula."""

from __future__ import annotations

from decimal import Decimal

import pandas as pd

from credlens.generation.allocations import OpenInstallment, allocate_payment
from credlens.generation.snapshots import compute_dpd, derive_snapshot_row, dpd_bucket


def _inst(installment_id: str, principal: str, interest: str, fees: str) -> OpenInstallment:
    return OpenInstallment(installment_id, Decimal(principal), Decimal(interest), Decimal(fees))


class TestAllocatePayment:
    def test_fees_paid_before_interest_before_principal(self) -> None:
        installment = _inst("i1", "100", "20", "5")
        result = allocate_payment(Decimal("10"), [installment])
        # 5 to fees, remaining 5 to interest, 0 to principal
        assert result == [("i1", Decimal("0"), Decimal("5"), Decimal("5"))]

    def test_full_payment_clears_one_installment_exactly(self) -> None:
        """allocate_payment only computes amounts - it does not mutate the
        installment; the caller (payments.py's loop) applies the
        subtraction. This is exactly what a full single-installment
        payment should compute."""
        installment = _inst("i1", "100", "20", "5")
        result = allocate_payment(Decimal("125"), [installment])
        assert result == [("i1", Decimal("100"), Decimal("20"), Decimal("5"))]

    def test_overpayment_flows_to_next_installment_oldest_first(self) -> None:
        first = _inst("i1", "50", "0", "0")
        second = _inst("i2", "50", "0", "0")
        result = allocate_payment(Decimal("75"), [first, second])
        assert result == [
            ("i1", Decimal("50"), Decimal("0"), Decimal("0")),
            ("i2", Decimal("25"), Decimal("0"), Decimal("0")),
        ]

    def test_never_allocates_more_than_the_payment_amount(self) -> None:
        installment = _inst("i1", "1000", "0", "0")
        result = allocate_payment(Decimal("10"), [installment])
        total_allocated = sum(p + i + f for _, p, i, f in result)
        assert total_allocated == Decimal("10")

    def test_zero_payment_allocates_nothing(self) -> None:
        installment = _inst("i1", "100", "0", "0")
        assert allocate_payment(Decimal("0"), [installment]) == []

    def test_installment_with_nothing_remaining_is_skipped(self) -> None:
        paid_off = _inst("i1", "0", "0", "0")
        open_one = _inst("i2", "50", "0", "0")
        result = allocate_payment(Decimal("50"), [paid_off, open_one])
        assert result == [("i2", Decimal("50"), Decimal("0"), Decimal("0"))]


class TestDpdAndBucket:
    def test_bucket_boundaries_inclusive(self) -> None:
        assert dpd_bucket(0) == "current"
        assert dpd_bucket(1) == "1-29"
        assert dpd_bucket(29) == "1-29"
        assert dpd_bucket(30) == "30-59"
        assert dpd_bucket(59) == "30-59"
        assert dpd_bucket(60) == "60-89"
        assert dpd_bucket(89) == "60-89"
        assert dpd_bucket(90) == "90+"
        assert dpd_bucket(500) == "90+"

    def test_compute_dpd_uses_oldest_overdue_installment(self) -> None:
        due_dates = {
            "i1": pd.Timestamp("2024-01-01"),
            "i2": pd.Timestamp("2024-02-01"),
        }
        installments = [_inst("i1", "10", "0", "0"), _inst("i2", "10", "0", "0")]
        dpd = compute_dpd(installments, due_dates, pd.Timestamp("2024-03-01"))
        assert dpd == (pd.Timestamp("2024-03-01") - pd.Timestamp("2024-01-01")).days

    def test_compute_dpd_ignores_not_yet_due_installments(self) -> None:
        due_dates = {"i1": pd.Timestamp("2024-06-01")}
        installments = [_inst("i1", "10", "0", "0")]
        dpd = compute_dpd(installments, due_dates, pd.Timestamp("2024-01-01"))
        assert dpd == 0

    def test_compute_dpd_ignores_fully_paid_installments(self) -> None:
        due_dates = {"i1": pd.Timestamp("2024-01-01")}
        installments = [_inst("i1", "0", "0", "0")]
        dpd = compute_dpd(installments, due_dates, pd.Timestamp("2024-06-01"))
        assert dpd == 0

    def test_compute_dpd_zero_when_nothing_open(self) -> None:
        assert compute_dpd([], {}, pd.Timestamp("2024-01-01")) == 0


class TestDeriveSnapshotRow:
    def test_current_contract_snapshot(self) -> None:
        due_dates = {"i1": pd.Timestamp("2024-06-01")}
        installments = [_inst("i1", "100", "5", "0")]
        row = derive_snapshot_row(
            "ctr-1",
            pd.Timestamp("2024-01-31"),
            installments,
            due_dates,
            Decimal("50"),
            Decimal("0"),
            "active",
        )
        assert row["dpd"] == 0
        assert row["delinquency_bucket"] == "current"
        assert row["total_balance"] == 105.0
        assert row["past_due_amount"] == 0.0
        assert row["next_due_date"] == "2024-06-01"

    def test_written_off_contract_zeroes_balance_but_keeps_real_dpd(self) -> None:
        """The Phase 4A fix: write-off never substitutes a sentinel for
        dpd - it stays the real, ledger-derived value, while the balance
        itself is netted to zero."""
        due_dates = {"i1": pd.Timestamp("2024-02-12")}
        installments = [_inst("i1", "166", "10", "0")]
        row = derive_snapshot_row(
            "ctr-1",
            pd.Timestamp("2024-06-30"),
            installments,
            due_dates,
            Decimal("0"),
            Decimal("176"),
            "charged_off",
        )
        assert row["dpd"] == (pd.Timestamp("2024-06-30") - pd.Timestamp("2024-02-12")).days
        assert row["dpd"] != 999
        assert row["total_balance"] == 0.0
        assert row["outstanding_principal"] == 0.0
        assert row["exposure"] == 0.0
        assert row["past_due_amount"] == 0.0
        assert row["next_due_date"] is None

    def test_exposure_is_zero_for_any_terminal_status(self) -> None:
        due_dates = {"i1": pd.Timestamp("2024-01-01")}
        installments = [_inst("i1", "0", "0", "0")]
        row = derive_snapshot_row(
            "ctr-1",
            pd.Timestamp("2024-02-29"),
            installments,
            due_dates,
            Decimal("100"),
            Decimal("0"),
            "settled",
        )
        assert row["exposure"] == 0.0
