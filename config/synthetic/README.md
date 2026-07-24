# config/synthetic/

Blueprints for the future synthetic-generation scenarios described in `docs/synthetic_generation_spec.md`. **No generation code reads these yet** - `credlens synthetic generate` is explicitly not implemented in this phase (see `docs/roadmap.md` phase 4). What exists here is validated structurally by `credlens synthetic validate-blueprints` (`src/credlens/synthetic.py`).

## Files

- `schema.yaml` - human-readable description of the blueprint schema (the actual enforcement is the Pydantic model in `src/credlens/synthetic.py`; this file documents it for readers who aren't going to read the Python).
- `scenarios/*.blueprint.yaml` - one file per scenario named in `docs/synthetic_generation_spec.md`: `baseline`, `policy_expansion`, `policy_tightening`, `macroeconomic_stress`, `collections_change`, `data_quality_incident`.

## What a blueprint is (and is not)

A blueprint names every parameter a future generator run would need, and honestly states whether that parameter is:

- `specified` - a concrete choice has been made and recorded (with a `value`).
- `pending` - not designed yet; no value should be inferred from its absence.
- `requires_calibration` - a parameter that conceptually needs a real numeric value, but none is set here because no real-world benchmark or business decision backs one yet.

**Every blueprint's top-level `status` is `requires_calibration` or `draft` - never `calibrated` or `active` -** because none of them have been calibrated against anything. A blueprint is a structured checklist of decisions still to make, not a configuration ready to run. Treating a `requires_calibration` parameter as if it had a real value (e.g., assuming a 0% default rate because none is set) would be exactly the kind of fabrication this project's other documentation explicitly prohibits - see `docs/assumptions_and_limitations.md`.
