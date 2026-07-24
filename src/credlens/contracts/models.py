"""Typed models for data contracts (contracts/raw/*.yaml, contracts/operational/*.yaml).

Pydantic parses and validates the contract YAML *definitions* themselves
(a one-time, small-N operation - loading ~20 files). It is not used to
validate data rows: actual table data is checked with vectorized pandas
operations in domain_rules.py / relational_rules.py / temporal_rules.py /
financial_rules.py, never one Pydantic instance per row. See
docs/data_contracts.md and docs/adr/0006-audit-vs-strict-validation.md.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


class Classification(StrEnum):
    """Who/what a contract or column is for - drives modeling availability."""

    PUBLIC_SOURCE = "public_source"
    SYNTHETIC_OPERATIONAL = "synthetic_operational"
    EVALUATION_ONLY = "evaluation_only"
    SYNTHETIC_TRUTH_ONLY = "synthetic_truth_only"
    TECHNICAL_METADATA = "technical_metadata"


class ContractStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    DEPRECATED = "deprecated"


class ColumnType(StrEnum):
    STRING = "string"
    INTEGER = "integer"
    DECIMAL = "decimal"
    BOOLEAN = "boolean"
    DATE = "date"
    TIMESTAMP = "timestamp"
    CATEGORICAL = "categorical"


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class DomainSpec(BaseModel):
    """A small, closed, declarative vocabulary - never an evaluated expression.

    Only `in_set`, `min`/`max`, and `regex` are recognized. A contract
    author cannot embed arbitrary Python here; anything not expressible in
    this vocabulary is out of scope for domain validation in this phase.
    """

    model_config = ConfigDict(extra="forbid")

    in_set: list[str | int | float | bool] | None = None
    min: float | None = None
    max: float | None = None
    regex: str | None = None

    @model_validator(mode="after")
    def _require_at_least_one_constraint(self) -> DomainSpec:
        if self.in_set is None and self.min is None and self.max is None and self.regex is None:
            raise ValueError("A domain spec must set at least one of in_set/min/max/regex.")
        return self


class ForeignKeySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    column: str
    references_contract: str
    references_column: str
    severity: Severity = Severity.ERROR


class ColumnSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    type: ColumnType
    nullable: bool
    domain: DomainSpec | None = None
    unit: str | None = None
    temporality: str | None = None
    sensitivity: Classification
    available_for_modeling: bool
    description: str


class UniquenessRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    columns: list[str]
    severity: Severity = Severity.ERROR

    @field_validator("columns")
    @classmethod
    def _non_empty(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("A uniqueness rule must name at least one column.")
        return value


class BusinessRule(BaseModel):
    """A reference to a named, implemented Python check - never inline code.

    `code` must match a function registered in relational_rules.py,
    temporal_rules.py, or financial_rules.py (see registry.py's
    `KNOWN_BUSINESS_RULE_CODES`) - an unrecognized code is a contract
    loading error, not a silently-skipped rule.
    """

    model_config = ConfigDict(extra="forbid")

    code: str
    description: str
    severity: Severity = Severity.ERROR


class DataContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    version: int
    description: str
    owner: str
    classification: Classification
    grain: str
    status: ContractStatus
    evolution_policy: str
    format: str

    primary_key: list[str]
    foreign_keys: list[ForeignKeySpec] = []
    columns: list[ColumnSpec]
    uniqueness_rules: list[UniquenessRule] = []
    business_rules: list[BusinessRule] = []
    strict_unexpected_columns: bool = False

    @property
    def column_names(self) -> list[str]:
        return [column.name for column in self.columns]

    def column(self, name: str) -> ColumnSpec:
        for column in self.columns:
            if column.name == name:
                return column
        raise KeyError(name)

    @model_validator(mode="after")
    def _primary_key_columns_exist(self) -> DataContract:
        known = set(self.column_names)
        missing = [key for key in self.primary_key if key not in known]
        if missing:
            raise ValueError(f"primary_key references undeclared column(s): {missing}")
        return self

    @model_validator(mode="after")
    def _uniqueness_rule_columns_exist(self) -> DataContract:
        known = set(self.column_names)
        for rule in self.uniqueness_rules:
            missing = [col for col in rule.columns if col not in known]
            if missing:
                raise ValueError(
                    f"uniqueness_rules[{rule.name}] references undeclared column(s): {missing}"
                )
        return self

    @model_validator(mode="after")
    def _foreign_key_columns_exist(self) -> DataContract:
        known = set(self.column_names)
        missing = [fk.column for fk in self.foreign_keys if fk.column not in known]
        if missing:
            raise ValueError(f"foreign_keys reference undeclared column(s): {missing}")
        return self
