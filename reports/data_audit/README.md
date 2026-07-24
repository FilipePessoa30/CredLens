# reports/data_audit/

Output of `uv run credlens data audit` - reproducible, code-generated, and safe to regenerate at any time (it never downloads anything; it only reads whatever is already in `data/raw/`).

## Files

- `quality_metrics.json` - the full, machine-readable audit report: one entry per audited source, each containing its structural profile (row/column counts, missing values, cardinality, min/max, etc.) and its categorized findings. This is a real, generated artifact from this session, not a template - see `docs/data_quality_audit.md` for the narrative read of it.
- `audit_summary.md` - a short, at-a-glance status table derived from `quality_metrics.json`.
- `source_comparison.md` - the four audited sources' structural characteristics placed side by side.

## Regenerating this directory

```bash
uv run credlens data audit
```

Requires the sources to already be acquired (`uv run credlens data fetch --source <id>` first) - this command deliberately never downloads data itself, per `docs/architecture.md`'s separation between ingestion and quality/audit responsibilities.

## What NOT to read into these numbers

Every count and percentage in this directory is a **technical fact about a specific public benchmark dataset**, not a business finding. See `docs/data_quality_audit.md`'s note on class-balance figures, and `docs/assumptions_and_limitations.md` generally, before citing anything here as if it described a real portfolio.
