"""Model Lab page - thin entrypoint, see
`credlens.dashboard.model_lab.render_model_lab` for the composition
logic. Historical public benchmark (UCI, Taiwan, 2005) - completely
separate from the synthetic portfolio pages; does not need
`credlens_data`, it reads directly from `reports/modeling/`."""

from __future__ import annotations

from credlens.dashboard.model_lab import render_model_lab

render_model_lab()
