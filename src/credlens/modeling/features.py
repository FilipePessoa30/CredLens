"""Deterministic, interpretable behavioral feature engineering for the
Phase 8 early-warning model - Phase 8 section 9: a bounded, documented set
(`config/modeling/feature_registry.yml`'s `engineered_features`), never
"dozens of features without justification."

Column order convention (matches UCI's own column layout): index 0 is the
MOST RECENT month (September 2005), index 5 is the OLDEST (April 2005).
`PAY_x` (delinquency status) columns are `X6..X11`; `BILL_AMTx` are
`X12..X17`; `PAY_AMTx` are `X18..X23`. A statement-cycle pair is
(payment made in month i, bill outstanding as of month i+1) - the payment
recorded for a given month pays down the PRIOR month's bill - so only 5
of the 6 months form a valid pair (the oldest payment has no prior bill
inside the observed window).

Every ratio is safe-divided (never raises `ZeroDivisionError`, never
produces `inf`/`-inf`/`NaN`) and every capped ratio's cap is stated in
`config/modeling/feature_registry.yml`.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

_DELINQUENCY_COLUMNS = ["X6", "X7", "X8", "X9", "X10", "X11"]
_BILL_COLUMNS = ["X12", "X13", "X14", "X15", "X16", "X17"]
_PAYMENT_COLUMNS = ["X18", "X19", "X20", "X21", "X22", "X23"]
_LIMIT_COLUMN = "X1"

_RATIO_CAP = 5.0
_EPSILON = 1e-9

FEATURE_COLUMNS = [
    "max_delinquency_status",
    "months_delinquent_count",
    "most_recent_delinquency_status",
    "delinquency_trend",
    "consecutive_months_delinquent",
    "total_bill_amount",
    "avg_bill_amount",
    "bill_trend",
    "bill_variability",
    "utilization_ratio",
    "total_payment_amount",
    "avg_payment_amount",
    "payment_to_bill_ratio",
    "months_without_payment",
    "payment_coverage_rate",
    "payment_variation",
    "worst_payment_to_bill_ratio",
    "limit_exposure_distance",
]


def _safe_ratio(
    numerator: pd.Series, denominator: pd.Series, *, cap: float | None = None
) -> pd.Series:
    safe_denominator = denominator.where(denominator.abs() > _EPSILON, other=np.nan)
    ratio = numerator / safe_denominator
    ratio = ratio.fillna(0.0)
    ratio = ratio.replace([np.inf, -np.inf], 0.0)
    if cap is not None:
        ratio = ratio.clip(lower=-cap, upper=cap)
    return ratio


def _consecutive_months_delinquent(delinquency: pd.DataFrame) -> pd.Series:
    is_delinquent = delinquency > 0
    streak = np.zeros(len(delinquency), dtype=int)
    running = np.zeros(len(delinquency), dtype=int)
    for col in _DELINQUENCY_COLUMNS:  # most recent first: a real "counting back" streak
        running = np.where(is_delinquent[col].to_numpy(), running + 1, 0)
        streak = np.maximum(streak, running)
    return pd.Series(streak, index=delinquency.index, dtype=int)


def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    """Returns a NEW DataFrame indexed like `df`, containing only
    `FEATURE_COLUMNS` (plus nothing else - no raw column ever passes
    through untouched, per the feature registry's `engineered_allowed`
    classification for X1/X6-X23)."""
    delinquency = df[_DELINQUENCY_COLUMNS].astype(float)
    bill = df[_BILL_COLUMNS].astype(float)
    payment = df[_PAYMENT_COLUMNS].astype(float)
    limit = df[_LIMIT_COLUMN].astype(float)

    out = pd.DataFrame(index=df.index)
    out["max_delinquency_status"] = delinquency.max(axis=1)
    out["months_delinquent_count"] = (delinquency > 0).sum(axis=1)
    out["most_recent_delinquency_status"] = delinquency[_DELINQUENCY_COLUMNS[0]]
    out["delinquency_trend"] = (
        delinquency[_DELINQUENCY_COLUMNS[0]] - delinquency[_DELINQUENCY_COLUMNS[-1]]
    ) / 5.0
    out["consecutive_months_delinquent"] = _consecutive_months_delinquent(delinquency)

    out["total_bill_amount"] = bill.sum(axis=1)
    out["avg_bill_amount"] = bill.mean(axis=1)
    out["bill_trend"] = (bill[_BILL_COLUMNS[0]] - bill[_BILL_COLUMNS[-1]]) / 5.0
    out["bill_variability"] = bill.std(axis=1, ddof=0).fillna(0.0)
    out["utilization_ratio"] = _safe_ratio(out["avg_bill_amount"], limit, cap=_RATIO_CAP)

    out["total_payment_amount"] = payment.sum(axis=1)
    out["avg_payment_amount"] = payment.mean(axis=1)
    # Payment is always >= 0 (per the source's own documented domain); a
    # bill <= 0 means "already fully covered / in credit", never a
    # negative coverage ratio - so this is capped to [0, cap], not
    # symmetric, unlike utilization_ratio/limit_exposure_distance where a
    # negative value is a meaningful signal (over-limit / in credit).
    out["payment_to_bill_ratio"] = (
        _safe_ratio(out["total_payment_amount"], out["total_bill_amount"], cap=_RATIO_CAP)
        .where(out["total_bill_amount"] > _EPSILON, other=_RATIO_CAP)
        .clip(lower=0.0)
    )
    out["months_without_payment"] = (payment == 0).sum(axis=1)

    payment_cols = [payment[c] for c in _PAYMENT_COLUMNS[:5]]
    prior_bill_cols = [bill[c] for c in _BILL_COLUMNS[1:6]]
    pair_ratios = []
    coverage_flags = []
    for pay_col, bill_col in zip(payment_cols, prior_bill_cols, strict=True):
        ratio = _safe_ratio(pay_col, bill_col, cap=_RATIO_CAP).clip(lower=0.0)
        # When the prior bill was <= 0 (paid off / credit balance), treat
        # the cycle as fully covered rather than an undefined ratio.
        ratio = ratio.where(bill_col > _EPSILON, other=_RATIO_CAP)
        pair_ratios.append(ratio)
        coverage_flags.append((pay_col >= bill_col) | (bill_col <= _EPSILON))

    pair_ratio_df = pd.concat(pair_ratios, axis=1)
    coverage_df = pd.concat(coverage_flags, axis=1)
    out["payment_coverage_rate"] = coverage_df.mean(axis=1)
    out["worst_payment_to_bill_ratio"] = pair_ratio_df.min(axis=1)

    payment_mean = out["avg_payment_amount"]
    payment_std = payment.std(axis=1, ddof=0).fillna(0.0)
    out["payment_variation"] = payment_std / (payment_mean.abs() + _EPSILON)
    out["payment_variation"] = out["payment_variation"].replace([np.inf, -np.inf], 0.0)

    out["limit_exposure_distance"] = _safe_ratio(
        limit - out["avg_bill_amount"], limit, cap=_RATIO_CAP
    )

    # Always float64, even for count-like columns (months_delinquent_count,
    # consecutive_months_delinquent, months_without_payment) - scikit-learn's
    # partial_dependence refuses integer-dtype columns outright, and every
    # other consumer (scaling, calibration) treats these as continuous anyway.
    out = out[FEATURE_COLUMNS].astype(float)
    if not np.isfinite(out.to_numpy(dtype=float)).all():
        raise ValueError("engineer_features produced a non-finite value - this is a bug.")
    return out
