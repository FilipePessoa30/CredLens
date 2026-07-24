# scripts/

This directory is a placeholder, kept empty on purpose in Phase 2.

Every data-acquisition, verification, and audit operation this phase needed is exposed as a proper, tested CLI command instead of a standalone script:

```bash
credlens data sources
credlens data fetch --source <id>
credlens data verify
credlens data audit
```

See `src/credlens/cli.py` and `src/credlens/data/` for the implementation, and `docs/data_sources.md` for what each command does. A one-off standalone script would have duplicated logic already covered by tested CLI code, and would not have been covered by `tests/test_data_cli.py`.

This directory remains reserved for a future phase's genuinely one-off utilities (e.g., a migration or a manual backfill) that don't belong in the permanent CLI surface - it is not populated with a placeholder file just to appear complete.
