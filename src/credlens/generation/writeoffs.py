"""Write-off decision and event-row construction.

Write-off is decided from DPD alone (a synthetic policy threshold), but
is never *inferred* by any consumer from DPD - it is always an explicit
event row, per this phase's requirement. See
docs/synthetic_generation_implementation.md and
contracts/operational/write_off_events.yaml.
"""

from __future__ import annotations

from decimal import Decimal

import pandas as pd

from credlens.generation.config import WriteOffConfig
from credlens.generation.ids import IdFactory


def should_write_off(dpd: int, config: WriteOffConfig) -> bool:
    return dpd >= config.dpd_threshold


def write_off_event_row(
    contract_id: str,
    write_off_date: pd.Timestamp,
    principal: Decimal,
    interest: Decimal,
    fees: Decimal,
    dpd_threshold: int,
    write_off_ids: IdFactory,
) -> dict[str, object]:
    amount = principal + interest + fees
    return {
        "write_off_id": write_off_ids.next(),
        "contract_id": contract_id,
        "write_off_date": write_off_date.strftime("%Y-%m-%d"),
        "amount": float(amount),
        "principal": float(principal),
        "interest": float(interest),
        "fees": float(fees),
        "reason": "policy_threshold",
        "policy_reference": f"baseline write-off policy: dpd>={dpd_threshold} (illustrative only)",
    }
