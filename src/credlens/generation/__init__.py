"""Deterministic synthetic-portfolio generation (Phase 4A: baseline scenario only).

See docs/synthetic_generation_implementation.md for the full design. No
other scenario (policy_expansion, policy_tightening, macroeconomic_stress,
collections_change, data_quality_incident) is implemented here - each
remains `requires_calibration` and is rejected by orchestrator.generate().
"""
