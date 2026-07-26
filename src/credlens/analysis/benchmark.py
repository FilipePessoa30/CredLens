"""Public-dataset benchmark appendix (Phase 6 section 14) - profiles the
already-acquired, already-audited public sources (UCI Default of Credit
Card Clients, South German Credit, BCB SGS series) completely SEPARATELY
from the synthetic operational analysis. Never merges a public record
with a synthetic customer, never treats the public target as a CredLens
result, never claims Brazilian-population representativeness for
datasets whose own documentation says otherwise (Taiwan 2005, Germany
1973-1975).

Reuses `credlens.data.audit.audit_dataframe` (Phase 2) - this module does
not reimplement structural profiling, it loads the manifested files and
calls the same audit code `credlens data audit` uses.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from credlens.data.audit import audit_dataframe
from credlens.data.manifest import read_manifest

_MANIFEST_PATH = Path("data/metadata/file_manifest.csv")

# Provenance context each source's own documentation records - never
# inferred, always the acquisition-time record (docs/data_licensing.md,
# docs/dataset_selection.md).
_SOURCE_CONTEXT: dict[str, dict[str, str]] = {
    "uci-default-credit": {
        "population": "Credit card clients, Taiwan",
        "period": "2005",
        "target": "default payment next month (binary)",
        "license": "CC BY 4.0",
    },
    "south-german-credit": {
        "population": "Credit applicants, Germany",
        "period": "1973-1975 (correction/republication donated 2019)",
        "target": "kredit (credit risk, binary)",
        "license": "CC BY 4.0",
    },
    "bcb-sgs-20570": {
        "population": "Brazil, aggregate banking system",
        "period": "2015-present (monthly)",
        "target": "n/a - a macro time series, not a labeled credit dataset",
        "license": "ODbL",
    },
    "bcb-sgs-21112": {
        "population": "Brazil, aggregate banking system",
        "period": "2015-present (monthly)",
        "target": "n/a - a macro time series, not a labeled credit dataset",
        "license": "ODbL",
    },
}


@dataclass(frozen=True)
class BenchmarkProfile:
    source_id: str
    num_rows: int
    num_columns: int
    missing_value_findings: int
    domain_findings: int
    context: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "num_rows": self.num_rows,
            "num_columns": self.num_columns,
            "missing_value_findings": self.missing_value_findings,
            "domain_findings": self.domain_findings,
            "context": self.context,
        }


def _load_uci_default_credit(repo_root: Path, entries: list[Any]) -> pd.DataFrame:
    entry = next((e for e in entries if e.filename.endswith(".csv")), None)
    if entry is None:
        raise FileNotFoundError("No .csv manifest entry for uci-default-credit.")
    return pd.read_csv(repo_root / entry.relative_path)


def _load_south_german_credit(repo_root: Path, entries: list[Any]) -> pd.DataFrame:
    entry = next((e for e in entries if e.filename.endswith(".asc")), None)
    if entry is None:
        raise FileNotFoundError("No .asc manifest entry for south-german-credit.")
    return pd.read_csv(repo_root / entry.relative_path, sep=r"\s+")


def _load_bcb_series(repo_root: Path, entries: list[Any]) -> pd.DataFrame:
    entry = next((e for e in entries if e.filename.endswith(".json")), None)
    if entry is None:
        raise FileNotFoundError("No .json manifest entry for this BCB series.")
    raw = json.loads((repo_root / entry.relative_path).read_text(encoding="utf-8"))
    return pd.DataFrame(raw)


_LOADERS = {
    "uci-default-credit": _load_uci_default_credit,
    "south-german-credit": _load_south_german_credit,
}


def profile_public_sources(repo_root: Path | None = None) -> list[BenchmarkProfile]:
    """Profiles every acquired public source with a known loader.
    Silently SKIPS (does not raise) a source with no acquired files yet -
    the benchmark appendix is optional, never a hard requirement of the
    analysis run (Phase 6 section 14: "somente se os arquivos e manifests
    forem encontrados e passarem na verificação")."""
    repo_root = repo_root or Path.cwd()
    manifest_path = repo_root / _MANIFEST_PATH
    if not manifest_path.is_file():
        return []

    entries = read_manifest(manifest_path)
    entries_by_source: dict[str, list[Any]] = {}
    for entry in entries:
        entries_by_source.setdefault(entry.source_id, []).append(entry)

    profiles: list[BenchmarkProfile] = []
    for source_id, source_entries in sorted(entries_by_source.items()):
        if source_id.startswith("bcb-sgs-"):
            try:
                df = _load_bcb_series(repo_root, source_entries)
            except (FileNotFoundError, ValueError):
                continue
            report = audit_dataframe(df, source_id=source_id)
        elif source_id in _LOADERS:
            try:
                df = _LOADERS[source_id](repo_root, source_entries)
            except (FileNotFoundError, ValueError):
                continue
            report = audit_dataframe(
                df,
                source_id=source_id,
                documented_no_missing_values=(
                    source_id in ("uci-default-credit", "south-german-credit")
                ),
            )
        else:
            continue

        findings_by_category: dict[str, int] = {}
        for finding in report.findings:
            findings_by_category[finding.category] = (
                findings_by_category.get(finding.category, 0) + 1
            )

        profiles.append(
            BenchmarkProfile(
                source_id=source_id,
                num_rows=report.profile.num_rows,
                num_columns=report.profile.num_columns,
                missing_value_findings=findings_by_category.get("missing_values", 0),
                domain_findings=findings_by_category.get("domain", 0),
                context=_SOURCE_CONTEXT.get(source_id, {}),
            )
        )
    return profiles
