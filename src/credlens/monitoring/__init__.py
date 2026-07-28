"""Monitoring-simulation layer (Phase 9) - "Monitoring simulation on a
historical public benchmark", never a real production monitoring system.

Reads a registered model candidate/challenger (`credlens.modeling.
registry`) and the UCI benchmark's own locked test set to build a
reference distribution and 12 simulated batches, then computes data
quality, drift, score, performance, and subgroup diagnostics against
locally calibrated (never market-generic) alert thresholds. Alerts are
local, structured records - never emailed, never posted to Slack/a
webhook, never acted on automatically.
"""

from __future__ import annotations
