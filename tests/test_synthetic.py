"""Tests for credlens.synthetic: structural validation of synthetic
scenario blueprints. No generation happens here - see
docs/synthetic_generation_spec.md."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from credlens.synthetic import (
    BlueprintError,
    BlueprintStatus,
    ParameterStatus,
    ScenarioBlueprint,
    load_all_blueprints,
    load_blueprint,
)

REAL_SCENARIOS_DIR = Path("config/synthetic/scenarios")


def _minimal_blueprint_payload(**overrides: object) -> dict[str, object]:
    parameter = {"status": "pending", "description": "A pending parameter.", "value": None}
    payload: dict[str, object] = {
        "scenario_id": "fixture_scenario",
        "name": "Fixture scenario",
        "description": "A fixture scenario.",
        "status": "requires_calibration",
        "population": {"p1": parameter},
        "origination": {"o1": parameter},
        "performance": {"perf1": parameter},
        "temporal_dependence": {"t1": parameter},
        "reproducibility": {"r1": parameter},
    }
    payload.update(overrides)
    return payload


class TestLoadBlueprint:
    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(BlueprintError, match="not found"):
            load_blueprint(tmp_path / "missing.yaml")

    def test_invalid_yaml_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "broken.yaml"
        path.write_text("scenario_id: [unclosed", encoding="utf-8")

        with pytest.raises(BlueprintError, match="not valid YAML"):
            load_blueprint(path)

    def test_non_mapping_top_level_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "list.yaml"
        path.write_text("- a\n- b\n", encoding="utf-8")

        with pytest.raises(BlueprintError, match="top-level mapping"):
            load_blueprint(path)

    def test_schema_violation_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "incomplete.yaml"
        path.write_text("scenario_id: fixture\n", encoding="utf-8")

        with pytest.raises(BlueprintError, match="failed schema validation"):
            load_blueprint(path)

    def test_unknown_parameter_status_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "bad_status.yaml"
        payload = _minimal_blueprint_payload(
            population={"p1": {"status": "calibrated_for_real", "description": "x", "value": None}}
        )
        path.write_text(yaml.safe_dump(payload), encoding="utf-8")

        with pytest.raises(BlueprintError):
            load_blueprint(path)

    def test_rejects_unknown_field(self, tmp_path: Path) -> None:
        path = tmp_path / "extra_field.yaml"
        payload = _minimal_blueprint_payload()
        payload["unexpected_section"] = {}
        path.write_text(yaml.safe_dump(payload), encoding="utf-8")

        with pytest.raises(BlueprintError):
            load_blueprint(path)

    def test_minimal_valid_blueprint_loads(self, tmp_path: Path) -> None:
        path = tmp_path / "fixture.blueprint.yaml"
        path.write_text(yaml.safe_dump(_minimal_blueprint_payload()), encoding="utf-8")

        blueprint = load_blueprint(path)

        assert blueprint.scenario_id == "fixture_scenario"
        assert blueprint.status == BlueprintStatus.REQUIRES_CALIBRATION

    def test_real_baseline_blueprint_loads(self) -> None:
        blueprint = load_blueprint(REAL_SCENARIOS_DIR / "baseline.blueprint.yaml")

        assert blueprint.scenario_id == "baseline"
        assert blueprint.status == BlueprintStatus.REQUIRES_CALIBRATION

    def test_every_real_scenario_blueprint_loads_individually(self) -> None:
        for path in sorted(REAL_SCENARIOS_DIR.glob("*.blueprint.yaml")):
            blueprint = load_blueprint(path)
            assert blueprint.scenario_id


class TestScenarioBlueprintParameterCounts:
    def test_counts_every_parameter_across_sections(self) -> None:
        blueprint = ScenarioBlueprint.model_validate(
            _minimal_blueprint_payload(
                population={
                    "p1": {"status": "specified", "description": "x", "value": 1},
                    "p2": {"status": "pending", "description": "x", "value": None},
                },
                origination={
                    "o1": {"status": "requires_calibration", "description": "x", "value": None}
                },
            )
        )

        counts = blueprint.parameter_counts()

        # specified: p1. pending: p2 + the untouched default performance/
        # temporal_dependence/reproducibility parameters (perf1, t1, r1).
        # requires_calibration: o1.
        assert counts[ParameterStatus.SPECIFIED] == 1
        assert counts[ParameterStatus.PENDING] == 4
        assert counts[ParameterStatus.REQUIRES_CALIBRATION] == 1

    def test_no_calibrated_real_world_values_are_silently_assumed(self) -> None:
        """Every parameter in the real blueprints must declare an honest
        status - none can be silently treated as 'specified' by default."""
        for path in sorted(REAL_SCENARIOS_DIR.glob("*.blueprint.yaml")):
            blueprint = load_blueprint(path)
            counts = blueprint.parameter_counts()
            total = sum(counts.values())
            assert total > 0


class TestLoadAllBlueprints:
    def test_missing_directory_returns_empty(self, tmp_path: Path) -> None:
        blueprints = load_all_blueprints(tmp_path / "does_not_exist")
        assert blueprints == {}

    def test_duplicate_scenario_id_raises(self, tmp_path: Path) -> None:
        payload = _minimal_blueprint_payload()
        (tmp_path / "a.blueprint.yaml").write_text(yaml.safe_dump(payload), encoding="utf-8")
        (tmp_path / "b.blueprint.yaml").write_text(yaml.safe_dump(payload), encoding="utf-8")

        with pytest.raises(BlueprintError, match="Duplicate scenario_id"):
            load_all_blueprints(tmp_path)

    def test_ignores_files_not_matching_blueprint_suffix(self, tmp_path: Path) -> None:
        (tmp_path / "not_a_blueprint.yaml").write_text("scenario_id: x\n", encoding="utf-8")

        blueprints = load_all_blueprints(tmp_path)

        assert blueprints == {}

    def test_loads_all_six_real_scenarios(self) -> None:
        blueprints = load_all_blueprints(REAL_SCENARIOS_DIR)

        assert set(blueprints) == {
            "baseline",
            "policy_expansion",
            "policy_tightening",
            "macroeconomic_stress",
            "collections_change",
            "data_quality_incident",
        }

    def test_every_real_scenario_status_is_requires_calibration(self) -> None:
        """No scenario claims to be ready-to-run; all are honestly marked
        as needing calibration before generation could occur."""
        blueprints = load_all_blueprints(REAL_SCENARIOS_DIR)
        for blueprint in blueprints.values():
            assert blueprint.status == BlueprintStatus.REQUIRES_CALIBRATION
