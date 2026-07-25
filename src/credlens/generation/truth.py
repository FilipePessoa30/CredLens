"""The synthetic-truth layer: latent parameters used ONLY to drive
simulated behavior and to let a future generator-validation pass check
"did the generator produce what it intended to" - never merged into any
operational table, never read by policies.py's decision score, never
shown in a dashboard. See docs/conceptual_data_model.md section 4.17 and
docs/adr/0007-synthetic-truth-isolation.md.

Physically separate: written only under data/synthetic_truth/<run_id>/
(git-ignored, same as data/raw/) by writers.py - this module only
computes the values in memory.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def generate_latent_customer_truth(
    customers: pd.DataFrame, rng: np.random.Generator
) -> pd.DataFrame:
    """One row per customer: a latent payment propensity in [0, 1] drawn
    from a Beta distribution skewed toward good payers (mean ~0.75) -
    baseline has no injected bad-population shock (that would be a
    different, not-yet-built scenario)."""
    n = len(customers)
    payment_propensity = rng.beta(6, 2, size=n)
    return pd.DataFrame(
        {
            "customer_id": customers["customer_id"].to_numpy(),
            "latent_payment_propensity": payment_propensity,
        }
    )


def attach_contract_truth(
    contracts: pd.DataFrame, latent_customer_truth: pd.DataFrame
) -> pd.DataFrame:
    """One row per contract: the same customer-level propensity carried
    down to contract grain (baseline does not model per-contract
    variation beyond the customer's own latent propensity)."""
    lookup = latent_customer_truth.set_index("customer_id")["latent_payment_propensity"]
    propensity = contracts["customer_id"].map(lookup)
    return pd.DataFrame(
        {
            "contract_id": contracts["contract_id"].to_numpy(),
            "customer_id": contracts["customer_id"].to_numpy(),
            "latent_payment_propensity": propensity.to_numpy(),
        }
    )
