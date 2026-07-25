"""The month-by-month portfolio ledger simulation - the core of the
baseline generator.

Complexity: O(months x active_contracts), months is bounded (12 for the
baseline period) and each contract's own per-month work is O(its open
installment count, at most a few dozen) - never a loop over raw
installment/payment ROWS beyond what a single contract/month actually
touches. At portfolio scale (~30k contracts x 12 months) this is a few
hundred thousand lightweight Python-level iterations - seconds, not
minutes; still bounded, unlike a naive O(rows^2) approach would be.

Events are the only thing that changes state (docs/adr/0003): balance,
DPD, bucket, and cumulative fields are always derived from the ledger
(installments + payments + payment_allocations + write_off_events)
inside this loop - nothing here sets a snapshot's dpd/balance directly
from a probability draw. The latent per-contract payment propensity
(truth.py) only ever influences *whether/how much* a contract pays this
month - never account_monthly_snapshots' derived fields directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

import numpy as np
import pandas as pd

from credlens.generation.allocations import OpenInstallment, allocate_payment
from credlens.generation.collections import collection_event_row, should_contact
from credlens.generation.config import GenerationConfig
from credlens.generation.ids import IdFactory
from credlens.generation.recoveries import recovery_event_row, schedule_recovery
from credlens.generation.snapshots import compute_dpd, derive_snapshot_row
from credlens.generation.writeoffs import should_write_off, write_off_event_row

_CENTS = Decimal("0.01")
_OUTCOMES = ("on_time", "partial", "prepay", "no_pay")
_CHANNELS = ("app", "web", "bank_slip", "direct_debit", "collections_agent")

# Explicit column lists for each output table - used so an empty result
# (e.g. a smoke run with zero recoveries) still produces a DataFrame with
# the right schema, instead of pandas inferring zero columns from an
# empty list of dicts (which would break both Parquet writing and
# contract validation's column checks).
_PAYMENT_COLUMNS = (
    "payment_id",
    "customer_id",
    "contract_id",
    "payment_timestamp",
    "amount",
    "channel",
    "status",
    "settlement_date",
    "reversal_of_payment_id",
)
_ALLOCATION_COLUMNS = (
    "allocation_id",
    "payment_id",
    "installment_id",
    "contract_id",
    "allocated_principal",
    "allocated_interest",
    "allocated_fees",
    "allocated_total",
)
_SNAPSHOT_COLUMNS = (
    "contract_id",
    "snapshot_date",
    "outstanding_principal",
    "outstanding_interest",
    "outstanding_fees",
    "total_balance",
    "past_due_amount",
    "next_due_date",
    "dpd",
    "delinquency_bucket",
    "status",
    "exposure",
    "cumulative_paid",
    "cumulative_write_off",
)
_COLLECTION_COLUMNS = (
    "collection_event_id",
    "contract_id",
    "event_timestamp",
    "channel",
    "strategy",
    "outcome",
    "promise_to_pay",
    "promised_amount",
    "promised_date",
    "status",
)
_WRITE_OFF_COLUMNS = (
    "write_off_id",
    "contract_id",
    "write_off_date",
    "amount",
    "principal",
    "interest",
    "fees",
    "reason",
    "policy_reference",
)
_RECOVERY_COLUMNS = (
    "recovery_id",
    "contract_id",
    "write_off_id",
    "recovery_date",
    "amount",
    "channel",
    "source",
)


def _frame(rows: list[dict[str, object]], columns: tuple[str, ...]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=list(columns))
    return pd.DataFrame(rows)


@dataclass
class LedgerSimulationResult:
    payments: pd.DataFrame
    payment_allocations: pd.DataFrame
    installments: pd.DataFrame
    account_monthly_snapshots: pd.DataFrame
    collection_events: pd.DataFrame
    write_off_events: pd.DataFrame
    recovery_events: pd.DataFrame


@dataclass
class _ContractState:
    open_installments: list[OpenInstallment]
    status: str = "active"
    cumulative_paid: Decimal = field(default_factory=lambda: Decimal("0"))
    cumulative_write_off: Decimal = field(default_factory=lambda: Decimal("0"))
    terminal_month: pd.Timestamp | None = None
    write_off_id: str | None = None
    scheduled_recovery: tuple[int, Decimal] | None = None


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)


def _decide_payment_amount(
    state: _ContractState,
    due_dates: dict[str, pd.Timestamp],
    month_start: pd.Timestamp,
    month_end: pd.Timestamp,
    propensity: float,
    config: GenerationConfig,
    rng: np.random.Generator,
) -> Decimal:
    payable = [
        i
        for i in state.open_installments
        if i.remaining_total > 0 and due_dates[i.installment_id] <= month_end
    ]
    if not payable:
        return Decimal("0")

    has_backlog = any(due_dates[i.installment_id] < month_start for i in payable)
    total_open = sum((i.remaining_total for i in state.open_installments), Decimal("0"))

    if has_backlog:
        cure_chance = min(
            0.95, config.payment_behavior.cure_probability_per_month * (0.5 + propensity)
        )
        if rng.random() < cure_chance:
            return min(total_open, total_open)  # full cure: pay everything open
        return Decimal("0")

    due_amount = sum((i.remaining_total for i in payable), Decimal("0"))
    scale = propensity / 0.75
    on_time_w = float(np.clip(config.payment_behavior.on_time_probability * scale, 0.0, 0.97))
    partial_w = config.payment_behavior.partial_payment_probability
    prepay_w = float(np.clip(config.payment_behavior.prepayment_probability * scale, 0.0, 1.0))
    no_pay_w = max(0.01, 1 - on_time_w - partial_w - prepay_w)
    weights = np.array([on_time_w, partial_w, prepay_w, no_pay_w])
    weights = weights / weights.sum()
    outcome = rng.choice(_OUTCOMES, p=weights)

    if outcome == "on_time":
        amount = due_amount
    elif outcome == "partial":
        fraction = Decimal(str(round(float(rng.uniform(0.3, 0.8)), 4)))
        amount = _quantize(due_amount * fraction)
    elif outcome == "prepay":
        amount = total_open  # a full early payoff
    else:
        amount = Decimal("0")

    return min(amount, total_open)


def simulate_portfolio_ledger(
    contracts: pd.DataFrame,
    installments: pd.DataFrame,
    latent_contract_truth: pd.DataFrame,
    config: GenerationConfig,
    as_of_date: pd.Timestamp,
    id_factories: dict[str, IdFactory],
    streams: dict[str, np.random.Generator],
) -> LedgerSimulationResult:
    if contracts.empty:
        empty_installments = installments.copy()
        return LedgerSimulationResult(
            payments=_frame([], _PAYMENT_COLUMNS),
            payment_allocations=_frame([], _ALLOCATION_COLUMNS),
            installments=empty_installments,
            account_monthly_snapshots=_frame([], _SNAPSHOT_COLUMNS),
            collection_events=_frame([], _COLLECTION_COLUMNS),
            write_off_events=_frame([], _WRITE_OFF_COLUMNS),
            recovery_events=_frame([], _RECOVERY_COLUMNS),
        )

    due_dates: dict[str, pd.Timestamp] = {
        str(row["installment_id"]): pd.Timestamp(row["due_date"])
        for row in installments.to_dict("records")
    }
    customer_by_contract = contracts.set_index("contract_id")["customer_id"]
    propensity_by_contract = latent_contract_truth.set_index("contract_id")[
        "latent_payment_propensity"
    ].to_dict()

    states: dict[str, _ContractState] = {}
    for contract_id, group in installments.groupby("contract_id"):
        open_installments = [
            OpenInstallment(
                installment_id=str(row["installment_id"]),
                remaining_principal=Decimal(str(row["scheduled_principal"])),
                remaining_interest=Decimal(str(row["scheduled_interest"])),
                remaining_fees=Decimal(str(row["scheduled_fees"])),
            )
            for row in group.to_dict("records")
        ]
        states[str(contract_id)] = _ContractState(open_installments=open_installments)

    disbursement_by_contract = pd.to_datetime(
        contracts.set_index("contract_id")["disbursement_date"]
    )

    month_ends = pd.date_range(
        start=pd.Timestamp(config.period.start),
        end=min(pd.Timestamp(config.period.end), as_of_date),
        freq="ME",
    )

    payments_rows: list[dict[str, object]] = []
    allocation_rows: list[dict[str, object]] = []
    snapshot_rows: list[dict[str, object]] = []
    collection_rows: list[dict[str, object]] = []
    write_off_rows: list[dict[str, object]] = []
    recovery_rows: list[dict[str, object]] = []

    payment_ids = id_factories["payment"]
    allocation_ids = id_factories["allocation"]
    write_off_ids = id_factories["write_off"]
    collection_ids = id_factories["collection_event"]
    recovery_ids = id_factories["recovery"]

    payments_rng = streams["payments"]
    collections_rng = streams["collections"]
    write_off_rng = streams["write_off"]
    recovery_rng = streams["recovery"]

    for month_index, month_end in enumerate(month_ends):
        month_start = month_end.replace(day=1)
        tz_month_end = month_end.tz_localize("UTC") if month_end.tzinfo is None else month_end

        for contract_id, state in states.items():
            if state.terminal_month is not None:
                continue
            disbursement = disbursement_by_contract[contract_id]
            disbursed_naive = (
                disbursement.tz_localize(None) if disbursement.tzinfo else disbursement
            )
            if disbursed_naive.normalize() > month_end:
                continue

            propensity = float(propensity_by_contract.get(contract_id, 0.75))
            amount = _decide_payment_amount(
                state, due_dates, month_start, month_end, propensity, config, payments_rng
            )

            if amount > 0:
                sorted_open = sorted(
                    (i for i in state.open_installments if i.remaining_total > 0),
                    key=lambda i: due_dates[i.installment_id],
                )
                allocations = allocate_payment(amount, sorted_open)
                pay_day = int(payments_rng.integers(1, month_end.day + 1))
                payment_ts = pd.Timestamp(
                    year=month_end.year, month=month_end.month, day=pay_day, tz="UTC"
                )
                payment_id = payment_ids.next()
                channel = str(payments_rng.choice(_CHANNELS))
                payments_rows.append(
                    {
                        "payment_id": payment_id,
                        "customer_id": customer_by_contract[contract_id],
                        "contract_id": contract_id,
                        "payment_timestamp": payment_ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "amount": float(amount),
                        "channel": channel,
                        "status": "settled",
                        "settlement_date": payment_ts.strftime("%Y-%m-%d"),
                        "reversal_of_payment_id": None,
                    }
                )
                by_id = {i.installment_id: i for i in state.open_installments}
                for installment_id, principal, interest, fees in allocations:
                    allocation_rows.append(
                        {
                            "allocation_id": allocation_ids.next(),
                            "payment_id": payment_id,
                            "installment_id": installment_id,
                            "contract_id": contract_id,
                            "allocated_principal": float(principal),
                            "allocated_interest": float(interest),
                            "allocated_fees": float(fees),
                            "allocated_total": float(principal + interest + fees),
                        }
                    )
                    inst = by_id[installment_id]
                    inst.remaining_principal -= principal
                    inst.remaining_interest -= interest
                    inst.remaining_fees -= fees
                state.cumulative_paid += amount

                if payments_rng.random() < config.payment_behavior.reversal_rate:
                    reversal_ts = payment_ts + pd.Timedelta(days=1)
                    # Must settle within the SAME calendar month as the
                    # original payment: this month's snapshot (taken once,
                    # at month-end) is the only point where this contract's
                    # ledger state is observed, so as long as both events
                    # land before that same month-end, the eager in-memory
                    # netting below agrees with the independent as-of-date
                    # reconciliation in credlens.contracts.financial_rules
                    # (which sums events by their own settlement_date). A
                    # reversal crossing into the NEXT month would net out
                    # here immediately but only take effect one month late
                    # from that reconciliation's point of view - skip it
                    # instead of introducing that inconsistency.
                    same_month = (
                        reversal_ts.year == payment_ts.year
                        and reversal_ts.month == payment_ts.month
                    )
                    if same_month and reversal_ts <= tz_month_end:
                        reversal_id = payment_ids.next()
                        payments_rows.append(
                            {
                                "payment_id": reversal_id,
                                "customer_id": customer_by_contract[contract_id],
                                "contract_id": contract_id,
                                "payment_timestamp": reversal_ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                "amount": float(amount),
                                "channel": channel,
                                "status": "settled",
                                "settlement_date": reversal_ts.strftime("%Y-%m-%d"),
                                "reversal_of_payment_id": payment_id,
                            }
                        )
                        for installment_id, principal, interest, fees in allocations:
                            allocation_rows.append(
                                {
                                    "allocation_id": allocation_ids.next(),
                                    "payment_id": reversal_id,
                                    "installment_id": installment_id,
                                    "contract_id": contract_id,
                                    "allocated_principal": float(principal),
                                    "allocated_interest": float(interest),
                                    "allocated_fees": float(fees),
                                    "allocated_total": float(principal + interest + fees),
                                }
                            )
                            inst = by_id[installment_id]
                            inst.remaining_principal += principal
                            inst.remaining_interest += interest
                            inst.remaining_fees += fees
                        state.cumulative_paid -= amount

            dpd = compute_dpd(state.open_installments, due_dates, month_end)
            total_open = sum((i.remaining_total for i in state.open_installments), Decimal("0"))

            if (
                total_open <= Decimal(str(config.tolerance.monetary_tolerance))
                and state.status != "charged_off"
            ):
                state.status = "settled"
                state.terminal_month = month_end
            elif should_write_off(dpd, config.write_off):
                principal = sum(
                    (i.remaining_principal for i in state.open_installments), Decimal("0")
                )
                interest = sum(
                    (i.remaining_interest for i in state.open_installments), Decimal("0")
                )
                fees = sum((i.remaining_fees for i in state.open_installments), Decimal("0"))
                row = write_off_event_row(
                    contract_id,
                    month_end,
                    principal,
                    interest,
                    fees,
                    config.write_off.dpd_threshold,
                    write_off_ids,
                )
                write_off_rows.append(row)
                state.cumulative_write_off = Decimal(str(row["amount"]))
                state.write_off_id = str(row["write_off_id"])
                state.status = "charged_off"
                state.terminal_month = month_end

                scheduled = schedule_recovery(
                    state.cumulative_write_off, config.recovery, write_off_rng
                )
                if scheduled is not None:
                    offset, recovery_amount = scheduled
                    state.scheduled_recovery = (month_index + offset, recovery_amount)
            elif dpd > 0:
                state.status = "delinquent"
            else:
                state.status = "active"

            snapshot_rows.append(
                derive_snapshot_row(
                    contract_id,
                    month_end,
                    state.open_installments,
                    due_dates,
                    state.cumulative_paid,
                    state.cumulative_write_off,
                    state.status,
                )
            )

            if state.status in ("active", "delinquent") and should_contact(dpd, config.collections):
                due_now = [
                    i
                    for i in state.open_installments
                    if i.remaining_total > 0 and due_dates[i.installment_id] <= month_end
                ]
                amount_due = float(sum((i.remaining_total for i in due_now), Decimal("0")))
                collection_rows.append(
                    collection_event_row(
                        contract_id,
                        month_end,
                        dpd,
                        amount_due,
                        config.collections,
                        collection_ids,
                        collections_rng,
                    )
                )

        # Recoveries scheduled to land in this month, for contracts already terminal.
        for contract_id, state in states.items():
            if state.scheduled_recovery is None or state.write_off_id is None:
                continue
            target_index, amount = state.scheduled_recovery
            if target_index == month_index:
                recovery_rows.append(
                    recovery_event_row(
                        contract_id,
                        state.write_off_id,
                        month_end,
                        amount,
                        recovery_ids,
                        recovery_rng,
                    )
                )
                state.scheduled_recovery = None

    final_installments = installments.copy()
    remaining_by_id = {
        i.installment_id: i for state in states.values() for i in state.open_installments
    }
    statuses = []
    outstanding = []
    for inst_row in final_installments.to_dict("records"):
        installment_id = str(inst_row["installment_id"])
        inst = remaining_by_id[installment_id]
        scheduled_total = Decimal(str(inst_row["scheduled_total"]))
        due_date = due_dates[installment_id]
        if inst.remaining_total <= 0:
            status = "paid"
        elif states[str(inst_row["contract_id"])].status == "charged_off":
            status = "written_off"
        elif inst.remaining_total < scheduled_total:
            status = "partially_paid"
        elif due_date < as_of_date:
            status = "overdue"
        elif due_date <= as_of_date:
            status = "due"
        else:
            status = "scheduled"
        statuses.append(status)
        outstanding.append(float(inst.remaining_total))
    final_installments["status"] = statuses
    final_installments["outstanding_balance"] = outstanding

    return LedgerSimulationResult(
        payments=_frame(payments_rows, _PAYMENT_COLUMNS),
        payment_allocations=_frame(allocation_rows, _ALLOCATION_COLUMNS),
        installments=final_installments,
        account_monthly_snapshots=_frame(snapshot_rows, _SNAPSHOT_COLUMNS),
        collection_events=_frame(collection_rows, _COLLECTION_COLUMNS),
        write_off_events=_frame(write_off_rows, _WRITE_OFF_COLUMNS),
        recovery_events=_frame(recovery_rows, _RECOVERY_COLUMNS),
    )
