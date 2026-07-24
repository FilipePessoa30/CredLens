# Data Licensing

This document is the licensing summary for every source in `data/metadata/source_registry.yaml`. The primary evidence (full license text, exact citation requirements) lives in `data/metadata/licenses/`; this page indexes and summarizes it. CredLens's own code license (MIT) is separate from all of this - see the root `LICENSE` file and its note that third-party datasets remain subject to their own terms.

## Summary table

| Source | License | Status | Redistribution | Evidence |
|---|---|---|---|---|
| uci-default-credit | CC BY 4.0 | Verified | Allowed with attribution | `data/metadata/licenses/cc-by-4.0.md` |
| south-german-credit | CC BY 4.0 | Verified | Allowed with attribution | `data/metadata/licenses/cc-by-4.0.md` |
| home-credit | Unknown (Kaggle competition-specific) | **Not verified - BLOCKED** | Unknown | `data/metadata/licenses/kaggle-home-credit-notes.md` |
| bcb-sgs-20570 | ODbL 1.0 | Verified | Allowed, share-alike | `data/metadata/licenses/odbl-bcb-sgs.md` |
| bcb-sgs-21112 | ODbL 1.0 | Verified | Allowed, share-alike | `data/metadata/licenses/odbl-bcb-sgs.md` |

## uci-default-credit and south-german-credit — CC BY 4.0

Both were confirmed directly against UCI's own dataset API (`archive.ics.uci.edu/api/dataset?id=350` and `?id=522`) on 2026-07-23, which returns a structured `license` field alongside a `dataset_doi`. Both report **Creative Commons Attribution 4.0 International (CC BY 4.0)**. This permits sharing and adapting the data, including commercially, provided attribution is given - satisfied here by citing each dataset's DOI everywhere it's referenced (`data/metadata/source_registry.yaml`'s `citation` field, and this document). See `data/metadata/licenses/cc-by-4.0.md` for the full requirement text and the exact citation strings used.

## bcb-sgs-20570 and bcb-sgs-21112 — ODbL 1.0

Confirmed directly against each series' `dadosabertos.bcb.gov.br` dataset page on 2026-07-23, which displays an Open Definition-conformant license badge for the **Open Data Commons Open Database License (ODbL) v1.0**. ODbL requires attribution and, for substantially modified public redistributions, share-alike licensing of the modified database. CredLens satisfies attribution by citing the series (source, series code, URL) wherever referenced; no modified redistribution of these series happens in this phase. See `data/metadata/licenses/odbl-bcb-sgs.md`.

## home-credit — UNVERIFIED, BLOCKED_REQUIRES_USER_ACCESS

This is the one source in this registry whose license was **not** confirmed, and the reasoning matters enough to spell out precisely what was tried and why "we couldn't check" was treated as a block rather than an assumption of permission.

### What was attempted (2026-07-23)

1. `curl` against `kaggle.com/competitions/home-credit-default-risk/rules`, `.../data`, and `.../overview`. Each returned HTTP 200 with a **5,586-byte** response body - inspected directly, and confirmed to be a client-side-rendered application shell (a `<title>`, meta tags, and JavaScript bootstrapping code), containing no rules text, no file listing, and no license statement. This is a verifiable fact about the response, not a guess.
2. A `WebFetch`-based fetch of the same three URLs (which converts rendered HTML to markdown for reading) returned only each page's `<title>` tag, for the identical reason: there is nothing else in the server-rendered response to convert.

### Why this became BLOCKED rather than "proceed cautiously"

Two independent rules apply here, and both point the same direction:

- **This project's own rule** (see the Phase 2 brief and `SECURITY.md`): an unclear or unconfirmed license is never treated as implicit permission. Kaggle's platform-wide, publicly documented access model - independent of this specific competition's exact current rules text, which could not be retrieved - requires a signed-in account, explicit acceptance of that competition's rules, and (for any non-interactive/API access) a personal API token. None of these existed in this session, and this project will not create, request, or bypass any of them.
- **The practical evidence above**: even if this project were willing to guess at the license, there was no rules text available to guess from - the response literally does not contain it.

### What would unblock this source

A human with a Kaggle account would need to sign in, read and accept the competition's actual current rules, generate a personal API token, and place it outside this repository (a local `~/.kaggle/kaggle.json`, or environment variables named `KAGGLE_USERNAME`/`KAGGLE_KEY` in a git-ignored `.env` - see `.env.example`). `credlens data fetch --source home-credit` still refuses to run even then, until that CLI path is explicitly implemented in a future phase with real, verified rules text to comply with - see `data/metadata/licenses/kaggle-home-credit-notes.md`.

## Rule this document enforces going forward

No dataset is downloaded, retained, or cited in this project without a license recorded here first. If a future phase adds a source, its entry in `data/metadata/source_registry.yaml` and a corresponding note in `data/metadata/licenses/` are added in the same change that adds the acquisition code - not after the fact.
