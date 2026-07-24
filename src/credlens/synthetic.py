"""Structural validation for synthetic-generation scenario blueprints.

No generation happens here - see docs/synthetic_generation_spec.md and
`credlens synthetic generate`'s explicit "not implemented" response (Phase
3 scope). This module only validates that a blueprint YAML is well-formed
and reports every parameter's status (`specified` / `pending` /
`requires_calibration`) honestly - it never invents or assumes a
calibrated value on a blueprint's behalf.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

DEFAULT_SCENARIOS_DIR = Path("config/synthetic/scenarios")

_SECTIONS = ("population", "origination", "performance", "temporal_dependence", "reproducibility")


class ParameterStatus(StrEnum):
    SPECIFIED = "specified"
    PENDING = "pending"
    REQUIRES_CALIBRATION = "requires_calibration"


class BlueprintStatus(StrEnum):
    DRAFT = "draft"
    REQUIRES_CALIBRATION = "requires_calibration"


class BlueprintParameter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ParameterStatus
    description: str
    value: str | float | int | bool | None = None


class ScenarioBlueprint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    name: str
    description: str
    status: BlueprintStatus
    population: dict[str, BlueprintParameter]
    origination: dict[str, BlueprintParameter]
    performance: dict[str, BlueprintParameter]
    temporal_dependence: dict[str, BlueprintParameter]
    reproducibility: dict[str, BlueprintParameter]

    def parameter_counts(self) -> dict[ParameterStatus, int]:
        counts = dict.fromkeys(ParameterStatus, 0)
        for section in _SECTIONS:
            for parameter in getattr(self, section).values():
                counts[parameter.status] += 1
        return counts


class BlueprintError(Exception):
    """Raised when a blueprint file cannot be read, parsed, or validated."""


def load_blueprint(path: Path) -> ScenarioBlueprint:
    """Load and structurally validate one scenario blueprint YAML file.

    Raises:
        BlueprintError: missing file, invalid YAML, or a schema violation.
    """
    if not path.is_file():
        raise BlueprintError(f"Blueprint file not found at '{path}'.")

    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise BlueprintError(f"Could not read blueprint file '{path}': {exc}") from exc

    try:
        data = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        raise BlueprintError(f"Blueprint file '{path}' is not valid YAML: {exc}") from exc

    if not isinstance(data, dict):
        raise BlueprintError(f"Blueprint file '{path}' must contain a top-level mapping.")

    try:
        return ScenarioBlueprint.model_validate(data)
    except ValidationError as exc:
        raise BlueprintError(f"Blueprint file '{path}' failed schema validation:\n{exc}") from exc


def load_all_blueprints(directory: Path = DEFAULT_SCENARIOS_DIR) -> dict[str, ScenarioBlueprint]:
    """Load every `*.blueprint.yaml` file in `directory`.

    Raises:
        BlueprintError: a file fails to load, or two files share a scenario_id.
    """
    blueprints: dict[str, ScenarioBlueprint] = {}
    if not directory.is_dir():
        return blueprints

    for path in sorted(directory.glob("*.blueprint.yaml")):
        blueprint = load_blueprint(path)
        if blueprint.scenario_id in blueprints:
            raise BlueprintError(
                f"Duplicate scenario_id '{blueprint.scenario_id}' - "
                "already loaded from another file."
            )
        blueprints[blueprint.scenario_id] = blueprint

    return blueprints
