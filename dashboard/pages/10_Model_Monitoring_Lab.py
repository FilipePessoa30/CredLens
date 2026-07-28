"""Model Monitoring Lab page - thin entrypoint, see
`credlens.dashboard.monitoring_lab.render_monitoring_lab` for the
composition logic. Monitoring simulation on a historical public
benchmark (UCI, Taiwan, 2005) - completely separate from the synthetic
portfolio pages; does not need `credlens_data`, it reads directly from
`reports/monitoring/` and `reports/model_validation/`."""

from __future__ import annotations

from credlens.dashboard.monitoring_lab import render_monitoring_lab

render_monitoring_lab()
