# Security Policy

CredLens is a public portfolio project built around a fictional company. It does not process real customer or financial data. That said, the same discipline that would apply to a production credit system applies here.

## Reporting a vulnerability

- **Do not open a public issue for a security vulnerability that could realistically be exploited.** Public issues are appropriate for general bugs, not for anything involving credential exposure, injection vulnerabilities, or similar risks.
- Instead, report it privately to the maintainer through the repository's private vulnerability reporting feature (GitHub Security Advisories), if enabled, or by contacting the maintainer directly through the contact information on their GitHub profile.
- Include enough detail to reproduce the issue: affected file/component, steps, and impact.

## Rules for contributors and users

- **Never commit credentials.** No API keys, database passwords, tokens, or connection strings — not even "temporary" ones, not even in a comment. `.env.example` documents variable *names* only; real values belong in a local, git-ignored `.env` or in a secrets manager, never in the repository.
- **Never submit real personal or financial data.** This project's data strategy (`docs/data_strategy.md`) is public data plus reproducible synthetic data, specifically so that no real customer or bank-account data ever needs to enter the repository. If you're extending this project, keep it that way.
- **Audit any dataset before committing anything related to it.** Even a "sample" or "preview" of a dataset can contain sensitive fields, license restrictions, or embedded credentials (e.g., in Jupyter notebook outputs). Check licenses and contents before anything derived from a dataset is versioned — and remember `data/` is git-ignored by default for exactly this reason (see `.gitignore` and `data/README.md`).
- **Treat `.pbix`, notebook outputs, and cache directories as potential leak vectors.** Power BI files, notebook checkpoints, and cache directories can silently embed data or credentials. These are excluded via `.gitignore`; don't force-add them.

## Dependency hygiene

- Runtime dependencies are kept deliberately minimal (see `pyproject.toml`); each addition should have a clear reason.
- `uv.lock` pins resolved versions for reproducibility. If you update a dependency, regenerate the lock intentionally (`uv lock`) rather than hand-editing it.

## Scope note

Because this project does not handle real user data or run a live service, its security surface is small: primarily source code integrity and the discipline of never introducing real sensitive data. This document will be revisited if a future phase (e.g., a deployed demo app) changes that.
