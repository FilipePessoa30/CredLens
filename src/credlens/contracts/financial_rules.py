"""Named business rules about financial reconciliation and monotonicity.

Same `(tables, contract_name) -> list[Finding]` signature as
relational_rules.py - see that module's docstring.
"""

from __future__ import annotations

from dataclasses import replace

import pandas as pd

from credlens.contracts.reporting import Finding, missing_tables_finding

_RECONCILIATION_TOLERANCE = 0.01

# CredLens's own DPD-bucket convention (see docs/metric_semantics.md) -
# not a claimed regulatory standard. Bucket boundaries are inclusive on
# both ends; a DPD of exactly 30 belongs to "30-59", matching the
# documented convention.
_DPD_BUCKET_EDGES = [-1, 0, 29, 59, 89, float("inf")]
_DPD_BUCKET_LABELS = ["current", "1-29", "30-59", "60-89", "90+"]


def _reconciled(total: pd.Series, *parts: pd.Series) -> pd.Series:
    total_numeric = pd.to_numeric(total, errors="coerce")
    summed = sum(pd.to_numeric(part, errors="coerce") for part in parts)
    return (total_numeric - summed).abs() > _RECONCILIATION_TOLERANCE


def installment_total_reconciled(
    tables: dict[str, pd.DataFrame], contract_name: str
) -> list[Finding]:
    df = tables.get(contract_name)
    if df is None:
        return [missing_tables_finding(contract_name, "installment_total_reconciled", [])]

    violation = _reconciled(
        df["scheduled_total"],
        df["scheduled_principal"],
        df["scheduled_interest"],
        df["scheduled_fees"],
    )
    count = int(violation.sum())
    if not count:
        return []
    return [
        Finding(
            code="INSTALLMENT_TOTAL_NOT_RECONCILED",
            severity="error",
            contract=contract_name,
            column="scheduled_total",
            message="scheduled_total does not equal principal + interest + fees.",
            count=count,
            total=len(df),
            examples=tuple(df.loc[violation, "installment_id"].astype(str).head(5).tolist()),
        )
    ]


def allocation_total_reconciled(
    tables: dict[str, pd.DataFrame], contract_name: str
) -> list[Finding]:
    df = tables.get(contract_name)
    if df is None:
        return [missing_tables_finding(contract_name, "allocation_total_reconciled", [])]

    violation = _reconciled(
        df["allocated_total"],
        df["allocated_principal"],
        df["allocated_interest"],
        df["allocated_fees"],
    )
    count = int(violation.sum())
    if not count:
        return []
    return [
        Finding(
            code="ALLOCATION_TOTAL_NOT_RECONCILED",
            severity="error",
            contract=contract_name,
            column="allocated_total",
            message="allocated_total does not equal allocated principal + interest + fees.",
            count=count,
            total=len(df),
            examples=tuple(df.loc[violation, "allocation_id"].astype(str).head(5).tolist()),
        )
    ]


def allocation_amount_not_negative(
    tables: dict[str, pd.DataFrame], contract_name: str
) -> list[Finding]:
    df = tables.get(contract_name)
    if df is None:
        return [missing_tables_finding(contract_name, "allocation_amount_not_negative", [])]

    columns = ["allocated_principal", "allocated_interest", "allocated_fees", "allocated_total"]
    numeric = df[columns].apply(pd.to_numeric, errors="coerce")
    violation = (numeric < 0).any(axis=1)

    count = int(violation.sum())
    if not count:
        return []
    return [
        Finding(
            code="NEGATIVE_ALLOCATION_AMOUNT",
            severity="error",
            contract=contract_name,
            column=",".join(columns),
            message="Allocation row has a negative principal/interest/fees/total component.",
            count=count,
            total=len(df),
            examples=tuple(df.loc[violation, "allocation_id"].astype(str).head(5).tolist()),
        )
    ]


def write_off_amount_reconciled(
    tables: dict[str, pd.DataFrame], contract_name: str
) -> list[Finding]:
    df = tables.get(contract_name)
    if df is None:
        return [missing_tables_finding(contract_name, "write_off_amount_reconciled", [])]

    violation = _reconciled(df["amount"], df["principal"], df["interest"], df["fees"])
    count = int(violation.sum())
    if not count:
        return []
    return [
        Finding(
            code="WRITE_OFF_AMOUNT_NOT_RECONCILED",
            severity="error",
            contract=contract_name,
            column="amount",
            message="amount does not equal principal + interest + fees.",
            count=count,
            total=len(df),
            examples=tuple(df.loc[violation, "write_off_id"].astype(str).head(5).tolist()),
        )
    ]


def total_balance_reconciled(tables: dict[str, pd.DataFrame], contract_name: str) -> list[Finding]:
    df = tables.get(contract_name)
    if df is None:
        return [missing_tables_finding(contract_name, "total_balance_reconciled", [])]

    violation = _reconciled(
        df["total_balance"],
        df["outstanding_principal"],
        df["outstanding_interest"],
        df["outstanding_fees"],
    )
    count = int(violation.sum())
    if not count:
        return []
    return [
        Finding(
            code="TOTAL_BALANCE_NOT_RECONCILED",
            severity="error",
            contract=contract_name,
            column="total_balance",
            message="total_balance does not equal outstanding principal + interest + fees.",
            count=count,
            total=len(df),
            examples=tuple(
                df.loc[violation, ["contract_id", "snapshot_date"]]
                .astype(str)
                .agg("@".join, axis=1)
                .head(5)
                .tolist()
            ),
        )
    ]


def dpd_matches_bucket(tables: dict[str, pd.DataFrame], contract_name: str) -> list[Finding]:
    df = tables.get(contract_name)
    if df is None:
        return [missing_tables_finding(contract_name, "dpd_matches_bucket", [])]

    dpd = pd.to_numeric(df["dpd"], errors="coerce")
    expected = pd.cut(dpd, bins=_DPD_BUCKET_EDGES, labels=_DPD_BUCKET_LABELS)
    violation = expected.astype(str) != df["delinquency_bucket"].astype(str)

    count = int(violation.sum())
    if not count:
        return []
    return [
        Finding(
            code="DPD_BUCKET_MISMATCH",
            severity="error",
            contract=contract_name,
            column="delinquency_bucket",
            message=(
                "delinquency_bucket does not match dpd under the CredLens bucket convention "
                "(docs/metric_semantics.md)."
            ),
            count=count,
            total=len(df),
            examples=tuple(
                df.loc[violation, ["contract_id", "snapshot_date"]]
                .astype(str)
                .agg("@".join, axis=1)
                .head(5)
                .tolist()
            ),
        )
    ]


def _cumulative_non_decreasing(
    df: pd.DataFrame, contract_name: str, column: str, code: str
) -> list[Finding]:
    ordered = df.sort_values(["contract_id", "snapshot_date"])
    values = pd.to_numeric(ordered[column], errors="coerce")
    same_contract = ordered["contract_id"] == ordered["contract_id"].shift()
    decreased = same_contract & (values < values.shift())

    count = int(decreased.sum())
    if not count:
        return []
    return [
        Finding(
            code=code,
            severity="error",
            contract=contract_name,
            column=column,
            message=(
                f"{column} decreased month-over-month for the same contract "
                "without a documented reversal."
            ),
            count=count,
            total=len(ordered),
            examples=tuple(
                ordered.loc[decreased, ["contract_id", "snapshot_date"]]
                .astype(str)
                .agg("@".join, axis=1)
                .head(5)
                .tolist()
            ),
        )
    ]


def cumulative_paid_non_decreasing(
    tables: dict[str, pd.DataFrame], contract_name: str
) -> list[Finding]:
    df = tables.get(contract_name)
    if df is None:
        return [missing_tables_finding(contract_name, "cumulative_paid_non_decreasing", [])]
    findings = _cumulative_non_decreasing(
        df, contract_name, "cumulative_paid", "CUMULATIVE_PAID_DECREASED"
    )
    # Declared as `warning` severity in the contract (a documented reversal
    # is a valid exception) - downgrade here to match.
    return [f if f.severity != "error" else _as_warning(f) for f in findings]


def cumulative_write_off_non_decreasing(
    tables: dict[str, pd.DataFrame], contract_name: str
) -> list[Finding]:
    df = tables.get(contract_name)
    if df is None:
        return [missing_tables_finding(contract_name, "cumulative_write_off_non_decreasing", [])]
    return _cumulative_non_decreasing(
        df, contract_name, "cumulative_write_off", "CUMULATIVE_WRITE_OFF_DECREASED"
    )


def _as_warning(finding: Finding) -> Finding:
    return replace(finding, severity="warning")


def promise_fields_require_promise_flag(
    tables: dict[str, pd.DataFrame], contract_name: str
) -> list[Finding]:
    df = tables.get(contract_name)
    if df is None:
        return [missing_tables_finding(contract_name, "promise_fields_require_promise_flag", [])]

    promised = df["promise_to_pay"].astype(str).str.lower() == "true"
    has_amount = df["promised_amount"].notna()
    has_date = df["promised_date"].notna()

    violation = (promised & (~has_amount | ~has_date)) | (~promised & (has_amount | has_date))
    count = int(violation.sum())
    if not count:
        return []
    return [
        Finding(
            code="PROMISE_FIELDS_INCONSISTENT",
            severity="error",
            contract=contract_name,
            column="promise_to_pay",
            message="promised_amount/promised_date must be set if and only if promise_to_pay=true.",
            count=count,
            total=len(df),
            examples=tuple(df.loc[violation, "collection_event_id"].astype(str).head(5).tolist()),
        )
    ]


def _ledger_reconciliation(tables: dict[str, pd.DataFrame]) -> pd.DataFrame | None:
    """Independently reconstruct, from installments/payments/allocations/
    write_off_events alone, what account_monthly_snapshots *should* say for
    every (contract_id, snapshot_date) pair - the Phase 4A fix for the
    Phase 3 gap "cumulative_paid is not reconciled against payments"
    (docs/business_rules.md, ADR events/snapshots hybrid).

    Formula (see docs/metric_semantics.md "DPD" and this module's docstring
    in docs/data_contracts.md for the full write-up):
      - A payment "counts" only once settled (status=settled) and only as
        of its settlement_date; a reversal (reversal_of_payment_id set)
        subtracts back out what it reverses, from its own settlement_date.
      - expected_cumulative_paid(contract, snapshot_date) = sum, over every
        installment of that contract, of the installment's own as-of-date
        cumulative allocated total (clipped so a single installment can
        never contribute more than its scheduled_total).
      - expected_dpd(contract, snapshot_date) = the largest
        (snapshot_date - due_date) in days among installments whose
        as-of-date outstanding balance is still positive - matches
        docs/metric_semantics.md's DPD convention exactly. Write-off does
        not zero this out: DPD is a fact about payment timeliness, not
        about the accounting treatment applied afterward.
      - expected_write_off(contract, snapshot_date) = sum of
        write_off_events.amount for that contract with write_off_date <=
        snapshot_date.
      - expected_total_balance(contract, snapshot_date) = max(0, sum of
        each installment's remaining scheduled_total not yet paid) minus
        expected_write_off, floored at 0 - once a contract is written off,
        its remaining ledger balance is carried as write-off, not balance.

    This does not independently re-derive the principal/interest/fees
    split of the balance (that internal consistency is
    total_balance_reconciled's job) - only the total.

    Returns None if the tables needed are not all present.
    """
    snapshots = tables.get("account_monthly_snapshots")
    installments = tables.get("installments")
    payments = tables.get("payments")
    allocations = tables.get("payment_allocations")
    if snapshots is None or installments is None or payments is None or allocations is None:
        return None

    snap = snapshots[["contract_id", "snapshot_date"]].copy()
    snap["snapshot_date"] = pd.to_datetime(snap["snapshot_date"], errors="coerce", utc=True)

    inst = installments[["installment_id", "contract_id", "due_date", "scheduled_total"]].copy()
    inst["installment_id"] = inst["installment_id"].astype(str)
    inst["due_date"] = pd.to_datetime(inst["due_date"], errors="coerce", utc=True)
    inst["scheduled_total"] = pd.to_numeric(inst["scheduled_total"], errors="coerce")

    settled = payments[payments["status"] == "settled"][
        ["payment_id", "settlement_date", "reversal_of_payment_id"]
    ].copy()
    settled["settlement_date"] = pd.to_datetime(
        settled["settlement_date"], errors="coerce", utc=True
    )

    alloc = allocations[["payment_id", "installment_id", "allocated_total"]].copy()
    # Explicit str cast (not just relying on the source dtype) so an empty
    # payments/allocations table (no payments made yet on this contract)
    # still produces a merge-compatible dtype below, instead of pandas
    # inferring float64 for an all-empty object column.
    alloc["installment_id"] = alloc["installment_id"].astype(str)
    alloc["allocated_total"] = pd.to_numeric(alloc["allocated_total"], errors="coerce")

    events = alloc.merge(settled, on="payment_id", how="inner").dropna(subset=["settlement_date"])
    is_reversal = events["reversal_of_payment_id"].notna()
    events["signed_total"] = events["allocated_total"].where(
        ~is_reversal, -events["allocated_total"]
    )
    events = events.sort_values("settlement_date")
    events["cumulative_paid"] = events.groupby("installment_id")["signed_total"].cumsum()

    # Every (contract, snapshot_date, installment) combination for that contract.
    cross = snap.merge(inst, on="contract_id", how="left")
    cross = cross.sort_values("snapshot_date")
    events_for_merge = events[["installment_id", "settlement_date", "cumulative_paid"]].sort_values(
        "settlement_date"
    )
    merged = pd.merge_asof(
        cross,
        events_for_merge,
        left_on="snapshot_date",
        right_on="settlement_date",
        by="installment_id",
        direction="backward",
    )
    merged["cumulative_paid"] = merged["cumulative_paid"].fillna(0.0).clip(lower=0)
    merged["cumulative_paid"] = merged[["cumulative_paid", "scheduled_total"]].min(axis=1)
    merged["outstanding"] = (merged["scheduled_total"] - merged["cumulative_paid"]).clip(lower=0)
    merged["days_overdue"] = (merged["snapshot_date"] - merged["due_date"]).dt.days

    # Only an installment already past its own due_date can contribute to
    # DPD - a not-yet-due installment with a positive outstanding balance
    # (the normal case for any future installment) must never count,
    # matching docs/metric_semantics.md's "due_date < snapshot_date" clause.
    overdue = merged[
        (merged["outstanding"] > _RECONCILIATION_TOLERANCE)
        & (merged["due_date"] < merged["snapshot_date"])
    ]
    expected_dpd = (
        overdue.groupby(["contract_id", "snapshot_date"])["days_overdue"]
        .max()
        .rename("expected_dpd")
    )
    expected_cumulative_paid = (
        merged.groupby(["contract_id", "snapshot_date"])["cumulative_paid"]
        .sum()
        .rename("expected_cumulative_paid")
    )
    expected_remaining = (
        merged.groupby(["contract_id", "snapshot_date"])["outstanding"]
        .sum()
        .rename("expected_remaining_before_write_off")
    )

    write_offs = tables.get("write_off_events")
    if write_offs is not None and not write_offs.empty:
        wo = write_offs[["contract_id", "write_off_date", "amount"]].copy()
        wo["write_off_date"] = pd.to_datetime(wo["write_off_date"], errors="coerce", utc=True)
        wo["amount"] = pd.to_numeric(wo["amount"], errors="coerce")
        wo_events = wo.sort_values("write_off_date")
        wo_events["cumulative_write_off"] = wo_events.groupby("contract_id")["amount"].cumsum()
        wo_asof = pd.merge_asof(
            snap.sort_values("snapshot_date"),
            wo_events[["contract_id", "write_off_date", "cumulative_write_off"]].sort_values(
                "write_off_date"
            ),
            left_on="snapshot_date",
            right_on="write_off_date",
            by="contract_id",
            direction="backward",
        )
        expected_write_off = wo_asof.set_index(["contract_id", "snapshot_date"])[
            "cumulative_write_off"
        ].fillna(0.0)
    else:
        expected_write_off = pd.Series(
            0.0, index=snap.set_index(["contract_id", "snapshot_date"]).index
        )
    expected_write_off = expected_write_off.rename("expected_write_off")

    result = (
        snap.set_index(["contract_id", "snapshot_date"])
        .join(expected_dpd)
        .join(expected_cumulative_paid)
        .join(expected_remaining)
        .join(expected_write_off)
        .reset_index()
    )
    result["expected_dpd"] = result["expected_dpd"].fillna(0.0)
    result["expected_cumulative_paid"] = result["expected_cumulative_paid"].fillna(0.0)
    result["expected_remaining_before_write_off"] = result[
        "expected_remaining_before_write_off"
    ].fillna(0.0)
    result["expected_write_off"] = result["expected_write_off"].fillna(0.0)
    result["expected_total_balance"] = (
        result["expected_remaining_before_write_off"] - result["expected_write_off"]
    ).clip(lower=0)
    return result


def _merge_with_reconciliation(df: pd.DataFrame, reconciled: pd.DataFrame) -> pd.DataFrame:
    """Join a snapshots table (with a string/object snapshot_date, as read
    from CSV/JSON) against `_ledger_reconciliation`'s output (which uses a
    tz-aware datetime snapshot_date) - normalizes both sides to the same
    dtype first so the merge key actually matches."""
    left = df.copy()
    left["_snapshot_date_key"] = pd.to_datetime(left["snapshot_date"], errors="coerce", utc=True)
    right = reconciled.rename(columns={"snapshot_date": "_snapshot_date_key"})
    return left.merge(right, on=["contract_id", "_snapshot_date_key"], how="left")


def snapshot_cumulative_paid_reconciled(
    tables: dict[str, pd.DataFrame], contract_name: str
) -> list[Finding]:
    df = tables.get(contract_name)
    reconciled = _ledger_reconciliation(tables)
    if df is None or reconciled is None:
        return [
            missing_tables_finding(
                contract_name,
                "snapshot_cumulative_paid_reconciled",
                ["installments", "payments", "payment_allocations"],
            )
        ]

    merged = _merge_with_reconciliation(df, reconciled)
    actual = pd.to_numeric(merged["cumulative_paid"], errors="coerce")
    violation = (actual - merged["expected_cumulative_paid"]).abs() > _RECONCILIATION_TOLERANCE

    count = int(violation.sum())
    if not count:
        return []
    return [
        Finding(
            code="SNAPSHOT_CUMULATIVE_PAID_MISMATCH",
            severity="error",
            contract=contract_name,
            column="cumulative_paid",
            message=(
                "cumulative_paid does not match the amount actually settled and "
                "allocated toward this contract's installments (net of reversals) "
                "as of snapshot_date."
            ),
            count=count,
            total=len(merged),
            examples=tuple(
                merged.loc[violation, ["contract_id", "snapshot_date"]]
                .astype(str)
                .agg("@".join, axis=1)
                .head(5)
                .tolist()
            ),
        )
    ]


def snapshot_balance_reconciled_with_ledger(
    tables: dict[str, pd.DataFrame], contract_name: str
) -> list[Finding]:
    df = tables.get(contract_name)
    reconciled = _ledger_reconciliation(tables)
    if df is None or reconciled is None:
        return [
            missing_tables_finding(
                contract_name,
                "snapshot_balance_reconciled_with_ledger",
                ["installments", "payments", "payment_allocations"],
            )
        ]

    merged = _merge_with_reconciliation(df, reconciled)
    actual = pd.to_numeric(merged["total_balance"], errors="coerce")
    violation = (actual - merged["expected_total_balance"]).abs() > _RECONCILIATION_TOLERANCE

    count = int(violation.sum())
    if not count:
        return []
    return [
        Finding(
            code="SNAPSHOT_BALANCE_RECONCILIATION_FAILED",
            severity="error",
            contract=contract_name,
            column="total_balance",
            message=(
                "total_balance does not match the remaining scheduled amount "
                "implied by installments/payments/allocations, net of any "
                "write-off, as of snapshot_date."
            ),
            count=count,
            total=len(merged),
            examples=tuple(
                merged.loc[violation, ["contract_id", "snapshot_date"]]
                .astype(str)
                .agg("@".join, axis=1)
                .head(5)
                .tolist()
            ),
        )
    ]


def snapshot_write_off_reconciled(
    tables: dict[str, pd.DataFrame], contract_name: str
) -> list[Finding]:
    df = tables.get(contract_name)
    reconciled = _ledger_reconciliation(tables)
    if df is None or reconciled is None:
        return [
            missing_tables_finding(
                contract_name,
                "snapshot_write_off_reconciled",
                ["installments", "payments", "payment_allocations"],
            )
        ]

    merged = _merge_with_reconciliation(df, reconciled)
    actual = pd.to_numeric(merged["cumulative_write_off"], errors="coerce")
    violation = (actual - merged["expected_write_off"]).abs() > _RECONCILIATION_TOLERANCE

    count = int(violation.sum())
    if not count:
        return []
    return [
        Finding(
            code="SNAPSHOT_WRITE_OFF_MISMATCH",
            severity="error",
            contract=contract_name,
            column="cumulative_write_off",
            message=(
                "cumulative_write_off does not match the sum of write_off_events "
                "amounts for this contract with write_off_date <= snapshot_date."
            ),
            count=count,
            total=len(merged),
            examples=tuple(
                merged.loc[violation, ["contract_id", "snapshot_date"]]
                .astype(str)
                .agg("@".join, axis=1)
                .head(5)
                .tolist()
            ),
        )
    ]


def snapshot_dpd_reconciled_with_installments(
    tables: dict[str, pd.DataFrame], contract_name: str
) -> list[Finding]:
    """The Phase 4A fix that structurally rejects a fabricated/sentinel DPD
    (e.g. the Phase 3 fixture's DPD=999): dpd must equal the largest
    (snapshot_date - due_date) among installments still carrying a
    positive outstanding balance as of snapshot_date - never a value
    inconsistent with the real ledger chronology."""
    df = tables.get(contract_name)
    reconciled = _ledger_reconciliation(tables)
    if df is None or reconciled is None:
        return [
            missing_tables_finding(
                contract_name,
                "snapshot_dpd_reconciled_with_installments",
                ["installments", "payments", "payment_allocations"],
            )
        ]

    merged = _merge_with_reconciliation(df, reconciled)
    actual = pd.to_numeric(merged["dpd"], errors="coerce")
    violation = actual != merged["expected_dpd"]

    count = int(violation.sum())
    if not count:
        return []
    return [
        Finding(
            code="SNAPSHOT_DPD_MISMATCH",
            severity="error",
            contract=contract_name,
            column="dpd",
            message=(
                "dpd does not equal the largest (snapshot_date - due_date) among "
                "installments with a positive outstanding balance as of "
                "snapshot_date, per the CredLens DPD convention "
                "(docs/metric_semantics.md) - a sentinel or otherwise fabricated "
                "value is not accepted."
            ),
            count=count,
            total=len(merged),
            examples=tuple(
                merged.loc[violation, ["contract_id", "snapshot_date"]]
                .astype(str)
                .agg("@".join, axis=1)
                .head(5)
                .tolist()
            ),
        )
    ]


RULES: dict[str, object] = {
    "installment_total_reconciled": installment_total_reconciled,
    "allocation_total_reconciled": allocation_total_reconciled,
    "allocation_amount_not_negative": allocation_amount_not_negative,
    "write_off_amount_reconciled": write_off_amount_reconciled,
    "total_balance_reconciled": total_balance_reconciled,
    "dpd_matches_bucket": dpd_matches_bucket,
    "cumulative_paid_non_decreasing": cumulative_paid_non_decreasing,
    "cumulative_write_off_non_decreasing": cumulative_write_off_non_decreasing,
    "promise_fields_require_promise_flag": promise_fields_require_promise_flag,
    "snapshot_cumulative_paid_reconciled": snapshot_cumulative_paid_reconciled,
    "snapshot_balance_reconciled_with_ledger": snapshot_balance_reconciled_with_ledger,
    "snapshot_write_off_reconciled": snapshot_write_off_reconciled,
    "snapshot_dpd_reconciled_with_installments": snapshot_dpd_reconciled_with_installments,
}
