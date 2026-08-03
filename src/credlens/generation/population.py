"""Synthetic customer population - no PII, no CPF-shaped identifiers.

Only what contracts/operational/customers.yaml actually declares
(customer_id, generation_run_id, created_at) - demographic/operational
characteristics live downstream, in application_features (frozen at
proposal time) and fairness_attributes (evaluation-only), never here -
see docs/adr/0007 and contracts/operational/customers.yaml's own comment
on why no latent parameter belongs on this table either.
"""

from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd

from credlens.generation.config import PeriodConfig
from credlens.generation.ids import IdFactory


def generate_customers(
    n_customers: int,
    period: PeriodConfig,
    generation_run_id: str,
    id_factory: IdFactory,
    rng: np.random.Generator,
) -> pd.DataFrame:
    """Customers arrive uniformly at random across the simulated period
    (a simple, explicitly synthetic arrival process - no seasonality
    modeled in baseline, see config/synthetic/scenarios/baseline.blueprint.yaml's
    customer_arrival_pattern, still requires_calibration at the design
    level even though this executable config picks a concrete uniform
    choice to make the generator runnable)."""
    total_days = (period.end - period.start).days
    offsets = rng.integers(0, total_days, size=n_customers)
    seconds = rng.integers(0, 86400, size=n_customers)

    customer_ids = [id_factory.next() for _ in range(n_customers)]
    created_at = [
        pd.Timestamp(period.start) + timedelta(days=int(d), seconds=int(s))
        for d, s in zip(offsets, seconds, strict=True)
    ]

    df = pd.DataFrame(
        {
            "customer_id": customer_ids,
            "generation_run_id": generation_run_id,
            "created_at": pd.to_datetime(created_at, utc=True).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
    )
    return df.sort_values("created_at").reset_index(drop=True)
