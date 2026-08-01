"""Phase 10 gate E - loads and applies
`config/model_validation/reason_codes.yml`, the executive reason-code
governance policy for MODEL_behavioral_default_v1.

Lives in `credlens.modeling` (not `credlens.model_validation`) even
though the policy's CONTENT is derived from the independent validation
layer's stability/VIF audit: `credlens.modeling` must never import
`credlens.model_validation` (the one-way dependency the whole project
relies on for "independent" to mean something - model_validation depends
on modeling's outputs, never the reverse). Referencing the YAML's path
by string creates no such import, so the governance data can still live
under `config/model_validation/` where the audit that justified it also
lives.

This module is a pure PRESENTATION-LAYER filter: it never touches a
model's coefficients or predictions, only which features may be named in
an executive-facing reason code, local explanation, model card, dashboard
page, or report, and in what register (causal-sounding for `allowed`,
strictly mathematical for `conditional`, never at all for `prohibited`).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

REASON_CODE_POLICY_PATH = Path("config/model_validation/reason_codes.yml")

ReasonCodeTier = Literal["allowed", "conditional", "prohibited", "ungoverned"]


class ReasonCodePolicyError(Exception):
    """Raised when the reason-code policy cannot be loaded or is malformed."""


@dataclass(frozen=True)
class ReasonCodePolicy:
    version: str
    governed_model_id: str
    allowed_features: dict[str, dict[str, Any]]
    conditional_features: dict[str, dict[str, Any]]
    prohibited_features: dict[str, dict[str, Any]]

    def tier(self, feature: str) -> ReasonCodeTier:
        if feature in self.allowed_features:
            return "allowed"
        if feature in self.conditional_features:
            return "conditional"
        if feature in self.prohibited_features:
            return "prohibited"
        # A feature this policy has never classified (e.g. a NEW model's
        # feature set) is neither allowed nor prohibited by fiat - callers
        # must decide how to treat "ungoverned" (the safe default used by
        # `filter_and_rank_for_reason_codes` below is to exclude it).
        return "ungoverned"

    def caveat(self, feature: str, language: str) -> str | None:
        row = self.conditional_features.get(feature)
        if row is None:
            return None
        key = "caveat_pt_br" if language == "pt-BR" else "caveat_en"
        value = row.get(key)
        return str(value).strip() if value is not None else None

    def description(self, feature: str, language: str) -> str | None:
        row = self.allowed_features.get(feature) or self.conditional_features.get(feature)
        if row is None:
            return None
        key = "description_pt_br" if language == "pt-BR" else "description_en"
        value = row.get(key)
        return str(value).strip() if value is not None else None


def load_reason_code_policy(repo_root: Path | None = None) -> ReasonCodePolicy:
    repo_root = repo_root or Path.cwd()
    path = repo_root / REASON_CODE_POLICY_PATH
    if not path.is_file():
        raise ReasonCodePolicyError(f"Reason-code policy not found at '{path}'.")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    reason_codes = raw["reason_codes"]
    return ReasonCodePolicy(
        version=raw["reason_code_policy_version"],
        governed_model_id=raw["governed_model_id"],
        allowed_features={row["feature"]: row for row in reason_codes["allowed_features"]},
        conditional_features={row["feature"]: row for row in reason_codes["conditional_features"]},
        prohibited_features={row["feature"]: row for row in reason_codes["prohibited_features"]},
    )


def filter_and_rank_for_reason_codes(
    contributions: list[tuple[str, float]], policy: ReasonCodePolicy, *, top_k: int
) -> list[tuple[str, float, ReasonCodeTier]]:
    """Given (feature, contribution) pairs, drops `prohibited`/
    `ungoverned` features BEFORE ranking (never "removed and silently
    back-filled unfairly"), then re-sorts the remaining allowed/
    conditional features by absolute contribution and keeps the top
    `top_k` - exactly what the unfiltered ranking would have done, just
    over a smaller eligible set."""
    eligible = [
        (feature, contribution, policy.tier(feature))
        for feature, contribution in contributions
        if policy.tier(feature) in ("allowed", "conditional")
    ]
    eligible.sort(key=lambda row: abs(row[1]), reverse=True)
    return eligible[:top_k]
