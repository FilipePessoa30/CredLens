"""Named business rules about causal/temporal ordering.

Same `(tables, contract_name) -> list[Finding]` signature as
relational_rules.py - see that module's docstring.
"""

from __future__ import annotations

import pandas as pd

from credlens.contracts.reporting import Finding, missing_tables_finding


def decision_not_before_submission(
    tables: dict[str, pd.DataFrame], contract_name: str
) -> list[Finding]:
    applications = tables.get("applications")
    decisions = tables.get("credit_decisions")
    if applications is None or decisions is None:
        return [
            missing_tables_finding(
                contract_name,
                "decision_not_before_submission",
                ["applications", "credit_decisions"],
            )
        ]

    merged = decisions.merge(
        applications[["application_id", "submitted_at"]], on="application_id", how="left"
    )
    decision_ts = pd.to_datetime(merged["decision_timestamp"], errors="coerce", utc=True)
    submitted_ts = pd.to_datetime(merged["submitted_at"], errors="coerce", utc=True)
    violation = decision_ts < submitted_ts

    count = int(violation.sum())
    if not count:
        return []
    return [
        Finding(
            code="DECISION_BEFORE_SUBMISSION",
            severity="error",
            contract=contract_name,
            column="decision_timestamp",
            message="decision_timestamp is earlier than the application's submitted_at.",
            count=count,
            total=len(merged),
            examples=tuple(merged.loc[violation, "decision_id"].astype(str).head(5).tolist()),
        )
    ]


def contract_after_decision(tables: dict[str, pd.DataFrame], contract_name: str) -> list[Finding]:
    decisions = tables.get("credit_decisions")
    contracts_df = tables.get("contracts")
    if decisions is None or contracts_df is None:
        return [
            missing_tables_finding(
                contract_name, "contract_after_decision", ["credit_decisions", "contracts"]
            )
        ]

    finals = decisions[
        (decisions["is_final"].astype(str).str.lower() == "true")
        & (decisions["outcome"] == "approved")
    ]
    merged = contracts_df.merge(
        finals[["application_id", "decision_timestamp"]], on="application_id", how="left"
    )
    contract_ts = pd.to_datetime(merged["contract_date"], errors="coerce", utc=True)
    decision_ts = pd.to_datetime(merged["decision_timestamp"], errors="coerce", utc=True)
    violation = decision_ts.notna() & (contract_ts < decision_ts)

    count = int(violation.sum())
    if not count:
        return []
    return [
        Finding(
            code="CONTRACT_BEFORE_DECISION",
            severity="error",
            contract=contract_name,
            column="contract_date",
            message="contract_date is earlier than the approving decision's decision_timestamp.",
            count=count,
            total=len(merged),
            examples=tuple(merged.loc[violation, "contract_id"].astype(str).head(5).tolist()),
        )
    ]


def disbursement_not_before_contract(
    tables: dict[str, pd.DataFrame], contract_name: str
) -> list[Finding]:
    contracts_df = tables.get("contracts")
    if contracts_df is None:
        return [
            missing_tables_finding(contract_name, "disbursement_not_before_contract", ["contracts"])
        ]

    contract_ts = pd.to_datetime(contracts_df["contract_date"], errors="coerce", utc=True)
    disbursement_ts = pd.to_datetime(contracts_df["disbursement_date"], errors="coerce", utc=True)
    violation = disbursement_ts < contract_ts

    count = int(violation.sum())
    if not count:
        return []
    return [
        Finding(
            code="DISBURSEMENT_BEFORE_CONTRACT",
            severity="error",
            contract=contract_name,
            column="disbursement_date",
            message="disbursement_date is earlier than contract_date.",
            count=count,
            total=len(contracts_df),
            examples=tuple(contracts_df.loc[violation, "contract_id"].astype(str).head(5).tolist()),
        )
    ]


def write_off_not_before_contract(
    tables: dict[str, pd.DataFrame], contract_name: str
) -> list[Finding]:
    contracts_df = tables.get("contracts")
    write_offs = tables.get("write_off_events")
    if contracts_df is None or write_offs is None:
        return [
            missing_tables_finding(contract_name, "write_off_not_before_contract", ["contracts"])
        ]

    merged = write_offs.merge(
        contracts_df[["contract_id", "contract_date"]], on="contract_id", how="left"
    )
    write_off_ts = pd.to_datetime(merged["write_off_date"], errors="coerce", utc=True)
    contract_ts = pd.to_datetime(merged["contract_date"], errors="coerce", utc=True)
    violation = write_off_ts < contract_ts

    count = int(violation.sum())
    if not count:
        return []
    return [
        Finding(
            code="WRITE_OFF_BEFORE_CONTRACT",
            severity="error",
            contract=contract_name,
            column="write_off_date",
            message="write_off_date is earlier than the contract's own contract_date.",
            count=count,
            total=len(merged),
            examples=tuple(merged.loc[violation, "write_off_id"].astype(str).head(5).tolist()),
        )
    ]


def recovery_after_write_off(tables: dict[str, pd.DataFrame], contract_name: str) -> list[Finding]:
    write_offs = tables.get("write_off_events")
    recoveries = tables.get("recovery_events")
    if write_offs is None or recoveries is None:
        return [
            missing_tables_finding(contract_name, "recovery_after_write_off", ["write_off_events"])
        ]

    merged = recoveries.merge(
        write_offs[["write_off_id", "write_off_date"]], on="write_off_id", how="left"
    )
    recovery_ts = pd.to_datetime(merged["recovery_date"], errors="coerce", utc=True)
    write_off_ts = pd.to_datetime(merged["write_off_date"], errors="coerce", utc=True)
    violation = write_off_ts.isna() | (recovery_ts < write_off_ts)

    count = int(violation.sum())
    if not count:
        return []
    return [
        Finding(
            code="RECOVERY_BEFORE_WRITE_OFF",
            severity="error",
            contract=contract_name,
            column="recovery_date",
            message=(
                "recovery_date is earlier than the referenced write_off_events row's "
                "write_off_date (or that row does not exist)."
            ),
            count=count,
            total=len(merged),
            examples=tuple(merged.loc[violation, "recovery_id"].astype(str).head(5).tolist()),
        )
    ]


def reversal_references_earlier_payment(
    tables: dict[str, pd.DataFrame], contract_name: str
) -> list[Finding]:
    payments = tables.get("payments")
    if payments is None:
        return [missing_tables_finding(contract_name, "reversal_references_earlier_payment", [])]

    reversals = payments[payments["reversal_of_payment_id"].notna()]
    if reversals.empty:
        return []

    lookup = payments.set_index("payment_id")["payment_timestamp"]
    original_ts = pd.to_datetime(
        reversals["reversal_of_payment_id"].map(lookup), errors="coerce", utc=True
    )
    reversal_ts = pd.to_datetime(reversals["payment_timestamp"], errors="coerce", utc=True)
    violation = original_ts.isna() | (reversal_ts <= original_ts)

    count = int(violation.sum())
    if not count:
        return []
    return [
        Finding(
            code="REVERSAL_NOT_AFTER_ORIGINAL",
            severity="error",
            contract=contract_name,
            column="reversal_of_payment_id",
            message="Reversal does not reference an existing, earlier payment.",
            count=count,
            total=len(reversals),
            examples=tuple(reversals.loc[violation, "payment_id"].astype(str).head(5).tolist()),
        )
    ]


def policy_validity_window_not_inverted(
    tables: dict[str, pd.DataFrame], contract_name: str
) -> list[Finding]:
    policies = tables.get("policy_versions")
    if policies is None:
        return [missing_tables_finding(contract_name, "policy_validity_window_not_inverted", [])]

    effective_from = pd.to_datetime(policies["effective_from"], errors="coerce", utc=True)
    effective_to = pd.to_datetime(policies["effective_to"], errors="coerce", utc=True)
    violation = effective_to.notna() & (effective_to <= effective_from)

    count = int(violation.sum())
    if not count:
        return []
    return [
        Finding(
            code="POLICY_WINDOW_INVERTED",
            severity="error",
            contract=contract_name,
            column="effective_to",
            message="effective_to is not strictly after effective_from.",
            count=count,
            total=len(policies),
            examples=tuple(
                policies.loc[violation, "policy_version_id"].astype(str).head(5).tolist()
            ),
        )
    ]


def bcb_dates_strictly_increasing(
    tables: dict[str, pd.DataFrame], contract_name: str
) -> list[Finding]:
    """Regression check for the Phase 2 chunking-boundary bug: sorted
    observation dates must be strictly increasing (a duplicate or
    out-of-order date indicates a chunk merge went wrong).
    """
    df = tables.get(contract_name)
    if df is None or "data" not in df.columns:
        return [missing_tables_finding(contract_name, "bcb_dates_strictly_increasing", [])]

    dates = pd.to_datetime(df["data"], format="%d/%m/%Y", errors="coerce")
    sorted_dates = dates.sort_values()
    non_increasing = sorted_dates.diff().dt.days <= 0
    non_increasing.iloc[0] = False  # first element has no prior element to compare against

    count = int(non_increasing.sum())
    if not count:
        return []
    return [
        Finding(
            code="BCB_DATES_NOT_STRICTLY_INCREASING",
            severity="error",
            contract=contract_name,
            column="data",
            message=(
                "Observation dates are not strictly increasing once sorted - a duplicate "
                "or misordered date is present."
            ),
            count=count,
            total=len(df),
            examples=tuple(sorted_dates[non_increasing].dt.strftime("%d/%m/%Y").head(5).tolist()),
        )
    ]


_TERMINAL_CONTRACT_STATUSES = ("settled", "closed", "charged_off")


def no_snapshot_after_terminal_status(
    tables: dict[str, pd.DataFrame], contract_name: str
) -> list[Finding]:
    """Phase 4A fix: once a contract's status is first observed as terminal
    (settled/closed/charged_off) in a snapshot, no later snapshot_date may
    exist for that contract.

    This is the retention rule that replaces the Phase 3 fixture's
    DPD=999 sentinel: rather than needing a magic "frozen/undefined DPD"
    value for months after write-off, generation simply stops producing
    snapshot rows once a contract reaches a terminal state - the terminal
    month's own snapshot (with a real, ledger-derived DPD) is the last
    one. See docs/temporal_semantics.md and docs/metric_semantics.md.
    """
    df = tables.get(contract_name)
    if df is None:
        return [missing_tables_finding(contract_name, "no_snapshot_after_terminal_status", [])]

    snapshot_dates = pd.to_datetime(df["snapshot_date"], errors="coerce", utc=True)
    is_terminal = df["status"].isin(_TERMINAL_CONTRACT_STATUSES)

    terminal_dates = snapshot_dates.where(is_terminal)
    first_terminal_by_contract = terminal_dates.groupby(df["contract_id"]).transform("min")
    violation = first_terminal_by_contract.notna() & (snapshot_dates > first_terminal_by_contract)

    count = int(violation.sum())
    if not count:
        return []
    return [
        Finding(
            code="SNAPSHOT_AFTER_TERMINAL_STATUS",
            severity="error",
            contract=contract_name,
            column="snapshot_date",
            message=(
                "A snapshot exists for this contract after its status was already "
                "observed as terminal (settled/closed/charged_off) in an earlier "
                "snapshot - no further monthly snapshots should be generated once "
                "a contract reaches a terminal state."
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


RULES: dict[str, object] = {
    "decision_not_before_submission": decision_not_before_submission,
    "contract_after_decision": contract_after_decision,
    "disbursement_not_before_contract": disbursement_not_before_contract,
    "write_off_not_before_contract": write_off_not_before_contract,
    "recovery_after_write_off": recovery_after_write_off,
    "reversal_references_earlier_payment": reversal_references_earlier_payment,
    "policy_validity_window_not_inverted": policy_validity_window_not_inverted,
    "bcb_dates_strictly_increasing": bcb_dates_strictly_increasing,
    "no_snapshot_after_terminal_status": no_snapshot_after_terminal_status,
}
