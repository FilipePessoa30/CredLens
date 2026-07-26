"""Portfolio analysis layer (Phase 6): turns a validated warehouse build
into a reproducible, SQL-first analysis - business questions, paired
scenario comparisons, multi-seed robustness, visualizations, and bilingual
reports. Everything here reads from an already-built warehouse
(`credlens.warehouse`) - this package computes nothing a dbt model could
compute instead; it queries, validates, charts, and narrates.
"""

from __future__ import annotations
