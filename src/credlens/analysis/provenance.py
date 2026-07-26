"""Analysis run provenance manifest (Phase 6 section 18) - what build,
what queries, what figures, what hashes, what versions produced a given
analysis output. Written once per `credlens analysis run` invocation to
`reports/portfolio_analysis/manifest.json` (or an injected output dir in
tests - Phase 6 gate B applies here too, see
`credlens.generation.testing_support`).
"""

from __future__ import annotations

import hashlib
import json
import platform
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from credlens import __version__ as credlens_version
from credlens.warehouse.build import BuildManifest


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass
class AnalysisManifest:
    analysis_id: str
    build_id: str
    warehouse_fingerprint: str
    suite_id: str | None
    run_ids: list[str]
    source_hashes: dict[str, str]
    generator_version: str
    contract_version_sets: list[str]
    package_version: str
    dbt_version: str
    duckdb_version: str
    python_version: str
    started_at: str
    finished_at: str | None
    queries_executed: list[str]
    tables_written: dict[str, str]
    figures_written: dict[str, str]
    warnings: list[str]
    final_status: str
    # The exact run_analysis() keyword arguments used - required so
    # `credlens analysis reproduce` can replay an identical invocation
    # (Phase 6 section 18: manifest must record "parameters").
    parameters: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis_id": self.analysis_id,
            "build_id": self.build_id,
            "warehouse_fingerprint": self.warehouse_fingerprint,
            "suite_id": self.suite_id,
            "run_ids": self.run_ids,
            "source_hashes": self.source_hashes,
            "generator_version": self.generator_version,
            "contract_version_sets": self.contract_version_sets,
            "package_version": self.package_version,
            "dbt_version": self.dbt_version,
            "duckdb_version": self.duckdb_version,
            "python_version": self.python_version,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "queries_executed": self.queries_executed,
            "tables_written": self.tables_written,
            "figures_written": self.figures_written,
            "warnings": self.warnings,
            "final_status": self.final_status,
            "parameters": self.parameters,
        }

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True), encoding="utf-8")


def new_manifest(
    build: BuildManifest, analysis_id: str, parameters: dict[str, Any] | None = None
) -> AnalysisManifest:
    source_hashes = {str(s["run_id"]): str(s.get("global_content_hash", "")) for s in build.sources}
    contract_version_sets = sorted({str(s.get("contract_version_set", "")) for s in build.sources})
    generator_versions = sorted({str(s.get("generator_version", "")) for s in build.sources})
    return AnalysisManifest(
        analysis_id=analysis_id,
        build_id=build.build_id,
        warehouse_fingerprint=build.analytical_fingerprint,
        suite_id=build.suite_id,
        run_ids=list(build.included_run_ids),
        source_hashes=source_hashes,
        generator_version=",".join(generator_versions),
        contract_version_sets=contract_version_sets,
        package_version=credlens_version,
        dbt_version=build.dbt_version,
        duckdb_version=build.duckdb_version,
        python_version=platform.python_version(),
        started_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        finished_at=None,
        queries_executed=[],
        tables_written={},
        figures_written={},
        warnings=[],
        final_status="running",
        parameters=dict(parameters) if parameters is not None else {},
    )


def record_table(manifest: AnalysisManifest, name: str, path: Path) -> None:
    manifest.tables_written[name] = _file_sha256(path) if path.is_file() else "missing"


def record_figure(manifest: AnalysisManifest, name: str, path: Path) -> None:
    manifest.figures_written[name] = _file_sha256(path) if path.is_file() else "missing"


def finalize(manifest: AnalysisManifest, *, status: str) -> None:
    manifest.finished_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest.final_status = status
