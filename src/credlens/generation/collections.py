"""Collections contact-event decision and row construction.

Proximity to a later recovery must never be read as causal - this
generator draws promise-to-pay independently of whatever the recovery
module later decides, precisely so no artificial correlation is baked in
beyond what the shared latent payment propensity already creates (see
docs/business_rules.md's correlation/causality note,
docs/assumptions_and_limitations.md).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from credlens.generation.config import CollectionsConfig
from credlens.generation.ids import IdFactory

_CHANNELS = ("call", "sms", "email", "letter", "in_person")
_STRATEGY_BY_DPD = (
    (30, "early_stage_soft"),
    (90, "mid_stage_firm"),
    (10_000, "late_stage_hard"),
)


def should_contact(dpd: int, config: CollectionsConfig) -> bool:
    return any(dpd >= threshold for threshold in config.contact_dpd_thresholds)


def _strategy_for_dpd(dpd: int) -> str:
    for ceiling, name in _STRATEGY_BY_DPD:
        if dpd < ceiling:
            return name
    return _STRATEGY_BY_DPD[-1][1]


def collection_event_row(
    contract_id: str,
    event_date: pd.Timestamp,
    dpd: int,
    installment_amount_due: float,
    config: CollectionsConfig,
    collection_event_ids: IdFactory,
    rng: np.random.Generator,
) -> dict[str, object]:
    channel = rng.choice(_CHANNELS, p=[0.45, 0.20, 0.15, 0.10, 0.10])
    promised = bool(rng.random() < config.promise_to_pay_probability)
    outcome = (
        "promise_to_pay"
        if promised
        else rng.choice(
            ["contacted_no_commitment", "no_contact", "dispute", "refused"], p=[0.5, 0.3, 0.1, 0.1]
        )
    )
    promised_amount = round(installment_amount_due, 2) if promised else None
    promised_date = (
        (event_date + pd.Timedelta(days=int(rng.integers(3, 15)))).strftime("%Y-%m-%d")
        if promised
        else None
    )
    return {
        "collection_event_id": collection_event_ids.next(),
        "contract_id": contract_id,
        "event_timestamp": event_date.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "channel": str(channel),
        "strategy": _strategy_for_dpd(dpd),
        "outcome": str(outcome),
        "promise_to_pay": promised,
        "promised_amount": promised_amount,
        "promised_date": promised_date,
        "status": "open",
    }
