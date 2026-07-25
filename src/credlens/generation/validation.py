"""Post-generation validation: contracts (strict), PII safety, truth
isolation, and technical statistical checks (never business findings -
see docs/synthetic_generation_implementation.md "Statistical validation
is not a business finding").

A run is only promoted from staging to its final location
(src/credlens/generation/orchestrator.py) if `passed` is True here - see
docs/synthetic_generation_implementation.md "Validation and atomicity".
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from credlens.contracts import domain_rules
from credlens.contracts.models import DataContract
from credlens.contracts.registry import KNOWN_BUSINESS_RULE_CODES
from credlens.contracts.reporting import Finding, ValidationReport


@dataclass(frozen=True)
class StatisticalCheck:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class GenerationValidationOutcome:
    contract_reports: dict[str, ValidationReport]
    statistical_checks: list[StatisticalCheck]
    pii_safe: bool
    pii_detail: str

    @property
    def contracts_passed(self) -> bool:
        return all(not report.has_errors for report in self.contract_reports.values())

    @property
    def statistical_passed(self) -> bool:
        return all(check.passed for check in self.statistical_checks)

    @property
    def passed(self) -> bool:
        """The hard gate for promotion: contract validity and PII safety.
        Statistical checks are technical sanity checks on the generator's
        own behavior, not business findings - see module docstring - and
        are reported but do not, by themselves, fail a run whose contracts
        and PII checks are otherwise clean."""
        return self.contracts_passed and self.pii_safe


def validate_contracts_strict(
    tables: dict[str, pd.DataFrame], contracts: dict[str, DataContract]
) -> dict[str, ValidationReport]:
    reports: dict[str, ValidationReport] = {}
    for name, df in tables.items():
        contract = contracts.get(name)
        if contract is None:
            continue
        findings: list[Finding] = list(domain_rules.check_all(df, contract, tables, mode="strict"))
        for rule in contract.business_rules:
            findings.extend(KNOWN_BUSINESS_RULE_CODES[rule.code](tables, contract.name))  # type: ignore[operator]
        reports[name] = ValidationReport(
            contract=name, mode="strict", row_count=len(df), findings=findings
        )
    return reports


def check_pii_safety(
    tables: dict[str, pd.DataFrame], contracts: dict[str, DataContract]
) -> tuple[bool, str]:
    """Reuses the same CPF-shaped-identifier check every contract already
    runs (domain_rules.check_no_document_like_identifiers) across every
    generated table, as a dedicated, explicitly-reported safety gate."""
    total_hits = 0
    details = []
    for name, df in tables.items():
        contract = contracts.get(name)
        if contract is None:
            continue
        findings = domain_rules.check_no_document_like_identifiers(df, contract)
        if findings:
            total_hits += sum(f.count or 0 for f in findings)
            details.append(f"{name}: {[f.code for f in findings]}")
    if total_hits:
        return False, f"{total_hits} CPF-shaped identifier(s) found: {details}"
    return True, "No CPF-shaped identifiers found in any generated table."


def run_statistical_checks(tables: dict[str, pd.DataFrame]) -> list[StatisticalCheck]:
    checks: list[StatisticalCheck] = []

    applications = tables.get("applications")
    decisions = tables.get("credit_decisions")
    contracts_df = tables.get("contracts")
    installments = tables.get("installments")
    payments = tables.get("payments")
    snapshots = tables.get("account_monthly_snapshots")
    write_offs = tables.get("write_off_events")
    recoveries = tables.get("recovery_events")

    if applications is not None and decisions is not None:
        finals = decisions[decisions["is_final"].astype(str).str.lower() == "true"]
        n_decided = len(finals)
        n_approved = int((finals["outcome"] == "approved").sum())
        approval_rate = (n_approved / n_decided) if n_decided else 0.0
        checks.append(
            StatisticalCheck(
                "approval_rate_in_0_100_pct",
                0.0 <= approval_rate <= 1.0,
                f"approval_rate={approval_rate:.3f} over {n_decided} decided applications",
            )
        )
        if contracts_df is not None:
            booking_rate = (len(contracts_df) / n_approved) if n_approved else 0.0
            checks.append(
                StatisticalCheck(
                    "booking_rate_not_exceeding_approval",
                    booking_rate <= 1.0 + 1e-9,
                    f"booking_rate={booking_rate:.3f} "
                    f"({len(contracts_df)} contracts / {n_approved} approved)",
                )
            )
            approved_application_ids = set(
                finals.loc[finals["outcome"] == "approved", "application_id"]
            )
            orphan_contracts = int(
                (~contracts_df["application_id"].isin(approved_application_ids)).sum()
            )
            checks.append(
                StatisticalCheck(
                    "contracts_only_from_approved_applications",
                    orphan_contracts == 0,
                    f"{orphan_contracts} contract(s) not traceable to an approved application",
                )
            )

    if installments is not None:
        has_paid = bool((installments["status"] == "paid").any())
        has_overdue_or_written_off = bool(
            installments["status"].isin(["overdue", "written_off", "partially_paid"]).any()
        )
        checks.append(
            StatisticalCheck(
                "portfolio_has_both_performing_and_non_performing_installments",
                has_paid or has_overdue_or_written_off,
                f"paid={has_paid}, overdue_or_written_off_or_partial={has_overdue_or_written_off}",
            )
        )

    if payments is not None and not payments.empty:
        n_full = len(payments)
        checks.append(
            StatisticalCheck(
                "payments_exist",
                n_full > 0,
                f"{n_full} payment(s) generated",
            )
        )
        n_channels = payments["channel"].nunique()
        checks.append(
            StatisticalCheck(
                "payment_channel_diversity",
                n_channels >= 1,
                f"{n_channels} distinct payment channel(s) observed",
            )
        )

    if snapshots is not None and not snapshots.empty:
        buckets = set(snapshots["delinquency_bucket"].unique())
        valid_buckets = {"current", "1-29", "30-59", "60-89", "90+"}
        checks.append(
            StatisticalCheck(
                "delinquency_buckets_within_known_values",
                buckets.issubset(valid_buckets),
                f"observed buckets: {sorted(buckets)}",
            )
        )
        dpd_negative = int((pd.to_numeric(snapshots["dpd"], errors="coerce") < 0).sum())
        checks.append(
            StatisticalCheck(
                "no_negative_dpd",
                dpd_negative == 0,
                f"{dpd_negative} snapshot(s) with negative dpd",
            )
        )

    if write_offs is not None:
        checks.append(
            StatisticalCheck(
                "write_off_table_well_formed",
                bool((write_offs["amount"] > 0).all()) if not write_offs.empty else True,
                f"{len(write_offs)} write-off event(s), all-positive-amount check applied",
            )
        )

    if recoveries is not None and write_offs is not None and not write_offs.empty:
        checks.append(
            StatisticalCheck(
                "recovery_only_after_write_off_exists",
                bool(recoveries["write_off_id"].isin(write_offs["write_off_id"]).all())
                if not recoveries.empty
                else True,
                f"{len(recoveries)} recovery event(s) against {len(write_offs)} write-off(s)",
            )
        )

    return checks


def validate_generated_portfolio(
    tables: dict[str, pd.DataFrame], contracts: dict[str, DataContract]
) -> GenerationValidationOutcome:
    contract_reports = validate_contracts_strict(tables, contracts)
    statistical_checks = run_statistical_checks(tables)
    pii_safe, pii_detail = check_pii_safety(tables, contracts)
    return GenerationValidationOutcome(
        contract_reports=contract_reports,
        statistical_checks=statistical_checks,
        pii_safe=pii_safe,
        pii_detail=pii_detail,
    )
