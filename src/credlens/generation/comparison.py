"""Technical, aggregate-only metrics for one generated run, and a
baseline-vs-candidate comparison - Phase 4B sections 6-10, 12. These are
DGP sanity/directional checks, not business findings (same posture as
credlens.generation.validation - see its own module docstring). Never
reads truth for the operational decision path; DOES read the isolated
truth layer here, but only to report an AGGREGATE statistic (mean latent
propensity of approved applicants) for validating the generator's own
behavior - never joined back into an operational table, never exposed as
a customer-level value, never read by credlens.generation.decisions.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

_TERMINAL_STATUSES = ("settled", "closed", "charged_off")


@dataclass(frozen=True)
class ScenarioMetrics:
    generation_run_id: str
    n_applications: int
    n_decided: int
    n_approved: int
    approval_rate: float
    n_contracts: int
    booking_rate: float
    n_snapshots: int
    dpd30_plus_rate: float
    dpd60_plus_rate: float
    dpd90_plus_rate: float
    cure_rate: float
    n_write_offs: int
    write_off_rate: float
    n_recoveries: int
    n_collection_events: int
    # Monetary totals (Phase 7 gate A) - added so multi-seed robustness can
    # track write-off/recovery AMOUNT, not just event counts, across
    # scenarios/seeds. Synthetic monetary units - see docs/glossary.md.
    total_write_off_amount: float
    total_recovery_amount: float
    avg_latent_propensity_of_approved: float | None

    def to_dict(self) -> dict[str, object]:
        return {
            "generation_run_id": self.generation_run_id,
            "n_applications": self.n_applications,
            "n_decided": self.n_decided,
            "n_approved": self.n_approved,
            "approval_rate": round(self.approval_rate, 6),
            "n_contracts": self.n_contracts,
            "booking_rate": round(self.booking_rate, 6),
            "n_snapshots": self.n_snapshots,
            "dpd30_plus_rate": round(self.dpd30_plus_rate, 6),
            "dpd60_plus_rate": round(self.dpd60_plus_rate, 6),
            "dpd90_plus_rate": round(self.dpd90_plus_rate, 6),
            "cure_rate": round(self.cure_rate, 6),
            "n_write_offs": self.n_write_offs,
            "write_off_rate": round(self.write_off_rate, 6),
            "n_recoveries": self.n_recoveries,
            "n_collection_events": self.n_collection_events,
            "total_write_off_amount": round(self.total_write_off_amount, 2),
            "total_recovery_amount": round(self.total_recovery_amount, 2),
            "avg_latent_propensity_of_approved": (
                round(self.avg_latent_propensity_of_approved, 6)
                if self.avg_latent_propensity_of_approved is not None
                else None
            ),
        }


def _read(operational_dir: Path, name: str) -> pd.DataFrame:
    path = operational_dir / f"{name}.parquet"
    if not path.is_file():
        return pd.DataFrame()
    return pd.read_parquet(path)


def compute_metrics(
    generation_run_id: str, operational_dir: Path, truth_dir: Path | None = None
) -> ScenarioMetrics:
    applications = _read(operational_dir, "applications")
    decisions = _read(operational_dir, "credit_decisions")
    contracts = _read(operational_dir, "contracts")
    snapshots = _read(operational_dir, "account_monthly_snapshots")
    write_offs = _read(operational_dir, "write_off_events")
    recoveries = _read(operational_dir, "recovery_events")
    collections = _read(operational_dir, "collection_events")

    n_decided = int((decisions["is_final"] == True).sum()) if not decisions.empty else 0  # noqa: E712
    n_approved = int((decisions["outcome"] == "approved").sum()) if not decisions.empty else 0
    approval_rate = n_approved / n_decided if n_decided else 0.0

    n_contracts = len(contracts)
    booking_rate = n_contracts / n_approved if n_approved else 0.0

    n_snapshots = len(snapshots)
    if n_snapshots:
        dpd = pd.to_numeric(snapshots["dpd"], errors="coerce")
        dpd30 = float((dpd >= 30).mean())
        dpd60 = float((dpd >= 60).mean())
        dpd90 = float((dpd >= 90).mean())
        ever_delinquent = set(snapshots.loc[snapshots["status"] == "delinquent", "contract_id"])
        ever_settled = set(snapshots.loc[snapshots["status"] == "settled", "contract_id"])
        cured = ever_delinquent & ever_settled
        cure_rate = len(cured) / len(ever_delinquent) if ever_delinquent else 0.0
    else:
        dpd30 = dpd60 = dpd90 = cure_rate = 0.0

    n_write_offs = len(write_offs)
    write_off_rate = n_write_offs / n_contracts if n_contracts else 0.0
    n_recoveries = len(recoveries)
    n_collection_events = len(collections)
    total_write_off_amount = (
        float(pd.to_numeric(write_offs["amount"], errors="coerce").sum())
        if not write_offs.empty
        else 0.0
    )
    total_recovery_amount = (
        float(pd.to_numeric(recoveries["amount"], errors="coerce").sum())
        if not recoveries.empty
        else 0.0
    )

    avg_latent_propensity_of_approved: float | None = None
    if truth_dir is not None and not contracts.empty:
        truth_path = truth_dir / "latent_contract_truth.parquet"
        if truth_path.is_file():
            truth = pd.read_parquet(truth_path)
            merged = contracts.merge(truth, on="contract_id", how="inner")
            if not merged.empty:
                avg_latent_propensity_of_approved = float(
                    merged["latent_payment_propensity"].mean()
                )

    return ScenarioMetrics(
        generation_run_id=generation_run_id,
        n_applications=len(applications),
        n_decided=n_decided,
        n_approved=n_approved,
        approval_rate=approval_rate,
        n_contracts=n_contracts,
        booking_rate=booking_rate,
        n_snapshots=n_snapshots,
        dpd30_plus_rate=dpd30,
        dpd60_plus_rate=dpd60,
        dpd90_plus_rate=dpd90,
        cure_rate=cure_rate,
        n_write_offs=n_write_offs,
        write_off_rate=write_off_rate,
        n_recoveries=n_recoveries,
        n_collection_events=n_collection_events,
        total_write_off_amount=total_write_off_amount,
        total_recovery_amount=total_recovery_amount,
        avg_latent_propensity_of_approved=avg_latent_propensity_of_approved,
    )


@dataclass(frozen=True)
class MetricComparison:
    metric: str
    baseline_value: float
    candidate_value: float
    delta: float

    def to_dict(self) -> dict[str, object]:
        return {
            "metric": self.metric,
            "baseline_value": round(self.baseline_value, 6),
            "candidate_value": round(self.candidate_value, 6),
            "delta": round(self.delta, 6),
        }


_COMPARABLE_METRICS = (
    # Counts (Phase 7 gate A additions) - raw deltas double as "marginal
    # contracts/approvals added or removed" for policy_expansion/
    # tightening, and as collections-activity volume for
    # collections_change, without duplicating warehouse-layer business
    # logic (this reads the same generation-layer parquet already loaded
    # above, nothing new is computed elsewhere).
    "n_applications",
    "n_approved",
    "n_contracts",
    "n_collection_events",
    # Rates (Phase 4B/6 original set).
    "approval_rate",
    "booking_rate",
    "dpd30_plus_rate",
    "dpd60_plus_rate",
    "dpd90_plus_rate",
    "cure_rate",
    "write_off_rate",
    # Monetary totals (Phase 7 gate A additions).
    "total_write_off_amount",
    "total_recovery_amount",
)


def compare_metrics(
    baseline: ScenarioMetrics, candidate: ScenarioMetrics
) -> list[MetricComparison]:
    comparisons = []
    for metric in _COMPARABLE_METRICS:
        b = float(getattr(baseline, metric))
        c = float(getattr(candidate, metric))
        comparisons.append(
            MetricComparison(metric=metric, baseline_value=b, candidate_value=c, delta=c - b)
        )
    return comparisons


def write_comparison_report(
    path: Path,
    baseline: ScenarioMetrics,
    candidate: ScenarioMetrics,
    comparisons: list[MetricComparison],
) -> None:
    payload = {
        "baseline": baseline.to_dict(),
        "candidate": candidate.to_dict(),
        "comparisons": [c.to_dict() for c in comparisons],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
