# Kaggle — Home Credit Default Risk — license status: UNVERIFIED / BLOCKED

Unlike the other four sources in this registry, this dataset's license
was **not** independently confirmed in Phase 2, and no file was
downloaded. This note records what was attempted and why the source is
marked `BLOCKED_REQUIRES_USER_ACCESS` in `data/metadata/source_registry.yaml`.

## What was checked

- `curl` against `kaggle.com/competitions/home-credit-default-risk/rules`,
  `.../data`, and `.../overview` on 2026-07-23: each returned only a
  ~5.6 KB client-side-rendered application shell (verified by inspecting
  the raw HTML byte count and content — no rules text, file list, or
  license statement is present in the server response).
- A `WebFetch`-based attempt to read the rendered page content for the
  same URLs returned only the page `<title>` tag, for the same reason:
  the actual content is rendered client-side by JavaScript after
  authentication-aware page load, which a non-interactive fetch cannot
  execute.

## Why this is treated as blocked, not merely "unclear"

Kaggle's platform-wide, publicly documented model for competition data
(independent of this specific competition's exact rules text, which
could not be retrieved) requires, at minimum:

1. A Kaggle account, signed in.
2. Explicitly accepting that competition's rules before any download is
   permitted.
3. For programmatic/API access, a personal API token (`kaggle.json`)
   generated from the user's own Kaggle account settings.

None of these were available in this session, and per this project's
explicit rules (see `docs/data_licensing.md` and `SECURITY.md`):

- Credentials are never embedded in code, config, or committed files.
- The user is never asked to paste a token into chat.
- Authentication is never bypassed.
- A missing/unclear license is never treated as implicit permission to
  download or redistribute.

## What would need to happen to unblock this source

A human with a Kaggle account would need to: sign in, read and accept the
competition's actual current rules (which may have changed since this
dataset was created), generate a personal API token, and place it at
`~/.kaggle/kaggle.json` (never inside this repository) or in local,
git-ignored environment variables named in `.env.example`
(`KAGGLE_USERNAME`, `KAGGLE_KEY`). Only after that could
`credlens data fetch --source home-credit` be attempted — and the CLI
still refuses to fetch it today; see `src/credlens/cli.py`.
