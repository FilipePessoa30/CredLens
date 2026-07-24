"""Load every contract, cross-validate references, and expose the known
business-rule code registry.

The set of "known" business rule codes is derived directly from the
actually-implemented functions in relational_rules.py, temporal_rules.py,
and financial_rules.py (their `RULES` dicts) - not maintained as a
separate list that could drift out of sync with the code.
"""

from __future__ import annotations

from pathlib import Path

from credlens.contracts import financial_rules, relational_rules, temporal_rules
from credlens.contracts.loader import ContractError, load_contract
from credlens.contracts.models import DataContract

DEFAULT_RAW_DIR = Path("contracts/raw")
DEFAULT_OPERATIONAL_DIR = Path("contracts/operational")

KNOWN_BUSINESS_RULE_CODES: dict[str, object] = {
    **relational_rules.RULES,
    **temporal_rules.RULES,
    **financial_rules.RULES,
}


class RegistryError(Exception):
    """Raised for contract-registry loading or cross-validation failures."""


def load_all_contracts(
    raw_dir: Path = DEFAULT_RAW_DIR,
    operational_dir: Path = DEFAULT_OPERATIONAL_DIR,
) -> dict[str, DataContract]:
    """Load every contract YAML file under `raw_dir` and `operational_dir`.

    Raises:
        RegistryError: a contract fails to load, two contracts share a
            name, a foreign key references an unknown contract/column, or
            a business rule references an unimplemented code.
    """
    contracts: dict[str, DataContract] = {}

    for directory in (raw_dir, operational_dir):
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.yaml")):
            try:
                contract = load_contract(path)
            except ContractError as exc:
                raise RegistryError(str(exc)) from exc
            if contract.name in contracts:
                raise RegistryError(
                    f"Duplicate contract name '{contract.name}' - already loaded from another file."
                )
            contracts[contract.name] = contract

    _validate_cross_references(contracts)
    return contracts


def _validate_cross_references(contracts: dict[str, DataContract]) -> None:
    for contract in contracts.values():
        for fk in contract.foreign_keys:
            if fk.references_contract not in contracts:
                raise RegistryError(
                    f"{contract.name}: foreign key on '{fk.column}' references unknown "
                    f"contract '{fk.references_contract}'."
                )
            referenced = contracts[fk.references_contract]
            if fk.references_column not in referenced.column_names:
                raise RegistryError(
                    f"{contract.name}: foreign key on '{fk.column}' references unknown column "
                    f"'{fk.references_contract}.{fk.references_column}'."
                )
        for rule in contract.business_rules:
            if rule.code not in KNOWN_BUSINESS_RULE_CODES:
                raise RegistryError(
                    f"{contract.name}: business_rules references unimplemented rule code "
                    f"'{rule.code}'. Known codes: {sorted(KNOWN_BUSINESS_RULE_CODES)}"
                )


def get_contract(contracts: dict[str, DataContract], name: str) -> DataContract:
    """Look up a single contract by name.

    Raises:
        RegistryError: no contract with that name exists.
    """
    try:
        return contracts[name]
    except KeyError:
        known = ", ".join(sorted(contracts))
        raise RegistryError(f"Unknown contract '{name}'. Known contracts: {known}") from None
