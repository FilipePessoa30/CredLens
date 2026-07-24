"""Named business rules about relationships/cardinality across tables.

Every function has the same signature - `(tables, contract_name) ->
list[Finding]` - so validators.py can dispatch any business_rules[].code
uniformly, whether the rule needs one table or several. `tables` maps
contract name -> its loaded DataFrame; a rule that needs a table not
present in this validation run reports an `info` finding instead of
crashing (see reporting.missing_tables_finding).
"""

from __future__ import annotations

import pandas as pd

from credlens.contracts.reporting import Finding, missing_tables_finding

# Every rule function below has the signature
# `(tables: dict[str, pd.DataFrame], contract_name: str) -> list[Finding]`.


def single_final_decision(tables: dict[str, pd.DataFrame], contract_name: str) -> list[Finding]:
    decisions = tables.get("credit_decisions")
    if decisions is None:
        return [
            missing_tables_finding(contract_name, "single_final_decision", ["credit_decisions"])
        ]

    finals = decisions[decisions["is_final"].astype(str).str.lower() == "true"]
    counts = finals.groupby("application_id").size()
    offenders = counts[counts > 1]
    if offenders.empty:
        return []
    return [
        Finding(
            code="MULTIPLE_FINAL_DECISIONS",
            severity="error",
            contract=contract_name,
            column="application_id",
            message="Application(s) have more than one decision marked is_final=true.",
            count=len(offenders),
            total=int(decisions["application_id"].nunique()),
            examples=tuple(offenders.index.astype(str)[:5].tolist()),
        )
    ]


def contract_requires_approved_final_decision(
    tables: dict[str, pd.DataFrame], contract_name: str
) -> list[Finding]:
    decisions = tables.get("credit_decisions")
    contracts_df = tables.get("contracts")
    if decisions is None or contracts_df is None:
        return [
            missing_tables_finding(
                contract_name,
                "contract_requires_approved_final_decision",
                ["credit_decisions", "contracts"],
            )
        ]

    finals = decisions[decisions["is_final"].astype(str).str.lower() == "true"]
    approved_ids = set(finals.loc[finals["outcome"] == "approved", "application_id"])
    orphans = contracts_df[~contracts_df["application_id"].isin(approved_ids)]
    if orphans.empty:
        return []
    return [
        Finding(
            code="CONTRACT_WITHOUT_APPROVED_DECISION",
            severity="error",
            contract=contract_name,
            column="application_id",
            message=(
                "Contract(s) exist for an application with no final, approved decision - "
                "a rejected (or non-final) application can never have a contract."
            ),
            count=len(orphans),
            total=len(contracts_df),
            examples=tuple(orphans["contract_id"].astype(str).head(5).tolist()),
        )
    ]


def approval_requires_valid_policy(
    tables: dict[str, pd.DataFrame], contract_name: str
) -> list[Finding]:
    decisions = tables.get("credit_decisions")
    policies = tables.get("policy_versions")
    if decisions is None or policies is None:
        return [
            missing_tables_finding(
                contract_name,
                "approval_requires_valid_policy",
                ["credit_decisions", "policy_versions"],
            )
        ]

    merged = decisions.merge(policies, on="policy_version_id", how="left", suffixes=("", "_policy"))
    decision_ts = pd.to_datetime(merged["decision_timestamp"], errors="coerce", utc=True)
    effective_from = pd.to_datetime(merged["effective_from"], errors="coerce", utc=True)
    effective_to = pd.to_datetime(merged["effective_to"], errors="coerce", utc=True)

    missing_policy = merged["name"].isna()
    before_start = decision_ts < effective_from
    after_end = effective_to.notna() & (decision_ts >= effective_to)
    invalid = missing_policy | before_start | after_end

    count = int(invalid.sum())
    if not count:
        return []
    return [
        Finding(
            code="DECISION_POLICY_NOT_VALID_AT_DECISION_TIME",
            severity="error",
            contract=contract_name,
            column="policy_version_id",
            message=(
                "Decision references a policy version that was not valid at decision_timestamp."
            ),
            count=count,
            total=len(merged),
            examples=tuple(merged.loc[invalid, "decision_id"].astype(str).head(5).tolist()),
        )
    ]


def allocation_same_contract(tables: dict[str, pd.DataFrame], contract_name: str) -> list[Finding]:
    allocations = tables.get("payment_allocations")
    payments = tables.get("payments")
    installments = tables.get("installments")
    if allocations is None or payments is None or installments is None:
        return [
            missing_tables_finding(
                contract_name, "allocation_same_contract", ["payments", "installments"]
            )
        ]

    merged = allocations.merge(
        payments[["payment_id", "contract_id"]].rename(
            columns={"contract_id": "payment_contract_id"}
        ),
        on="payment_id",
        how="left",
    ).merge(
        installments[["installment_id", "contract_id"]].rename(
            columns={"contract_id": "installment_contract_id"}
        ),
        on="installment_id",
        how="left",
    )

    mismatched = (merged["contract_id"] != merged["payment_contract_id"]) | (
        merged["contract_id"] != merged["installment_contract_id"]
    )
    count = int(mismatched.sum())
    if not count:
        return []
    return [
        Finding(
            code="ALLOCATION_CROSSES_CONTRACTS",
            severity="error",
            contract=contract_name,
            column="contract_id",
            message=(
                "Allocation's contract_id does not match the referenced payment's and/or "
                "installment's contract_id - an allocation must never cross contracts."
            ),
            count=count,
            total=len(merged),
            examples=tuple(merged.loc[mismatched, "allocation_id"].astype(str).head(5).tolist()),
        )
    ]


def payment_allocation_not_exceed_payment(
    tables: dict[str, pd.DataFrame], contract_name: str
) -> list[Finding]:
    allocations = tables.get("payment_allocations")
    payments = tables.get("payments")
    if allocations is None or payments is None:
        return [
            missing_tables_finding(
                contract_name, "payment_allocation_not_exceed_payment", ["payments"]
            )
        ]

    allocated_total = pd.to_numeric(allocations["allocated_total"], errors="coerce")
    totals_by_payment = allocated_total.groupby(allocations["payment_id"]).sum()
    payment_amounts = pd.to_numeric(payments.set_index("payment_id")["amount"], errors="coerce")

    comparison = totals_by_payment.to_frame("allocated").join(
        payment_amounts.to_frame("amount"), how="left"
    )
    exceeded = comparison["allocated"] > comparison["amount"]
    count = int(exceeded.sum())
    if not count:
        return []
    return [
        Finding(
            code="ALLOCATION_EXCEEDS_PAYMENT",
            severity="error",
            contract=contract_name,
            column="payment_id",
            message="Sum of allocations for a payment exceeds that payment's amount.",
            count=count,
            total=len(comparison),
            examples=tuple(comparison.index[exceeded].astype(str)[:5].tolist()),
        )
    ]


RULES: dict[str, object] = {
    "single_final_decision": single_final_decision,
    "contract_requires_approved_final_decision": contract_requires_approved_final_decision,
    "approval_requires_valid_policy": approval_requires_valid_policy,
    "allocation_same_contract": allocation_same_contract,
    "payment_allocation_not_exceed_payment": payment_allocation_not_exceed_payment,
}
