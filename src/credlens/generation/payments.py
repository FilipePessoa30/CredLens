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
from credlens.generation.config import GenerationConfig, PaymentBehaviorConfig
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
    "payment_type",
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
    # Installments are always exhausted in strict due-date order: allocate_payment
    # (allocations.py) walks its input oldest-first and only ever advances past an
    # installment once its remaining_total hits exactly 0 - fees/interest/principal
    # only ever decrease toward 0, never below, and a same-month reversal restores
    # exactly what it took away before this pointer is advanced for that month (see
    # the per-month loop below). So open_installments[:head_index] is permanently
    # exhausted and open_installments[head_index:] ("active") is exactly the still-
    # open set - an O(open) view instead of rescanning O(all installments this
    # contract was ever issued) every month. See docs/performance_optimization.md.
    head_index: int = 0


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)


def _clip01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _effective_payment_behavior(
    config: GenerationConfig, month_end: pd.Timestamp
) -> PaymentBehaviorConfig:
    """config.payment_behavior unchanged, UNLESS config.macro_shock is set
    AND month_end falls at/after its shock_date - in which case a shocked
    copy is returned (macroeconomic_stress scenario, Phase 4B). Every
    month before shock_date - and every month of every scenario that
    doesn't configure macro_shock at all - is completely unaffected, so
    baseline/policy_expansion/policy_tightening/collections_change/
    contract_coverage behave exactly as before this function existed."""
    shock = config.macro_shock
    if shock is None:
        return config.payment_behavior
    shock_date = pd.Timestamp(shock.shock_date)
    month_end_naive = month_end.tz_localize(None) if month_end.tzinfo else month_end
    if month_end_naive.normalize() < shock_date:
        return config.payment_behavior
    base = config.payment_behavior
    return base.model_copy(
        update={
            "on_time_probability": _clip01(
                base.on_time_probability * shock.on_time_probability_multiplier
            ),
            "partial_payment_probability": _clip01(
                base.partial_payment_probability * shock.partial_payment_probability_multiplier
            ),
            "prepayment_probability": _clip01(
                base.prepayment_probability * shock.prepayment_probability_multiplier
            ),
            "cure_probability_per_month": _clip01(
                base.cure_probability_per_month * shock.cure_probability_multiplier
            ),
        }
    )


def _decide_payment_amount(
    active_installments: list[OpenInstallment],
    due_dates: dict[str, pd.Timestamp],
    month_start: pd.Timestamp,
    month_end: pd.Timestamp,
    propensity: float,
    behavior: PaymentBehaviorConfig,
    rng: np.random.Generator,
) -> tuple[Decimal, str]:
    """Returns (amount, payment_type). payment_type is one of "scheduled"
    (on-time - pays exactly what's due), "partial" (a fraction of what's
    due), "cure" (pays off the overdue backlog ONLY - see below), or
    "prepayment" (a full early payoff of every remaining installment,
    including not-yet-due ones). amount == 0 means no payment this month;
    payment_type is meaningless in that case and never written to a row.

    active_installments is already pruned to remaining_total > 0 by the
    caller (state.open_installments[state.head_index:]) - no need to
    re-check that here. `behavior` is config.payment_behavior for every
    month before a configured macro_shock's shock_date (or always, if no
    shock is configured) and a shocked copy for every month at/after it
    - see _effective_payment_behavior below.

    CURE SEMANTICS (Phase 5, docs/adr/0010-cure-semantics-and-relapse.md):
    a cure pays exactly enough to eliminate every installment that is
    overdue AS OF THIS SNAPSHOT (due_date < month_end - the same strict
    boundary credlens.generation.snapshots.compute_dpd and
    derive_snapshot_row's past_due_amount already use), and NOTHING more -
    installments due later (due_date >= month_end) are left untouched,
    still scheduled, still able to be paid, missed, or become delinquent
    again in a later month. This is deliberately NOT "pay off the whole
    remaining balance" (that was Phase 4A/4B's behavior, and made cure
    always terminal - see the ADR for why that made delinquency relapse
    architecturally impossible). A cure that happens to be the contract's
    very last installment still naturally completes the loan - that is a
    legitimate coincidence, not a special case this function handles."""
    payable = [i for i in active_installments if due_dates[i.installment_id] <= month_end]
    if not payable:
        return Decimal("0"), "scheduled"

    has_backlog = any(due_dates[i.installment_id] < month_start for i in payable)
    total_open = sum((i.remaining_total for i in active_installments), Decimal("0"))

    if has_backlog:
        cure_chance = min(0.95, behavior.cure_probability_per_month * (0.5 + propensity))
        if rng.random() < cure_chance:
            overdue_now = [
                i for i in active_installments if due_dates[i.installment_id] < month_end
            ]
            cure_amount = sum((i.remaining_total for i in overdue_now), Decimal("0"))
            return cure_amount, "cure"
        return Decimal("0"), "cure"

    due_amount = sum((i.remaining_total for i in payable), Decimal("0"))
    scale = propensity / 0.75
    on_time_w = float(np.clip(behavior.on_time_probability * scale, 0.0, 0.97))
    partial_w = behavior.partial_payment_probability
    prepay_w = float(np.clip(behavior.prepayment_probability * scale, 0.0, 1.0))
    no_pay_w = max(0.01, 1 - on_time_w - partial_w - prepay_w)
    weights = np.array([on_time_w, partial_w, prepay_w, no_pay_w])
    weights = weights / weights.sum()
    outcome = rng.choice(_OUTCOMES, p=weights)

    if outcome == "on_time":
        amount = due_amount
        payment_type = "scheduled"
    elif outcome == "partial":
        fraction = Decimal(str(round(float(rng.uniform(0.3, 0.8)), 4)))
        amount = _quantize(due_amount * fraction)
        payment_type = "partial"
    elif outcome == "prepay":
        amount = total_open  # a full early payoff - distinct from cure, see docstring
        payment_type = "prepayment"
    else:
        amount = Decimal("0")
        payment_type = "scheduled"

    return min(amount, total_open), payment_type


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

    # A single bulk to_dict("records") + a plain-Python grouping pass, NOT
    # installments.groupby("contract_id") followed by one group.to_dict(...)
    # per contract: at sample/portfolio scale that is thousands of separate
    # pandas-level to_dict calls, each paying DataFrame construction
    # overhead for a handful of rows - profiled (cProfile, sample scale) at
    # ~9.2s of a ~34s run, the single largest hotspot found. installments
    # is already contiguous per contract_id in installment_number order (by
    # construction in schedules.generate_installments), so a plain pass
    # preserves the exact same per-contract ordering groupby would have -
    # see docs/performance_optimization.md.
    states: dict[str, _ContractState] = {}
    for inst_row in installments.to_dict("records"):
        contract_id = str(inst_row["contract_id"])
        installment = OpenInstallment(
            installment_id=str(inst_row["installment_id"]),
            remaining_principal=Decimal(str(inst_row["scheduled_principal"])),
            remaining_interest=Decimal(str(inst_row["scheduled_interest"])),
            remaining_fees=Decimal(str(inst_row["scheduled_fees"])),
        )
        state = states.get(contract_id)
        if state is None:
            state = _ContractState(open_installments=[])
            states[contract_id] = state
        state.open_installments.append(installment)

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
        behavior = _effective_payment_behavior(config, month_end)
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

            active = state.open_installments[state.head_index :]
            propensity = float(propensity_by_contract.get(contract_id, 0.75))
            amount, payment_type = _decide_payment_amount(
                active, due_dates, month_start, month_end, propensity, behavior, payments_rng
            )

            if amount > 0:
                # active is already in due-date order (installments.py
                # builds each contract's schedule in installment_number
                # order) and already pruned to remaining_total > 0 by the
                # head_index invariant - no re-sort/re-filter needed here.
                allocations = allocate_payment(amount, active)
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
                        "payment_type": payment_type,
                    }
                )
                by_id = {i.installment_id: i for i in active}
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
                                "payment_type": payment_type,
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

            # Advance the head pointer now that this month's mutations
            # (payment + its possible same-month reversal) are final - safe
            # per the invariant documented on _ContractState.head_index.
            # Every element skipped here has remaining_total == 0, so
            # re-deriving dpd/snapshot/write-off sums from the smaller
            # "active" view below is numerically identical to summing over
            # the full open_installments list, just cheaper.
            while (
                state.head_index < len(state.open_installments)
                and state.open_installments[state.head_index].remaining_total <= 0
            ):
                state.head_index += 1
            active = state.open_installments[state.head_index :]

            dpd = compute_dpd(active, due_dates, month_end)
            total_open = sum((i.remaining_total for i in active), Decimal("0"))

            if (
                total_open <= Decimal(str(config.tolerance.monetary_tolerance))
                and state.status != "charged_off"
            ):
                state.status = "settled"
                state.terminal_month = month_end
            elif should_write_off(dpd, config.write_off):
                principal = sum((i.remaining_principal for i in active), Decimal("0"))
                interest = sum((i.remaining_interest for i in active), Decimal("0"))
                fees = sum((i.remaining_fees for i in active), Decimal("0"))
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

            # derive_snapshot_row's own next_due_date computation is NOT
            # filtered by remaining_total (unlike dpd/past_due_amount,
            # which it computes safely from either view) - it deliberately
            # (if subtly) treats an installment due exactly THIS month_end
            # as still eligible for "next_due_date" even after this same
            # month's payment has just exhausted it (due_date >= month_end
            # is an inclusive boundary). Pruned "active" would silently
            # change that pre-existing behavior for same-day payoffs -
            # caught by re-running the sample scale and diffing every
            # snapshot cell against the pre-optimization output, not by
            # reasoning alone. Pass the full list here; every other field
            # this function computes is unaffected either way (exhausted
            # installments contribute exactly 0 to every sum).
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
                due_now = [i for i in active if due_dates[i.installment_id] <= month_end]
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
