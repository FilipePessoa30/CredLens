"""Loads the UCI Default of Credit Card Clients benchmark for modeling -
NEVER downloads it, NEVER mixes it with any other source.

The file must already be acquired and registered in
`data/metadata/file_manifest.csv` (Phase 2's `credlens data fetch`) - this
module only reads what is already on disk and re-verifies its hash against
the manifest before anything else touches it (Phase 8 section 3/4: "já
estar adquirida... não ser baixada novamente sem necessidade").
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from credlens.data.audit import audit_dataframe
from credlens.data.checksums import compute_sha256
from credlens.data.manifest import ManifestError, read_manifest

SOURCE_ID = "uci-default-credit"
_MANIFEST_PATH = Path("data/metadata/file_manifest.csv")


class DataAcquisitionError(Exception):
    """Raised when the UCI benchmark is missing, unregistered, or tampered."""


@dataclass(frozen=True)
class DatasetAudit:
    source_id: str
    num_rows: int
    num_columns: int
    sha256: str
    target_prevalence: float
    target_positive_count: int
    target_negative_count: int
    total_missing_values: int
    duplicate_id_count: int
    duplicate_row_count: int
    out_of_domain_education_count: int
    out_of_domain_marriage_count: int
    structural_findings: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "num_rows": self.num_rows,
            "num_columns": self.num_columns,
            "sha256": self.sha256,
            "target_prevalence": round(self.target_prevalence, 6),
            "target_positive_count": self.target_positive_count,
            "target_negative_count": self.target_negative_count,
            "total_missing_values": self.total_missing_values,
            "duplicate_id_count": self.duplicate_id_count,
            "duplicate_row_count": self.duplicate_row_count,
            "out_of_domain_education_count": self.out_of_domain_education_count,
            "out_of_domain_marriage_count": self.out_of_domain_marriage_count,
            "structural_findings": self.structural_findings,
        }


def _manifest_entry(repo_root: Path) -> Any:
    manifest_path = repo_root / _MANIFEST_PATH
    try:
        entries = read_manifest(manifest_path)
    except ManifestError as exc:
        raise DataAcquisitionError(
            f"No file manifest at '{manifest_path}' - run 'credlens data fetch "
            f"--source {SOURCE_ID}' first (Phase 2). The modeling layer never "
            "downloads data itself."
        ) from exc
    entry = next(
        (e for e in entries if e.source_id == SOURCE_ID and e.filename.endswith(".csv")),
        None,
    )
    if entry is None:
        raise DataAcquisitionError(
            f"No manifest entry for source '{SOURCE_ID}' - it must be fetched via "
            "'credlens data fetch' before it can be used for modeling."
        )
    return entry


def load_uci_default_credit(repo_root: Path | None = None) -> pd.DataFrame:
    """Reads the acquired UCI CSV directly off disk, verifying its hash
    against the manifest first. Raises `DataAcquisitionError` on any
    mismatch or missing file - never silently re-downloads or repairs."""
    repo_root = repo_root or Path.cwd()
    entry = _manifest_entry(repo_root)
    file_path = repo_root / entry.relative_path
    if not file_path.is_file():
        raise DataAcquisitionError(
            f"Manifest references '{file_path}' but the file is not on disk. "
            "Re-run 'credlens data fetch' - the modeling layer will not download it."
        )
    actual_hash = compute_sha256(file_path)
    if actual_hash.lower() != entry.sha256.lower():
        raise DataAcquisitionError(
            f"Hash mismatch for '{file_path}': manifest says {entry.sha256}, "
            f"file is actually {actual_hash}. Refusing to model on a tampered/corrupted source."
        )
    return pd.read_csv(file_path)


def audit_source(repo_root: Path | None = None) -> DatasetAudit:
    """Reproduces, as data, the numbers `docs/data_quality_audit.md`
    already reports by hand for uci-default-credit - registered once per
    modeling run so a report can point at a live number, not a copied one."""
    repo_root = repo_root or Path.cwd()
    entry = _manifest_entry(repo_root)
    df = load_uci_default_credit(repo_root)

    report = audit_dataframe(
        df,
        source_id=SOURCE_ID,
        documented_no_missing_values=True,
        known_id_columns=("ID",),
    )

    education_domain = {1, 2, 3, 4}
    marriage_domain = {1, 2, 3}

    return DatasetAudit(
        source_id=SOURCE_ID,
        num_rows=len(df),
        num_columns=len(df.columns),
        sha256=entry.sha256,
        target_prevalence=float(df["Y"].mean()),
        target_positive_count=int((df["Y"] == 1).sum()),
        target_negative_count=int((df["Y"] == 0).sum()),
        total_missing_values=int(df.isna().sum().sum()),
        duplicate_id_count=int(df["ID"].duplicated().sum()),
        duplicate_row_count=int(df.duplicated().sum()),
        out_of_domain_education_count=int((~df["X3"].isin(education_domain)).sum()),
        out_of_domain_marriage_count=int((~df["X4"].isin(marriage_domain)).sum()),
        structural_findings=len(report.findings),
    )
