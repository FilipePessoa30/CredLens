"""Orchestrates domain + business-rule checks into one ValidationReport.

Two ways to call `validate`:
- `path` is a single file: only checks that need just this one table run;
  any business rule needing another table reports an informational
  "not evaluated" finding (see reporting.missing_tables_finding).
- `path` is a directory (a "scenario"): every contract's file present in
  it, named `<contract_name>.<format>`, is loaded, so multi-table business
  rules run too. This is how tests/fixtures/contracts/ scenarios work.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from credlens.contracts import domain_rules
from credlens.contracts.models import DataContract
from credlens.contracts.registry import KNOWN_BUSINESS_RULE_CODES
from credlens.contracts.reporting import Finding, ValidationReport

VALID_MODES = ("audit", "strict")


class ValidationRunError(Exception):
    """Raised when the table(s) needed for validation cannot be located/read."""


def read_table(path: Path, contract: DataContract) -> pd.DataFrame:
    """Read `path` into a DataFrame according to `contract.format`.

    Raises:
        ValidationRunError: unreadable file or unsupported format.
    """
    try:
        if contract.format == "csv":
            return pd.read_csv(path)
        if contract.format == "json":
            raw = json.loads(path.read_text(encoding="utf-8"))
            return pd.DataFrame(raw)
        if contract.format == "asc":
            return pd.read_csv(path, sep=r"\s+")
    except (OSError, ValueError) as exc:
        raise ValidationRunError(f"Could not read '{path}' as {contract.format}: {exc}") from exc

    raise ValidationRunError(
        f"Unsupported contract format '{contract.format}' declared by contract '{contract.name}'."
    )


def _contract_file_in(directory: Path, contract: DataContract) -> Path | None:
    candidate = directory / f"{contract.name}.{contract.format}"
    return candidate if candidate.is_file() else None


def load_scenario_tables(
    directory: Path, contracts: dict[str, DataContract]
) -> dict[str, pd.DataFrame]:
    """Load every contract's file present in `directory`.

    A contract with no matching file in the directory is simply absent
    from the result - that is not an error, since a given scenario need
    not exercise every table (see tests/fixtures/contracts/).
    """
    tables: dict[str, pd.DataFrame] = {}
    for name, contract in contracts.items():
        found = _contract_file_in(directory, contract)
        if found is not None:
            tables[name] = read_table(found, contract)
    return tables


def validate(
    contract: DataContract,
    path: Path,
    *,
    mode: str,
    all_contracts: dict[str, DataContract] | None = None,
) -> ValidationReport:
    """Validate `contract` against the file or scenario directory at `path`.

    Raises:
        ValueError: `mode` is not "audit" or "strict".
        ValidationRunError: the path doesn't exist, the file can't be
            read, or a directory was given without `all_contracts`.
    """
    if mode not in VALID_MODES:
        raise ValueError(f"Unknown validation mode '{mode}' - expected one of {VALID_MODES}.")

    if path.is_dir():
        if all_contracts is None:
            raise ValidationRunError(
                "Validating a scenario directory requires the full contract registry."
            )
        tables = load_scenario_tables(path, all_contracts)
        if contract.name not in tables:
            raise ValidationRunError(
                f"No file for contract '{contract.name}' found in scenario directory '{path}' "
                f"(expected '{contract.name}.{contract.format}')."
            )
        df = tables[contract.name]
    elif path.is_file():
        df = read_table(path, contract)
        tables = {contract.name: df}
    else:
        raise ValidationRunError(f"Path not found: '{path}'.")

    findings: list[Finding] = list(domain_rules.check_all(df, contract, tables, mode=mode))

    for rule in contract.business_rules:
        rule_func = KNOWN_BUSINESS_RULE_CODES[rule.code]
        findings.extend(rule_func(tables, contract.name))  # type: ignore[operator]

    return ValidationReport(contract=contract.name, mode=mode, row_count=len(df), findings=findings)
