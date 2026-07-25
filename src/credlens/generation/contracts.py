"""Contract booking: which approved applications actually become a
contract (an approval never implies a contract - contracts.yaml), with
contract_date/disbursement_date respecting the causal chain
decision -> contract -> disbursement (docs/temporal_semantics.md).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from credlens.generation.config import BookingConfig, ContractConfig
from credlens.generation.ids import IdFactory


def generate_contracts(
    applications: pd.DataFrame,
    credit_decisions: pd.DataFrame,
    booking_cfg: BookingConfig,
    contract_cfg: ContractConfig,
    currency_unit: str,
    contract_ids: IdFactory,
    rng: np.random.Generator,
) -> pd.DataFrame:
    approved_decisions = credit_decisions[credit_decisions["outcome"] == "approved"].copy()
    n_approved = len(approved_decisions)
    is_booked = rng.random(n_approved) < booking_cfg.booking_rate_given_approved
    booked = approved_decisions[is_booked].copy()
    n = len(booked)
    if n == 0:
        return pd.DataFrame(
            columns=[
                "contract_id",
                "application_id",
                "customer_id",
                "contract_date",
                "disbursement_date",
                "financed_amount",
                "term_months",
                "contract_rate",
                "num_installments",
                "first_due_date",
                "status",
                "currency_unit",
                "closed_date",
            ]
        )

    customer_by_application = applications.set_index("application_id")["customer_id"]

    decision_ts = pd.to_datetime(booked["decision_timestamp"], utc=True)
    days_to_contract = rng.integers(0, booking_cfg.max_days_approval_to_contract + 1, size=n)
    contract_date = decision_ts + pd.to_timedelta(days_to_contract, unit="D")

    days_to_disbursement = rng.integers(
        0, contract_cfg.max_days_contract_to_disbursement + 1, size=n
    )
    disbursement_date = contract_date + pd.to_timedelta(days_to_disbursement, unit="D")

    first_due_date = (disbursement_date + pd.Timedelta(days=30)).dt.normalize()

    contract_ids_list = [contract_ids.next() for _ in range(n)]

    return pd.DataFrame(
        {
            "contract_id": contract_ids_list,
            "application_id": booked["application_id"].to_numpy(),
            "customer_id": customer_by_application.loc[booked["application_id"]].to_numpy(),
            "contract_date": contract_date.dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "disbursement_date": disbursement_date.dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "financed_amount": booked["approved_amount"].to_numpy(),
            "term_months": booked["approved_term_months"].to_numpy().astype(int),
            "contract_rate": booked["offered_rate"].to_numpy(),
            "num_installments": booked["approved_term_months"].to_numpy().astype(int),
            "first_due_date": first_due_date.dt.strftime("%Y-%m-%d"),
            "status": "active",
            "currency_unit": currency_unit,
            "closed_date": None,
        }
    )
