"""Append-only release errata log (Phase 10B - Release Candidate
Acceptance Remediation).

`credlens.release.manifest.decide_readiness` (Phase 10) only checked a
narrow set of blockers (release-integrity check failures, a
`validation_failed` model decision, a missing official model artifact).
It never enforced a minimum test-coverage percentage or a minimum
monitoring-detection rate against `RC_1.0.0rc1_bc33e939`'s own real,
measured numbers (94% coverage, 50% scenario-detection rate) - so
`release_candidate_ready_with_limitations` with `release_blockers: []`
was an incomplete acceptance decision, not a false one: every check that
existed passed, but the check set itself was too narrow.

This module NEVER deletes or overwrites `release_manifest.json` or any
prior errata entry - it only appends a new, dated correction, exactly
like `credlens.model_validation.lifecycle`'s append-only transition
history. The original decision remains readable forever.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ERRATA_PATH = Path("reports/release/release_errata.json")


class ReleaseErrataError(Exception):
    """Raised when a release errata entry cannot be built or written."""


@dataclass(frozen=True)
class ReleaseErrataEntry:
    errata_id: str
    release_id: str
    original_decision: str
    corrected_decision: str
    blockers: list[str]
    reason_en: str
    reason_pt_br: str
    evidence: dict[str, Any]
    incomplete_rule_en: str
    incomplete_rule_pt_br: str
    corrected_at_utc: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "errata_id": self.errata_id,
            "release_id": self.release_id,
            "original_decision": self.original_decision,
            "corrected_decision": self.corrected_decision,
            "blockers": self.blockers,
            "reason_en": self.reason_en,
            "reason_pt_br": self.reason_pt_br,
            "evidence": self.evidence,
            "incomplete_rule_en": self.incomplete_rule_en,
            "incomplete_rule_pt_br": self.incomplete_rule_pt_br,
            "corrected_at_utc": self.corrected_at_utc,
        }


def build_rc1_acceptance_errata(
    *, measured_coverage_percent: float, measured_scenario_detection_rate: float
) -> ReleaseErrataEntry:
    """Documents the specific, real gap found in Fase 10B: `RC_1.0.0rc1_
    bc33e939` was declared `release_candidate_ready_with_limitations`
    with real coverage at `measured_coverage_percent`% (below the 95%
    acceptance bar this errata now makes an enforced, coded blocker) and
    a real `scenario_detection_rate` of `measured_scenario_detection_rate`
    (below the 90% acceptance bar this errata now makes an enforced,
    coded blocker in `credlens.monitoring.detection_eval`/
    `credlens.release.manifest`)."""
    blockers = [
        "coverage_below_required_threshold",
        "monitoring_detection_below_required_threshold",
        "release_gate_did_not_enforce_acceptance_criteria",
    ]
    return ReleaseErrataEntry(
        errata_id="ERRATA_RC_1.0.0rc1_bc33e939_001",
        release_id="RC_1.0.0rc1_bc33e939",
        original_decision="release_candidate_ready_with_limitations",
        corrected_decision="release_candidate_not_ready",
        blockers=blockers,
        reason_en=(
            f"Real measured coverage was {measured_coverage_percent:.0f}% (below the 95% "
            f"acceptance bar formalized in this errata) and the real monitoring "
            f"scenario_detection_rate was {measured_scenario_detection_rate:.2f} (below the 90% "
            "acceptance bar formalized in this errata: missingness_drift, out_of_domain_codes, "
            "feature_range_violation, prevalence_drift, and subgroup_composition_shift were "
            "profiled by the pipeline but never turned into an Alert, so they could never be "
            "detected by credlens.monitoring.detection_eval). The original "
            "release_candidate_ready_with_limitations decision was not fabricated - every check "
            "that existed at the time passed - but the check set itself did not enforce a "
            "coverage or detection-rate acceptance bar at all, so 'zero blockers' did not mean "
            "'meets every acceptance criterion'."
        ),
        reason_pt_br=(
            f"A cobertura real medida era {measured_coverage_percent:.0f}% (abaixo da barra de "
            f"aceite de 95% formalizada por esta errata) e a taxa real de "
            f"scenario_detection_rate do monitoramento era {measured_scenario_detection_rate:.2f} "
            "(abaixo da barra de aceite de 90% formalizada por esta errata: missingness_drift, "
            "out_of_domain_codes, feature_range_violation, prevalence_drift e "
            "subgroup_composition_shift eram perfilados pelo pipeline mas nunca viravam um "
            "Alert, portanto nunca podiam ser detectados por "
            "credlens.monitoring.detection_eval). A decisão original "
            "release_candidate_ready_with_limitations não foi fabricada - toda checagem que "
            "existia na época passou - mas o próprio conjunto de checagens não impunha nenhuma "
            "barra de aceite de cobertura ou taxa de detecção, então 'zero blockers' não "
            "significava 'atende a todo critério de aceite'."
        ),
        evidence={
            "coverage_report": "reports/release/rc1_coverage_at_errata_time.json",
            "detection_report": "reports/release/rc1_detection_at_errata_time.json",
            "measured_coverage_percent": measured_coverage_percent,
            "measured_scenario_detection_rate": measured_scenario_detection_rate,
            "original_manifest": "reports/release/release_manifest.json",
        },
        incomplete_rule_en=(
            "credlens.release.manifest.decide_readiness (Phase 10) only checked "
            "integrity.has_failure, validation_decision == 'validation_failed', and "
            "model_v1_present - it never read a coverage report or a detection-evaluation "
            "report at all, so no numeric coverage or detection floor could ever become a "
            "release_blockers entry."
        ),
        incomplete_rule_pt_br=(
            "credlens.release.manifest.decide_readiness (Fase 10) checava apenas "
            "integrity.has_failure, validation_decision == 'validation_failed' e "
            "model_v1_present - nunca lia um relatório de cobertura nem um relatório de "
            "avaliação de detecção, portanto nenhum piso numérico de cobertura ou detecção "
            "podia jamais virar uma entrada de release_blockers."
        ),
        corrected_at_utc=datetime.now(UTC).isoformat(),
    )


def write_release_errata(entry: ReleaseErrataEntry, *, repo_root: Path | None = None) -> Path:
    """Appends `entry` to `reports/release/release_errata.json` - creates
    the file with a single-entry list if it does not exist yet, otherwise
    appends to the existing list. Never overwrites an existing entry."""
    repo_root = repo_root or Path.cwd()
    path = repo_root / ERRATA_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: list[dict[str, Any]] = []
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ReleaseErrataError(f"Existing errata file at '{path}' is corrupt.") from exc
    existing.append(entry.to_dict())
    path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    return path


def load_release_errata(*, repo_root: Path | None = None) -> list[dict[str, Any]]:
    repo_root = repo_root or Path.cwd()
    path = repo_root / ERRATA_PATH
    if not path.is_file():
        return []
    result: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
    return result
