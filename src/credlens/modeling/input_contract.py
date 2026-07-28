"""Input contract gate for scoring-time data (Phase 9 section 12) -
turns the Phase 8 robustness finding ("PR-AUC degradation ~0.169 under an
out-of-domain delinquency code") into an enforced gate instead of a
one-off stress-test observation.

Two modes:

- `strict`: a batch-level schema violation (missing/extra column, a
  column that cannot be coerced to numeric) rejects the WHOLE batch
  outright - nothing is scored. A row-level violation (duplicate ID,
  non-finite value, out-of-domain delinquency code, an impossible
  monetary range) quarantines ONLY the offending rows to a local CSV;
  the remaining clean rows may still be scored by the caller.
- `audit`: never raises, never quarantines, never implies a score should
  be produced - it only profiles every violation found (Phase 9 section
  12.1: "não produz score operacional; registra a anomalia; calcula
  perfil de impacto; permite diagnóstico").

Never silently maps an unknown code to zero/paid-off/mean - both modes
report it explicitly instead.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd

Mode = Literal["strict", "audit"]

_ID_COLUMN = "ID"
_DELINQUENCY_COLUMNS = ["X6", "X7", "X8", "X9", "X10", "X11"]
_MONETARY_COLUMNS = [
    "X1",
    "X12",
    "X13",
    "X14",
    "X15",
    "X16",
    "X17",
    "X18",
    "X19",
    "X20",
    "X21",
    "X22",
    "X23",
]
_REQUIRED_COLUMNS = [_ID_COLUMN, *[f"X{i}" for i in range(1, 24)]]
_TOLERATED_EXTRA_COLUMNS = frozenset({"Y"})

# Documented delinquency-status domain (config/modeling/feature_registry.yml:
# "-2 to 9 documented"). A code outside this set is not necessarily wrong
# data - it may be a legitimately new servicing code - but this project's
# model was never trained on one, so it is flagged, never silently mapped.
_DELINQUENCY_DOMAIN = frozenset(range(-2, 10))

# A generous, documented sanity bound (NT dollar) - several orders of
# magnitude above the largest value observed in the acquired UCI file -
# used only to catch a clearly impossible monetary value, not to encode
# any real institutional credit-limit policy.
MONETARY_ABSOLUTE_MAX = 1e8

QUARANTINE_DIR = Path("reports/modeling/quarantine")


class InputContractError(Exception):
    """Raised in `strict` mode for a batch-level schema violation."""


@dataclass(frozen=True)
class ContractViolation:
    scope: Literal["batch", "row"]
    violation_type: str
    column: str | None
    row_id: Any
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope": self.scope,
            "violation_type": self.violation_type,
            "column": self.column,
            "row_id": None if self.row_id is None else str(self.row_id),
            "detail": self.detail,
        }


@dataclass(frozen=True)
class InputValidationReport:
    mode: Mode
    n_rows: int
    n_valid_rows: int
    n_quarantined_rows: int
    batch_level_violations: list[ContractViolation]
    row_level_violations: list[ContractViolation]
    quarantined_ids: list[Any]
    impact_profile: dict[str, int] = field(default_factory=dict)

    @property
    def has_batch_level_violation(self) -> bool:
        return len(self.batch_level_violations) > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "n_rows": self.n_rows,
            "n_valid_rows": self.n_valid_rows,
            "n_quarantined_rows": self.n_quarantined_rows,
            "batch_level_violations": [v.to_dict() for v in self.batch_level_violations],
            "row_level_violations": [v.to_dict() for v in self.row_level_violations],
            "quarantined_ids": [str(i) for i in self.quarantined_ids],
            "impact_profile": self.impact_profile,
        }


def _check_schema(df: pd.DataFrame) -> list[ContractViolation]:
    violations = []
    missing = [c for c in _REQUIRED_COLUMNS if c not in df.columns]
    for column in missing:
        violations.append(
            ContractViolation(
                "batch", "missing_required_column", column, None, f"'{column}' is absent."
            )
        )
    extra = [
        c for c in df.columns if c not in _REQUIRED_COLUMNS and c not in _TOLERATED_EXTRA_COLUMNS
    ]
    for column in extra:
        violations.append(
            ContractViolation(
                "batch",
                "unexpected_extra_column",
                column,
                None,
                f"'{column}' is not part of the schema.",
            )
        )
    for column in [c for c in _REQUIRED_COLUMNS if c in df.columns]:
        coerced = pd.to_numeric(df[column], errors="coerce")
        if coerced.isna().any() and not df[column].isna().any():
            violations.append(
                ContractViolation(
                    "batch",
                    "wrong_dtype",
                    column,
                    None,
                    f"'{column}' contains value(s) that cannot be interpreted as numeric.",
                )
            )
    return violations


def _check_rows(df: pd.DataFrame) -> list[ContractViolation]:
    violations = []
    id_col = df[_ID_COLUMN]
    duplicated_mask = id_col.duplicated(keep="first")
    for row_id in id_col[duplicated_mask]:
        violations.append(
            ContractViolation("row", "duplicate_id", _ID_COLUMN, row_id, "Duplicate identifier.")
        )

    numeric_cols = [c for c in _REQUIRED_COLUMNS[1:] if c in df.columns]
    numeric = df[numeric_cols].apply(pd.to_numeric, errors="coerce")
    non_finite_mask = ~np.isfinite(numeric.to_numpy(dtype=float))
    for row_pos, col_pos in zip(*np.where(non_finite_mask), strict=True):
        column = numeric_cols[col_pos]
        row_id = df[_ID_COLUMN].iloc[row_pos]
        violations.append(
            ContractViolation(
                "row", "non_finite_value", column, row_id, f"Non-finite value in '{column}'."
            )
        )

    for column in _DELINQUENCY_COLUMNS:
        values = pd.to_numeric(df[column], errors="coerce")
        mask = ~values.isin(_DELINQUENCY_DOMAIN) & values.notna()
        for row_id, value in zip(df.loc[mask, _ID_COLUMN], values[mask], strict=True):
            violations.append(
                ContractViolation(
                    "row",
                    "domain_violation",
                    column,
                    row_id,
                    f"Delinquency code {value:g} outside documented domain "
                    f"{sorted(_DELINQUENCY_DOMAIN)}.",
                )
            )

    for column in _MONETARY_COLUMNS:
        values = pd.to_numeric(df[column], errors="coerce")
        mask = values.abs() > MONETARY_ABSOLUTE_MAX
        for row_id, value in zip(df.loc[mask, _ID_COLUMN], values[mask], strict=True):
            violations.append(
                ContractViolation(
                    "row",
                    "range_violation",
                    column,
                    row_id,
                    f"Value {value:,.0f} exceeds the sanity bound of {MONETARY_ABSOLUTE_MAX:,.0f}.",
                )
            )
    return violations


def _impact_profile(violations: list[ContractViolation]) -> dict[str, int]:
    profile: dict[str, int] = {}
    for violation in violations:
        profile[violation.violation_type] = profile.get(violation.violation_type, 0) + 1
    return profile


def validate_input_contract(df: pd.DataFrame, mode: Mode) -> InputValidationReport:
    batch_violations = _check_schema(df)
    if batch_violations and mode == "strict":
        detail = "; ".join(v.detail for v in batch_violations)
        raise InputContractError(f"Batch-level schema violation(s) in strict mode: {detail}")
    if batch_violations:
        # audit mode (or a caller inspecting before deciding): schema is
        # broken badly enough that row-level checks would be meaningless.
        return InputValidationReport(
            mode=mode,
            n_rows=len(df),
            n_valid_rows=0,
            n_quarantined_rows=0,
            batch_level_violations=batch_violations,
            row_level_violations=[],
            quarantined_ids=[],
            impact_profile=_impact_profile(batch_violations),
        )

    row_violations = _check_rows(df)
    quarantined_ids = sorted({v.row_id for v in row_violations}, key=str)

    if mode == "audit":
        return InputValidationReport(
            mode=mode,
            n_rows=len(df),
            n_valid_rows=len(df) - len(quarantined_ids),
            n_quarantined_rows=len(quarantined_ids),
            batch_level_violations=[],
            row_level_violations=row_violations,
            quarantined_ids=quarantined_ids,
            impact_profile=_impact_profile(row_violations),
        )

    return InputValidationReport(
        mode=mode,
        n_rows=len(df),
        n_valid_rows=len(df) - len(quarantined_ids),
        n_quarantined_rows=len(quarantined_ids),
        batch_level_violations=[],
        row_level_violations=row_violations,
        quarantined_ids=quarantined_ids,
        impact_profile=_impact_profile(row_violations),
    )


def clean_rows(df: pd.DataFrame, report: InputValidationReport) -> pd.DataFrame:
    """Only meaningful in `strict` mode - returns `df` with every
    quarantined row removed."""
    if not report.quarantined_ids:
        return df
    return df[~df[_ID_COLUMN].isin(report.quarantined_ids)].copy()


def write_quarantine(
    df: pd.DataFrame, report: InputValidationReport, *, repo_root: Path | None = None
) -> Path | None:
    """Writes quarantined rows (plus a sidecar reason per row) to a local,
    timestamped CSV under `reports/modeling/quarantine/` - never sent
    anywhere external."""
    if not report.quarantined_ids:
        return None
    repo_root = repo_root or Path.cwd()
    out_dir = repo_root / QUARANTINE_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
    path = out_dir / f"quarantine_{timestamp}.csv"

    quarantined = df[df[_ID_COLUMN].isin(report.quarantined_ids)].copy()
    reasons_by_id: dict[Any, list[str]] = {}
    for violation in report.row_level_violations:
        reasons_by_id.setdefault(violation.row_id, []).append(violation.violation_type)
    quarantined["quarantine_reasons"] = quarantined[_ID_COLUMN].map(
        lambda i: ";".join(reasons_by_id.get(i, []))
    )
    quarantined.to_csv(path, index=False)

    manifest_path = out_dir / f"quarantine_{timestamp}.manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "quarantined_at_utc": datetime.now(UTC).isoformat(),
                "n_rows": len(quarantined),
                "impact_profile": report.impact_profile,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return path
