"""The baseline scenario's single policy_versions row.

Per config/synthetic/scenarios/baseline.blueprint.yaml's `policy_profile`
(status: specified, value: single_policy_version): exactly one policy
version is active for the whole simulated period - no policy-change
events. policy_expansion/policy_tightening would add more rows; not
built in Phase 4A.
"""

from __future__ import annotations

import pandas as pd

from credlens.generation.config import PeriodConfig
from credlens.generation.ids import IdFactory


def generate_policy_versions(period: PeriodConfig, id_factory: IdFactory) -> pd.DataFrame:
    policy_version_id = id_factory.next()
    effective_from = pd.Timestamp(period.start, tz="UTC") - pd.Timedelta(days=1)
    return pd.DataFrame(
        {
            "policy_version_id": [policy_version_id],
            "name": ["baseline_standard"],
            "version": [1],
            "effective_from": [effective_from.strftime("%Y-%m-%dT%H:%M:%SZ")],
            "effective_to": [None],
            "status": ["active"],
            "rules_reference": ["baseline-generation-config-v1"],
            "change_reason": ["Initial baseline policy - no prior version exists."],
            "scenario": ["baseline"],
        }
    )
