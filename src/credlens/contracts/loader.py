"""Load a single contract YAML file into a validated DataContract."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from credlens.contracts.models import DataContract


class ContractError(Exception):
    """Raised when a contract file cannot be read, parsed, or validated."""


def load_contract(path: Path) -> DataContract:
    """Load and validate one contract YAML file.

    Raises:
        ContractError: missing file, invalid YAML, wrong top-level shape,
            or a schema violation (e.g. primary_key referencing an
            undeclared column, an unrecognized `classification` value).
    """
    if not path.is_file():
        raise ContractError(f"Contract file not found at '{path}'.")

    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ContractError(f"Could not read contract file '{path}': {exc}") from exc

    try:
        data = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        raise ContractError(f"Contract file '{path}' is not valid YAML: {exc}") from exc

    if not isinstance(data, dict):
        raise ContractError(
            f"Contract file '{path}' must contain a top-level mapping, got {type(data).__name__}."
        )

    try:
        return DataContract.model_validate(data)
    except ValidationError as exc:
        raise ContractError(f"Contract file '{path}' failed schema validation:\n{exc}") from exc
