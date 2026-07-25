"""Derives one account_monthly_snapshots row from the generator's own
in-memory ledger state at a given month-end - never generated
independently of installments/payments (see docs/adr/0009 and
credlens.contracts.financial_rules for the independent, output-side
reconciliation that checks this module's work after the fact).
"""

from __future__ import annotations

from decimal import Decimal

import pandas as pd

from credlens.generation.allocations import OpenInstallment

_DPD_BUCKET_EDGES = (-1, 0, 29, 59, 89)
_DPD_BUCKET_LABELS = ("current", "1-29", "30-59", "60-89", "90+")


def dpd_bucket(dpd: int) -> str:
    for edge, label in zip(_DPD_BUCKET_EDGES[1:], _DPD_BUCKET_LABELS[:-1], strict=True):
        if dpd <= edge:
            return label
    return _DPD_BUCKET_LABELS[-1]


def compute_dpd(
    open_installments: list[OpenInstallment],
    due_dates: dict[str, pd.Timestamp],
    month_end: pd.Timestamp,
) -> int:
    """max(month_end - due_date) in days, over installments still open
    (remaining_total > 0) with due_date < month_end - matches
    docs/metric_semantics.md exactly."""
    worst = 0
    for inst in open_installments:
        if inst.remaining_total <= 0:
            continue
        due = due_dates[inst.installment_id]
        if due < month_end:
            days = (month_end - due).days
            if days > worst:
                worst = days
    return worst


def derive_snapshot_row(
    contract_id: str,
    month_end: pd.Timestamp,
    open_installments: list[OpenInstallment],
    due_dates: dict[str, pd.Timestamp],
    cumulative_paid: Decimal,
    cumulative_write_off: Decimal,
    status: str,
) -> dict[str, object]:
    outstanding_principal = sum((i.remaining_principal for i in open_installments), Decimal("0"))
    outstanding_interest = sum((i.remaining_interest for i in open_installments), Decimal("0"))
    outstanding_fees = sum((i.remaining_fees for i in open_installments), Decimal("0"))
    remaining_total = outstanding_principal + outstanding_interest + outstanding_fees
    total_balance = max(Decimal("0"), remaining_total - cumulative_write_off)

    is_terminal = status in ("settled", "closed", "charged_off")
    if is_terminal and cumulative_write_off > 0:
        # Written off: nothing is carried on book anymore - the loss is in
        # cumulative_write_off, not in an outstanding balance.
        outstanding_principal = Decimal("0")
        outstanding_interest = Decimal("0")
        outstanding_fees = Decimal("0")
        total_balance = Decimal("0")

    dpd = compute_dpd(open_installments, due_dates, month_end)
    if is_terminal and cumulative_write_off > 0:
        past_due_amount = Decimal("0")
    else:
        past_due_amount = sum(
            (
                i.remaining_total
                for i in open_installments
                if i.remaining_total > 0 and due_dates[i.installment_id] < month_end
            ),
            Decimal("0"),
        )

    future_due = sorted(
        (
            due_dates[i.installment_id]
            for i in open_installments
            if due_dates[i.installment_id] >= month_end
        ),
    )
    next_due_date = future_due[0].strftime("%Y-%m-%d") if future_due and not is_terminal else None

    exposure = Decimal("0") if is_terminal else total_balance

    return {
        "contract_id": contract_id,
        "snapshot_date": month_end.strftime("%Y-%m-%d"),
        "outstanding_principal": float(outstanding_principal),
        "outstanding_interest": float(outstanding_interest),
        "outstanding_fees": float(outstanding_fees),
        "total_balance": float(total_balance),
        "past_due_amount": float(past_due_amount),
        "next_due_date": next_due_date,
        "dpd": dpd,
        "delinquency_bucket": dpd_bucket(dpd),
        "status": status,
        "exposure": float(exposure),
        "cumulative_paid": float(cumulative_paid),
        "cumulative_write_off": float(cumulative_write_off),
    }
