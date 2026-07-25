"""Recovery scheduling and event-row construction.

Whether/when/how much a written-off contract ever recovers is decided
ONCE, at the moment of write-off (not re-rolled every subsequent month) -
keeps the model simple and guarantees at most one recovery_event per
write-off in this phase's scope. See
docs/synthetic_generation_implementation.md.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

import numpy as np
import pandas as pd

from credlens.generation.config import RecoveryConfig
from credlens.generation.ids import IdFactory

_CHANNELS = ("collections_agent", "legal", "debt_sale", "voluntary")
_CENTS = Decimal("0.01")


def schedule_recovery(
    write_off_amount: Decimal, config: RecoveryConfig, rng: np.random.Generator
) -> tuple[int, Decimal] | None:
    """Returns (month_offset, amount) if this write-off will recover
    something, else None. month_offset is 1..max_months_after_write_off."""
    if rng.random() >= config.recovery_probability:
        return None
    month_offset = int(rng.integers(1, config.max_months_after_write_off + 1))
    fraction = rng.uniform(config.recovery_fraction_min, config.recovery_fraction_max)
    amount = (write_off_amount * Decimal(str(round(fraction, 6)))).quantize(
        _CENTS, rounding=ROUND_HALF_UP
    )
    return month_offset, amount


def recovery_event_row(
    contract_id: str,
    write_off_id: str,
    recovery_date: pd.Timestamp,
    amount: Decimal,
    recovery_ids: IdFactory,
    rng: np.random.Generator,
) -> dict[str, object]:
    channel = rng.choice(_CHANNELS, p=[0.55, 0.15, 0.15, 0.15])
    return {
        "recovery_id": recovery_ids.next(),
        "contract_id": contract_id,
        "write_off_id": write_off_id,
        "recovery_date": recovery_date.strftime("%Y-%m-%d"),
        "amount": float(amount),
        "channel": str(channel),
        "source": None,
    }
