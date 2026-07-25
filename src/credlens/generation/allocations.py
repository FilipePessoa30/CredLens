"""Deterministic payment-to-installment allocation.

CredLens convention (not a claimed universal accounting rule, see
config/synthetic/baseline.generation.yaml's payment_behavior.allocation_order
and docs/business_rules.md): within the oldest still-open installment
first, apply the payment to fees, then interest, then principal; once
that installment is fully covered, move to the next-oldest open
installment, until the payment amount is exhausted or every open
installment is paid off (any remainder is a prepayment sitting on the
next not-yet-due installment, if one exists).
"""

from __future__ import annotations

from decimal import Decimal


class OpenInstallment:
    """Mutable view of one installment's remaining components, used only
    within a single allocate_payment() call."""

    __slots__ = ("installment_id", "remaining_fees", "remaining_interest", "remaining_principal")

    def __init__(
        self,
        installment_id: str,
        remaining_principal: Decimal,
        remaining_interest: Decimal,
        remaining_fees: Decimal,
    ) -> None:
        self.installment_id = installment_id
        self.remaining_principal = remaining_principal
        self.remaining_interest = remaining_interest
        self.remaining_fees = remaining_fees

    @property
    def remaining_total(self) -> Decimal:
        return self.remaining_principal + self.remaining_interest + self.remaining_fees


def allocate_payment(
    amount: Decimal, open_installments: list[OpenInstallment]
) -> list[tuple[str, Decimal, Decimal, Decimal]]:
    """Distributes `amount` (already >= 0) across `open_installments`
    (must be pre-sorted oldest-due-first by the caller), fees -> interest
    -> principal within each installment before moving to the next.

    Returns a list of (installment_id, principal, interest, fees) tuples,
    one entry per installment actually touched (skips installments that
    receive nothing). Never allocates more than `amount` in total, and
    never more than each installment's own remaining components -
    matching payment_allocation_not_exceed_payment.
    """
    remaining = amount
    results: list[tuple[str, Decimal, Decimal, Decimal]] = []

    for installment in open_installments:
        if remaining <= 0:
            break

        fees_paid = min(remaining, installment.remaining_fees)
        remaining -= fees_paid

        interest_paid = min(remaining, installment.remaining_interest)
        remaining -= interest_paid

        principal_paid = min(remaining, installment.remaining_principal)
        remaining -= principal_paid

        if fees_paid > 0 or interest_paid > 0 or principal_paid > 0:
            results.append((installment.installment_id, principal_paid, interest_paid, fees_paid))

    return results
