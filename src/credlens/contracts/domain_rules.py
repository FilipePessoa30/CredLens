"""Generic, schema-driven checks that apply to any contract's own table.

Everything here is vectorized pandas over the whole column/table at once -
never a Python loop instantiating one validator object per row. This is
what makes these checks equally cheap on a 21-row fixture and a
30,000-row real file (see docs/data_contracts.md, "why vectorized").
"""

from __future__ import annotations

import re

import pandas as pd

from credlens.contracts.models import ColumnSpec, DataContract, DomainSpec
from credlens.contracts.reporting import Finding, missing_tables_finding

# Matches an 11-digit Brazilian CPF, with or without the conventional
# XXX.XXX.XXX-XX punctuation - see docs/business_rules.md identity rules
# and SECURITY.md. Applied to every *_id column as a safety net: this
# project's synthetic identifiers are letter-prefixed (e.g. "cust-001")
# and should never coincidentally take this shape.
_CPF_LIKE_PATTERN = re.compile(r"^\d{3}\.?\d{3}\.?\d{3}-?\d{2}$")


def check_required_and_unexpected_columns(
    df: pd.DataFrame, contract: DataContract, *, mode: str
) -> list[Finding]:
    findings: list[Finding] = []
    actual = set(df.columns)
    expected = set(contract.column_names)

    for column in sorted(expected - actual):
        findings.append(
            Finding(
                code="MISSING_COLUMN",
                severity="error",
                contract=contract.name,
                column=column,
                message="Required column is missing from the file.",
            )
        )

    unexpected_is_error = mode == "strict" or contract.strict_unexpected_columns
    for column in sorted(actual - expected):
        findings.append(
            Finding(
                code="UNEXPECTED_COLUMN",
                severity="error" if unexpected_is_error else "warning",
                contract=contract.name,
                column=column,
                message="Column is present in the file but not declared in the contract.",
            )
        )
    return findings


def check_nullability(df: pd.DataFrame, contract: DataContract) -> list[Finding]:
    findings: list[Finding] = []
    for column in contract.columns:
        if column.nullable or column.name not in df.columns:
            continue
        missing_mask = df[column.name].isna()
        count = int(missing_mask.sum())
        if count:
            findings.append(
                Finding(
                    code="NULL_VIOLATION",
                    severity="error",
                    contract=contract.name,
                    column=column.name,
                    message="Non-nullable column contains null value(s).",
                    count=count,
                    total=len(df),
                )
            )
    return findings


def _domain_violation_mask(series: pd.Series, domain: DomainSpec) -> pd.Series:
    violation = pd.Series(False, index=series.index)

    if domain.in_set is not None:
        violation = violation | ~series.isin(domain.in_set)
    if domain.min is not None or domain.max is not None:
        numeric = pd.to_numeric(series, errors="coerce")
        out_of_range = numeric.isna()
        if domain.min is not None:
            out_of_range = out_of_range | (numeric < domain.min)
        if domain.max is not None:
            out_of_range = out_of_range | (numeric > domain.max)
        violation = violation | out_of_range
    if domain.regex is not None:
        matches = series.astype(str).str.match(domain.regex)
        violation = violation | ~matches.fillna(False)

    return violation


def check_domain(df: pd.DataFrame, contract: DataContract) -> list[Finding]:
    findings: list[Finding] = []
    for column in contract.columns:
        if column.domain is None or column.name not in df.columns:
            continue
        series = df[column.name].dropna()
        if series.empty:
            continue
        violation_mask = _domain_violation_mask(series, column.domain)
        count = int(violation_mask.sum())
        if count:
            examples = tuple(series[violation_mask].astype(str).unique()[:5].tolist())
            findings.append(_domain_finding(column, contract.name, count, len(series), examples))
    return findings


def _domain_finding(
    column: ColumnSpec, contract_name: str, count: int, total: int, examples: tuple[str, ...]
) -> Finding:
    return Finding(
        code="DOMAIN_VIOLATION",
        severity="error",
        contract=contract_name,
        column=column.name,
        message="Value(s) outside the contract's documented domain.",
        count=count,
        total=total,
        examples=examples,
    )


def check_primary_key(df: pd.DataFrame, contract: DataContract) -> list[Finding]:
    pk = contract.primary_key
    if not pk or not all(col in df.columns for col in pk):
        return []

    findings: list[Finding] = []
    null_mask = df[pk].isna().any(axis=1)
    null_count = int(null_mask.sum())
    if null_count:
        findings.append(
            Finding(
                code="PK_NULL",
                severity="error",
                contract=contract.name,
                column=",".join(pk),
                message="Primary key column(s) contain null value(s).",
                count=null_count,
                total=len(df),
            )
        )

    non_null = df.loc[~null_mask, pk]
    dup_mask = non_null.duplicated(keep=False)
    dup_count = int(dup_mask.sum())
    if dup_count:
        examples = tuple(
            non_null[dup_mask].drop_duplicates().astype(str).agg("-".join, axis=1).head(5).tolist()
        )
        findings.append(
            Finding(
                code="PK_DUPLICATE",
                severity="error",
                contract=contract.name,
                column=",".join(pk),
                message="Duplicate primary key value(s).",
                count=dup_count,
                total=len(df),
                examples=examples,
            )
        )
    return findings


def check_uniqueness_rules(df: pd.DataFrame, contract: DataContract) -> list[Finding]:
    findings: list[Finding] = []
    for rule in contract.uniqueness_rules:
        if not all(col in df.columns for col in rule.columns):
            continue
        subset = df[rule.columns].dropna()
        dup_mask = subset.duplicated(keep=False)
        dup_count = int(dup_mask.sum())
        if dup_count:
            examples = tuple(
                subset[dup_mask]
                .drop_duplicates()
                .astype(str)
                .agg("-".join, axis=1)
                .head(5)
                .tolist()
            )
            findings.append(
                Finding(
                    code="UNIQUENESS_VIOLATION",
                    severity=rule.severity.value,
                    contract=contract.name,
                    column=",".join(rule.columns),
                    message=f"Uniqueness rule '{rule.name}' violated.",
                    count=dup_count,
                    total=len(df),
                    examples=examples,
                )
            )
    return findings


def check_no_document_like_identifiers(df: pd.DataFrame, contract: DataContract) -> list[Finding]:
    """Every `*_id` column must never contain a CPF-shaped value.

    Defense in depth for the "no real document numbers" rule (see
    SECURITY.md, docs/business_rules.md) - this project's own synthetic
    identifiers are letter-prefixed and should never match, but this
    check runs unconditionally rather than trusting that convention alone.
    """
    findings: list[Finding] = []
    id_columns = [column for column in df.columns if str(column).endswith("_id")]
    for column_name in id_columns:
        series = df[column_name].dropna().astype(str)
        if series.empty:
            continue
        cpf_like = series.str.match(_CPF_LIKE_PATTERN)
        count = int(cpf_like.sum())
        if count:
            findings.append(
                Finding(
                    code="CPF_LIKE_IDENTIFIER",
                    severity="error",
                    contract=contract.name,
                    column=str(column_name),
                    message=(
                        "Identifier column contains a CPF-shaped value - identifiers must "
                        "never resemble a real document number."
                    ),
                    count=count,
                    total=len(series),
                    examples=tuple(series[cpf_like].unique()[:5].tolist()),
                )
            )
    return findings


def check_foreign_keys(
    df: pd.DataFrame, contract: DataContract, tables: dict[str, pd.DataFrame]
) -> list[Finding]:
    findings: list[Finding] = []
    for fk in contract.foreign_keys:
        if fk.column not in df.columns:
            continue
        referenced_df = tables.get(fk.references_contract)
        if referenced_df is None or fk.references_column not in referenced_df.columns:
            findings.append(
                missing_tables_finding(
                    contract.name, f"foreign_key:{fk.column}", [fk.references_contract]
                )
            )
            continue

        known_values = set(referenced_df[fk.references_column].dropna())
        actual = df[fk.column].dropna()
        orphan_mask = ~actual.isin(known_values)
        count = int(orphan_mask.sum())
        if count:
            examples = tuple(actual[orphan_mask].astype(str).unique()[:5].tolist())
            findings.append(
                Finding(
                    code="FK_ORPHAN",
                    severity=fk.severity.value,
                    contract=contract.name,
                    column=fk.column,
                    message=(
                        f"Value(s) not found in {fk.references_contract}.{fk.references_column}."
                    ),
                    count=count,
                    total=len(actual),
                    examples=examples,
                )
            )
    return findings


def check_all(
    df: pd.DataFrame,
    contract: DataContract,
    tables: dict[str, pd.DataFrame],
    *,
    mode: str,
) -> list[Finding]:
    """Run every generic, schema-driven check. Does not touch business_rules
    (named, contract-declared multi-table checks) - see validators.py.
    """
    findings: list[Finding] = []
    findings += check_required_and_unexpected_columns(df, contract, mode=mode)
    findings += check_nullability(df, contract)
    findings += check_domain(df, contract)
    findings += check_primary_key(df, contract)
    findings += check_uniqueness_rules(df, contract)
    findings += check_foreign_keys(df, contract, tables)
    findings += check_no_document_like_identifiers(df, contract)
    return findings
