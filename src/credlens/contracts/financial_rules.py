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
}
