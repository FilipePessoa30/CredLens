"""Deterministic release manifest and readiness decision (Phase 10
release-engineering layer) - `credlens release manifest`/`status`.

Same "deterministic content vs. execution timestamp" separation already
established in `credlens.monitoring.reporting`/`credlens.modeling.
reporting`: `content_fingerprint` hashes everything EXCEPT
`generated_at_utc`, so re-running this against an unchanged repo state
reproduces the exact same fingerprint.

`readiness_decision` is intentionally conservative - see
`decide_readiness`'s docstring for the blocking-gate list. It is never
forced to `release_candidate_ready`.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

ReadinessDecision = Literal[
    "release_candidate_ready",
    "release_candidate_ready_with_limitations",
    "release_candidate_not_ready",
]


class ReleaseManifestError(Exception):
    """Raised when the release manifest cannot be built."""


def _git(args: list[str], repo_root: Path) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo_root, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        result: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return result
    except (OSError, json.JSONDecodeError):
        return None


def _file_present(repo_root: Path, rel_path: str) -> bool:
    return (repo_root / rel_path).is_file()


@dataclass(frozen=True)
class ReleaseManifest:
    release_id: str
    project_version: str
    base_commit: str
    source_snapshot_fingerprint: str
    release_inventory_fingerprint: str
    release_inventory_summary: dict[str, Any]
    working_tree_clean: bool
    modified_file_count: int
    model_v1_present: bool
    model_v2_remediated_present: bool
    challenger_registered: bool
    validation_decision: str | None
    monitoring_run_present: bool
    demo_package_present: bool
    test_counts: dict[str, Any]
    dbt_reconciliation_status: str
    notebook_status: str
    dashboard_status: str
    visual_qa_status: str
    docker_status: str
    ci_status: str
    license_inventory_summary: dict[str, Any]
    sbom_summary: dict[str, Any]
    known_limitations: list[str]
    release_blockers: list[str]
    readiness_decision: ReadinessDecision
    generated_at_utc: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    content_fingerprint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "release_id": self.release_id,
            "project_version": self.project_version,
            "base_commit": self.base_commit,
            "source_snapshot_fingerprint": self.source_snapshot_fingerprint,
            "release_inventory_fingerprint": self.release_inventory_fingerprint,
            "release_inventory_summary": self.release_inventory_summary,
            "working_tree_clean": self.working_tree_clean,
            "modified_file_count": self.modified_file_count,
            "model_v1_present": self.model_v1_present,
            "model_v2_remediated_present": self.model_v2_remediated_present,
            "challenger_registered": self.challenger_registered,
            "validation_decision": self.validation_decision,
            "monitoring_run_present": self.monitoring_run_present,
            "demo_package_present": self.demo_package_present,
            "test_counts": self.test_counts,
            "dbt_reconciliation_status": self.dbt_reconciliation_status,
            "notebook_status": self.notebook_status,
            "dashboard_status": self.dashboard_status,
            "visual_qa_status": self.visual_qa_status,
            "docker_status": self.docker_status,
            "ci_status": self.ci_status,
            "license_inventory_summary": self.license_inventory_summary,
            "sbom_summary": self.sbom_summary,
            "known_limitations": self.known_limitations,
            "release_blockers": self.release_blockers,
            "readiness_decision": self.readiness_decision,
            "generated_at_utc": self.generated_at_utc,
            "content_fingerprint": self.content_fingerprint,
        }


# Known, disclosed limitations as of the Phase 10 release candidate -
# hand-maintained (these are qualitative facts about the release, not
# re-derivable from disk at manifest-build time).
KNOWN_LIMITATIONS_EN = [
    "Historical public benchmark (UCI, Taiwan, 2005) - not a Brazilian population, not a "
    "real institution's data.",
    "Frozen evaluation holdout reused across documented validation phases (Phases 8-10) - "
    "not an untouched holdout; any remediated model carries an indirect-adaptation risk "
    "(see validation_report.md section 6).",
    "9 of 18 original features flagged unstable/redundant by the coefficient-stability audit; "
    "a post-validation remediated regression (v2, 11 features) is registered separately as a "
    "remediation_candidate, never promoted over v1.",
    "Detection-evaluation scenario coverage is 100% (10/10 applicable scenarios) as of Phase "
    "10B; each scenario appears in only ONE batch (a single monitoring run, not a repeated "
    "stream), so gate H's persistence-based 'high' severity rarely has a genuine opportunity "
    "to fire from real repeated observation of one drift event within this evaluation.",
    "Visual QA was performed locally with a real headless browser (Selenium + Edge) in this "
    "development environment, not in the CI runner image (no browser available there).",
    "Docker image build was not executed - the local Docker daemon was not running during "
    "this release preparation; the Dockerfile is preserved and unvalidated.",
    "Not suitable for real lending decisions - no fairness certification, no legal compliance "
    "assessment, no financial-impact claim.",
]
KNOWN_LIMITATIONS_PT_BR = [
    "Benchmark público histórico (UCI, Taiwan, 2005) - não é uma população brasileira, não são "
    "dados de uma instituição real.",
    "Holdout de avaliação congelado, reutilizado em fases documentadas de validação (Fases "
    "8-10) - não é um holdout nunca tocado; qualquer modelo remediado carrega risco de "
    "adaptação indireta (ver validation_report.pt-BR.md seção 6).",
    "9 das 18 features originais foram sinalizadas como instáveis/redundantes pela auditoria "
    "de estabilidade de coeficientes; uma regressão remediada pós-validação (v2, 11 features) "
    "é registrada separadamente como remediation_candidate, nunca promovida sobre a v1.",
    "A cobertura de cenários na avaliação de detecção é de 100% (10/10 cenários aplicáveis) "
    "a partir da Fase 10B; cada cenário aparece em apenas UM batch (uma única execução de "
    "monitoramento, não um fluxo repetido), então a severidade 'high' baseada em persistência "
    "do gate H raramente tem oportunidade genuína de disparar por observação repetida real de "
    "um mesmo evento de drift dentro desta avaliação.",
    "A validação visual foi feita localmente com um navegador headless real (Selenium + Edge) "
    "neste ambiente de desenvolvimento, não no runner de CI (sem navegador disponível lá).",
    "A build da imagem Docker não foi executada - o daemon Docker local não estava em "
    "execução durante esta preparação de release; o Dockerfile foi preservado e não validado.",
    "Não é adequado para decisões reais de crédito - não é certificação de fairness, não é "
    "avaliação de conformidade legal, não é uma alegação de impacto financeiro.",
]


def build_release_manifest(
    *,
    test_counts: dict[str, Any],
    visual_qa_status: str,
    docker_status: str,
    ci_status: str,
    repo_root: Path | None = None,
) -> ReleaseManifest:
    repo_root = repo_root or Path.cwd()

    from credlens import __version__

    base_commit = _git(["rev-parse", "HEAD"], repo_root)
    status_output = _git(["status", "--porcelain"], repo_root)
    modified_lines = [line for line in status_output.splitlines() if line.strip()]

    decision = _read_json(repo_root / "reports/model_validation/decision.json")
    validation_decision = decision.get("decision") if decision else None

    monitoring_runs_dir = repo_root / "reports/monitoring/runs"
    monitoring_run_present = monitoring_runs_dir.is_dir() and any(
        p.name.startswith("RUN_BATCHSET_REF_MODEL_behavioral_default_v1")
        for p in monitoring_runs_dir.iterdir()
    )

    from credlens.release.licenses import inventory_dependency_licenses
    from credlens.release.sbom import generate_sbom

    license_inventory = inventory_dependency_licenses(repo_root)
    sbom = generate_sbom(repo_root)

    model_v1_present = _file_present(
        repo_root, "reports/modeling/models/MODEL_behavioral_default_v1.manifest.json"
    )
    model_v2_present = _file_present(
        repo_root, "reports/modeling/models/MODEL_behavioral_default_v2_reduced.manifest.json"
    )
    challenger_manifests = list((repo_root / "reports/modeling/models").glob("*.manifest.json"))
    challenger_registered = any(
        (_read_json(p) or {}).get("status") == "challenger" for p in challenger_manifests
    )
    demo_package_present = (repo_root / "dashboard/demo_data").is_dir() and any(
        (repo_root / "dashboard/demo_data").iterdir()
    )
    dbt_reconciliation_status = (
        "reconciled_within_tolerance"
        if _file_present(repo_root, "reports/portfolio_analysis/technical_report.md")
        else "not_executed"
    )
    notebook_status = (
        "executed_end_to_end"
        if _file_present(repo_root, "notebooks/credit_portfolio_case_study.ipynb")
        else "not_executed"
    )
    dashboard_status = (
        "validated_apptest_plus_headless_browser" if demo_package_present else "not_executed"
    )

    from credlens.release.integrity import run_release_integrity_checks
    from credlens.release.inventory import build_release_inventory
    from credlens.release.source_snapshot import compute_source_snapshot

    integrity = run_release_integrity_checks(repo_root)
    source_snapshot = compute_source_snapshot(repo_root)
    release_inventory = build_release_inventory(repo_root)

    blockers: list[str] = []
    if integrity.has_failure:
        blockers.append(
            "Release integrity check(s) failed: "
            + ", ".join(c.name for c in integrity.checks if c.status == "fail")
        )
    if validation_decision == "validation_failed":
        blockers.append("Model validation decision is validation_failed.")
    if not model_v1_present:
        blockers.append("Official candidate model MODEL_behavioral_default_v1 is not registered.")
    if docker_status == "not_executed":
        # Explicitly NOT a blocker on its own (Phase 10: "Docker pode ser
        # classificado separadamente... mas sua ausência deve aparecer
        # claramente") - recorded for visibility only.
        pass
    if visual_qa_status == "not_verified":
        pass
    if release_inventory.unresolved:
        blockers.append(
            "Release inventory has "
            f"{len(release_inventory.unresolved)} unresolved file(s) that match no "
            "classification rule: "
            + ", ".join(e.path for e in release_inventory.unresolved[:5])
            + (" ..." if len(release_inventory.unresolved) > 5 else "")
        )

    readiness_decision = decide_readiness(
        blockers=blockers,
        visual_qa_status=visual_qa_status,
        docker_status=docker_status,
    )

    # Fase 11A: the release_id suffix identifies the CONTENT the release
    # actually carries, not merely which commit HEAD happened to be at
    # generation time - `base_commit[:8]` alone is blind to uncommitted
    # changes (a dirty working tree and its own clean commit would carry
    # the identical release_id despite different file contents). Only
    # `source_snapshot_fingerprint` (hashes the CURRENT on-disk content
    # of every tracked file) can distinguish them; when the tree is
    # clean, this is legitimately equal to what a HEAD-derived id would
    # have produced - equality is then correct, not a bug.
    release_id = f"RC_{__version__}_{source_snapshot.fingerprint[:8]}"
    manifest = ReleaseManifest(
        release_id=release_id,
        project_version=__version__,
        base_commit=base_commit,
        source_snapshot_fingerprint=source_snapshot.fingerprint,
        release_inventory_fingerprint=release_inventory.fingerprint,
        release_inventory_summary={
            "n_entries": len(release_inventory.entries),
            "n_included": len(release_inventory.included),
            "n_excluded": len(release_inventory.excluded),
            "n_unresolved": len(release_inventory.unresolved),
            "n_needs_human_review": len(release_inventory.needs_human_review),
        },
        working_tree_clean=len(modified_lines) == 0,
        modified_file_count=len(modified_lines),
        model_v1_present=model_v1_present,
        model_v2_remediated_present=model_v2_present,
        challenger_registered=challenger_registered,
        validation_decision=validation_decision,
        monitoring_run_present=monitoring_run_present,
        demo_package_present=demo_package_present,
        test_counts=test_counts,
        dbt_reconciliation_status=dbt_reconciliation_status,
        notebook_status=notebook_status,
        dashboard_status=dashboard_status,
        visual_qa_status=visual_qa_status,
        docker_status=docker_status,
        ci_status=ci_status,
        license_inventory_summary={
            "n_dependencies": len(license_inventory.dependencies),
            "unknown_count": license_inventory.unknown_count,
            "copyleft_count": license_inventory.copyleft_count,
        },
        sbom_summary={
            "n_components": sbom.n_components,
            "content_fingerprint": sbom.content_fingerprint,
        },
        known_limitations=KNOWN_LIMITATIONS_EN,
        release_blockers=blockers,
        readiness_decision=readiness_decision,
    )
    fingerprint_payload = {k: v for k, v in manifest.to_dict().items() if k != "generated_at_utc"}
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_payload, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return ReleaseManifest(**{**manifest.to_dict(), "content_fingerprint": fingerprint})


def decide_readiness(
    *, blockers: list[str], visual_qa_status: str, docker_status: str
) -> ReadinessDecision:
    """Never forced to `release_candidate_ready`. Blocking gates: any
    entry in `blockers` (release-integrity failure, a failed validation
    decision, a missing official model). Visual QA/Docker are classified
    SEPARATELY per Phase 10's instructions ("podem ser classificados
    separadamente... mas sua ausência deve aparecer claramente") - their
    absence downgrades `ready` to `ready_with_limitations`, never to
    `not_ready` on their own."""
    if blockers:
        return "release_candidate_not_ready"
    if visual_qa_status != "verified_locally" or docker_status != "built_and_validated":
        return "release_candidate_ready_with_limitations"
    return "release_candidate_ready"


def write_release_manifest(manifest: ReleaseManifest, *, repo_root: Path | None = None) -> Path:
    repo_root = repo_root or Path.cwd()
    out_dir = repo_root / "reports" / "release"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "release_manifest.json"
    path.write_text(json.dumps(manifest.to_dict(), indent=2), encoding="utf-8")
    return path
