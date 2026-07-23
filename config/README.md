# config/

Configuration for the CredLens application.

## Files

- `base.yaml` — the default configuration loaded by `credlens.config`.
  It contains only structural, non-sensitive settings: project metadata,
  environment name, logging level, and logical (not absolute, not
  credentialed) paths. See the file itself for the current schema.

## What does NOT belong here

- Credentials, API keys, tokens, or connection strings — those are
  environment variables, documented (by name only) in `.env.example` at
  the repository root, never committed as real values.
- Business thresholds presented as ground truth (approval cutoffs,
  delinquency limits, pricing parameters). Until such values are derived
  from real analysis in a later phase, they do not belong in a config
  file that implies they are already validated.
- Environment-specific overrides with real infrastructure details
  (hostnames, ports, credentials for staging/production). Those would be
  supplied via environment variables or a git-ignored local override
  file in a future phase, not committed here.

## Loading behavior

`credlens.config.load_config()` reads `config/base.yaml` by default and
validates that the required keys are present and well-typed. See
`src/credlens/config.py` for the implementation and
`docs/architecture.md` for how configuration fits into the broader
system.
