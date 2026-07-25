"""Installment amortization schedules.

Standard reducing-balance (Price/French) amortization: a level payment
per period, split into a shrinking interest component and a growing
principal component. This is a CredLens convention choice for the
baseline scenario, not a claim that it's the only valid amortization
method (flat-rate schedules exist too) - documented here and in
docs/synthetic_generation_implementation.md.

Uses `Decimal`, quantized to 2 decimal places (ROUND_HALF_UP) every
period, with any residual cent from rounding absorbed into the LAST
installment - see docs/synthetic_generation_implementation.md "Financial
precision". Looping per (contract, installment) is bounded (at most a
few dozen installments per contract) and therefore cheap even at
portfolio scale - never a loop over millions of raw rows.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

import pandas as pd

from credlens.generation.ids import IdFactory

_CENTS = Decimal("0.01")


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)


def _amortize_one_contract(
    financed_amount: Decimal, rate: Decimal, n_installments: int
) -> list[tuple[Decimal, Decimal, Decimal]]:
    """Returns a list of (principal, interest, total) per installment,
    reconciling exactly to financed_amount in total principal."""
    if n_installments <= 0:
        return []

    if rate == 0:
        level_payment = _quantize(financed_amount / n_installments)
    else:
        factor = 1 - (1 + rate) ** (-n_installments)
        level_payment = _quantize(financed_amount * rate / factor)

    balance = financed_amount
    rows: list[tuple[Decimal, Decimal, Decimal]] = []
    for period in range(1, n_installments + 1):
        interest = _quantize(balance * rate)
        if period < n_installments:
            principal = _quantize(level_payment - interest)
        else:
            # Last installment absorbs whatever residual rounding left behind,
            # so total principal reconciles exactly to financed_amount.
            principal = _quantize(balance)
        total = _quantize(principal + interest)
        rows.append((principal, interest, total))
        balance = _quantize(balance - principal)

    return rows


def generate_installments(contracts: pd.DataFrame, installment_ids: IdFactory) -> pd.DataFrame:
    if contracts.empty:
        return pd.DataFrame(
            columns=[
                "installment_id",
                "contract_id",
                "installment_number",
                "due_date",
                "scheduled_principal",
                "scheduled_interest",
                "scheduled_fees",
                "scheduled_total",
                "status",
                "outstanding_balance",
            ]
        )

    records: list[dict[str, object]] = []
    for row in contracts.to_dict("records"):
        financed_amount = Decimal(str(row["financed_amount"]))
        rate = Decimal(str(row["contract_rate"]))
        n_installments = int(row["num_installments"])
        first_due = pd.Timestamp(row["first_due_date"])

        schedule = _amortize_one_contract(financed_amount, rate, n_installments)
        for period, (principal, interest, total) in enumerate(schedule, start=1):
            due_date = first_due + pd.DateOffset(months=period - 1)
            records.append(
                {
                    "installment_id": installment_ids.next(),
                    "contract_id": row["contract_id"],
                    "installment_number": period,
                    "due_date": due_date.strftime("%Y-%m-%d"),
                    "scheduled_principal": float(principal),
                    "scheduled_interest": float(interest),
                    "scheduled_fees": 0.0,
                    "scheduled_total": float(total),
                    "status": "scheduled",
                    "outstanding_balance": float(total),
                }
            )

    return pd.DataFrame.from_records(records)
