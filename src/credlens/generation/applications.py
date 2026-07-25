"""Applications, frozen application_features, and evaluation-only
fairness_attributes - generated together since they share one row per
application by construction (docs/adr/0004-feature-freeze-at-proposal.md).

No column here that postdates submitted_at is ever produced - there is no
future information available to leak, because nothing downstream
(decisions, contracts, payments) has been generated yet at this step.
"""

from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd

from credlens.generation.config import ApplicationsConfig, PeriodConfig, PopulationConfig
from credlens.generation.ids import IdFactory

_BUREAU_BUCKETS = ("thin_file", "low", "medium", "high")
_AGE_BRACKETS = ("18-25", "26-35", "36-50", "51-65", "65+")
_GENDER_LABELS = ("a", "b", "unspecified")
_REGIONS = ("region_1", "region_2", "region_3", "region_4")


def generate_applications(
    customers: pd.DataFrame,
    period: PeriodConfig,
    applications_cfg: ApplicationsConfig,
    population_cfg: PopulationConfig,
    generation_run_id: str,
    application_ids: IdFactory,
    rng: np.random.Generator,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Returns (applications, application_features, fairness_attributes),
    all one-row-per-application, in submitted_at order."""
    created_at = pd.to_datetime(customers["created_at"], utc=True)
    counts = rng.integers(
        1, applications_cfg.applications_per_customer_max + 1, size=len(customers)
    )

    customer_id_repeated = np.repeat(customers["customer_id"].to_numpy(), counts)
    created_at_repeated = pd.DatetimeIndex(np.repeat(created_at.to_numpy(), counts))
    n = len(customer_id_repeated)

    period_days = (period.end - period.start).days
    # Independent per-row offsets in days, then sorted WITHIN each customer
    # (via a stable groupby-cumsum trick) so a customer's own applications
    # are always in increasing submitted_at order, without ever preceding
    # that customer's own created_at.
    raw_offsets = rng.integers(0, max(period_days, 1), size=n)
    order_df = pd.DataFrame({"customer_id": customer_id_repeated, "offset": raw_offsets})
    order_df["offset"] = order_df.groupby("customer_id")["offset"].transform(sorted)
    offsets = order_df["offset"].to_numpy()
    seconds = rng.integers(0, 86400, size=n)

    submitted_at = (
        created_at_repeated
        + pd.to_timedelta(offsets, unit="D")
        + pd.to_timedelta(seconds, unit="s")
    )
    # Never past the simulated period end, and never before the customer exists.
    period_end_ts = pd.Timestamp(period.end, tz="UTC") + timedelta(hours=23, minutes=59)
    submitted_at = submitted_at.where(submitted_at <= period_end_ts, period_end_ts)

    channel_names = list(applications_cfg.channel_weights)
    channel_probs = np.array(list(applications_cfg.channel_weights.values()))
    channel_probs = channel_probs / channel_probs.sum()
    channels = rng.choice(channel_names, size=n, p=channel_probs)

    requested_amount = np.round(
        rng.uniform(
            applications_cfg.requested_amount_min, applications_cfg.requested_amount_max, size=n
        ),
        2,
    )
    requested_term_months = rng.choice(applications_cfg.requested_term_months_choices, size=n)

    application_ids_list = [application_ids.next() for _ in range(n)]

    applications = pd.DataFrame(
        {
            "application_id": application_ids_list,
            "customer_id": customer_id_repeated,
            "generation_run_id": generation_run_id,
            "submitted_at": submitted_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "product": "personal_loan",
            "channel": channels,
            "requested_amount": requested_amount,
            "requested_term_months": requested_term_months,
            # status is finalized later by decisions.finalize_application_status()
            "status": "submitted",
        }
    )

    bureau_bucket_names = list(population_cfg.bureau_score_bucket_weights)
    bureau_bucket_probs = np.array(list(population_cfg.bureau_score_bucket_weights.values()))
    bureau_bucket_probs = bureau_bucket_probs / bureau_bucket_probs.sum()
    bureau_bucket = rng.choice(bureau_bucket_names, size=n, p=bureau_bucket_probs)
    is_thin_file = bureau_bucket == "thin_file"

    declared_income = np.round(
        rng.uniform(population_cfg.declared_income_min, population_cfg.declared_income_max, size=n),
        2,
    )
    employment_months = rng.integers(0, population_cfg.employment_months_max + 1, size=n).astype(
        float
    )
    employment_months[is_thin_file] = np.nan
    debt_to_income = np.round(rng.uniform(0.0, 1.5, size=n), 4)
    debt_to_income[is_thin_file] = np.nan

    has_relationship = rng.random(n) < population_cfg.existing_relationship_share
    relationship_months = np.where(
        has_relationship, rng.integers(1, population_cfg.employment_months_max + 1, size=n), 0
    )

    application_features = pd.DataFrame(
        {
            "application_id": application_ids_list,
            "declared_income": declared_income,
            "debt_to_income": debt_to_income,
            "employment_months": employment_months,
            "relationship_months": relationship_months,
            "bureau_score_bucket": bureau_bucket,
            "requested_amount": requested_amount,
            "requested_term_months": requested_term_months,
            "feature_snapshot_at": applications["submitted_at"],
        }
    )

    fairness_attributes = pd.DataFrame(
        {
            "application_id": application_ids_list,
            "age_bracket": rng.choice(_AGE_BRACKETS, size=n),
            "synthetic_gender": rng.choice(_GENDER_LABELS, size=n, p=[0.47, 0.47, 0.06]),
            "region": rng.choice(_REGIONS, size=n),
        }
    )

    return applications, application_features, fairness_attributes


def apply_cancellations(
    applications: pd.DataFrame, cancellation_rate: float, rng: np.random.Generator
) -> pd.DataFrame:
    """A fraction of applications never reach a final decision - marked
    'cancelled' up front so decisions.py knows to skip them."""
    n = len(applications)
    is_cancelled = rng.random(n) < cancellation_rate
    result = applications.copy()
    result.loc[is_cancelled, "status"] = "cancelled"
    return result
