"""Tests for credlens.analysis.reporting (Phase 6 sections 16-17): report
builders must never crash on an empty/partial scenario_cmp or composition
(a real analysis run might not have every scenario), must produce distinct
EN/PT-BR content, and must never emit a forbidden causal/profitability
claim the DGP has no data to support. No warehouse needed - pure
formatting functions over directly-constructed DataFrames/dicts."""

from __future__ import annotations

import pandas as pd
import pytest

from credlens.analysis.reporting import (
    _df_to_markdown,
    build_executive_summary,
    build_technical_report,
    decision_card,
)

# Concrete forbidden prescriptive/causal claims (Phase 6 section 16's own
# example: "Bancos devem expandir a aprovação porque isso aumenta lucro").
# LGD/EAD/profit/revenue/ROI are legitimate words when used INSIDE a "we
# have no such data" limitation disclaimer (which every report includes) -
# so this list checks for the prescriptive claim itself, not those words.
_FORBIDDEN_PHRASES = (
    "bancos devem",
    "banks should",
    "banks must",
    "aumenta lucro",
    "increases profit",
    "we recommend",
    "recomendamos",
)


@pytest.fixture
def scenario_cmp() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "scenario": "policy_expansion",
                "approval_rate": 0.88,
                "baseline_approval_rate": 0.57,
                "approval_rate_delta_abs": 0.31,
                "write_off_count": 82,
                "baseline_write_off_count": 51,
            },
            {
                "scenario": "collections_change",
                "approval_rate": 0.57,
                "baseline_approval_rate": 0.57,
                "approval_rate_delta_abs": 0.0,
                "write_off_count": 17,
                "baseline_write_off_count": 51,
                "write_off_count_delta_abs": -34,
            },
        ]
    )


@pytest.fixture
def macro_pp() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "period": "pre_shock",
                "baseline_par90": 0.06,
                "stress_par90": 0.06,
                "par90_delta_abs": 0.0,
            },
            {
                "period": "post_shock",
                "baseline_par90": 0.065,
                "stress_par90": 0.19,
                "par90_delta_abs": 0.125,
            },
        ]
    )


@pytest.fixture
def composition() -> dict[str, dict[str, object]]:
    return {
        "policy_expansion": {
            "shared_booked_count": 2935,
            "baseline_only_count": 543,
            "scenario_only_count": 2384,
            "shared_par90": 0.056,
            "marginal_par90": 0.068,
        }
    }


@pytest.fixture
def writeoff_recovery_totals() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "scenario": "baseline",
                "total_write_off_amount": 100_000.0,
                "total_recovery_amount": 5_000.0,
            },
            {
                "scenario": "policy_expansion",
                "total_write_off_amount": 150_000.0,
                "total_recovery_amount": 8_000.0,
            },
        ]
    )


class TestDecisionCard:
    def test_english_card_has_english_labels(self) -> None:
        card = decision_card("Q?", "E", "I", "D", "R", lang="en")
        assert "**Question:**" in card
        assert "**Evidence:**" in card
        assert "**Interpretation:**" in card
        assert "**Decision this could support:**" in card
        assert "**Risk/limitation:**" in card

    def test_portuguese_card_has_portuguese_labels(self) -> None:
        card = decision_card("P?", "E", "I", "D", "R", lang="pt-BR")
        assert "**Pergunta:**" in card
        assert "**Evidência:**" in card
        assert "**Interpretação:**" in card
        assert "**Decisão que poderia apoiar:**" in card
        assert "**Risco/limitação:**" in card


class TestBuildExecutiveSummary:
    @pytest.mark.parametrize("lang", ["en", "pt-BR"])
    def test_runs_without_error_on_full_data(
        self,
        lang: str,
        scenario_cmp: pd.DataFrame,
        macro_pp: pd.DataFrame,
        composition: dict[str, dict[str, object]],
        writeoff_recovery_totals: pd.DataFrame,
    ) -> None:
        out = build_executive_summary(
            lang=lang,
            suite_id="SUITE_x",
            build_id="BUILD_x",
            fingerprint="a" * 64,
            scenario_cmp=scenario_cmp,
            macro_pp=macro_pp,
            composition=composition,
            writeoff_recovery_totals=writeoff_recovery_totals,
        )
        assert out
        assert "BUILD_x" in out
        assert "SUITE_x" in out

    def test_does_not_crash_on_empty_scenario_cmp_and_composition(
        self, writeoff_recovery_totals: pd.DataFrame
    ) -> None:
        empty_scenario_cmp = pd.DataFrame(columns=["scenario", "approval_rate"])
        empty_macro_pp = pd.DataFrame(columns=["period", "par90_delta_abs"])
        out = build_executive_summary(
            lang="en",
            suite_id="SUITE_x",
            build_id="BUILD_x",
            fingerprint="a" * 64,
            scenario_cmp=empty_scenario_cmp,
            macro_pp=empty_macro_pp,
            composition={},
            writeoff_recovery_totals=writeoff_recovery_totals,
        )
        assert out
        # No scenario/macro decision cards possible - only the write-off card.
        assert out.count("**Question:**") == 1

    def test_en_and_pt_outputs_are_different_text(
        self,
        scenario_cmp: pd.DataFrame,
        macro_pp: pd.DataFrame,
        composition: dict[str, dict[str, object]],
        writeoff_recovery_totals: pd.DataFrame,
    ) -> None:
        en = build_executive_summary(
            lang="en",
            suite_id="SUITE_x",
            build_id="BUILD_x",
            fingerprint="a" * 64,
            scenario_cmp=scenario_cmp,
            macro_pp=macro_pp,
            composition=composition,
            writeoff_recovery_totals=writeoff_recovery_totals,
        )
        pt = build_executive_summary(
            lang="pt-BR",
            suite_id="SUITE_x",
            build_id="BUILD_x",
            fingerprint="a" * 64,
            scenario_cmp=scenario_cmp,
            macro_pp=macro_pp,
            composition=composition,
            writeoff_recovery_totals=writeoff_recovery_totals,
        )
        assert en != pt
        assert "Synthetic" in en or "synthetic" in en
        assert "sintético" in pt or "sintética" in pt or "Sintética" in pt

    def test_never_emits_a_forbidden_profitability_or_causal_claim(
        self,
        scenario_cmp: pd.DataFrame,
        macro_pp: pd.DataFrame,
        composition: dict[str, dict[str, object]],
        writeoff_recovery_totals: pd.DataFrame,
    ) -> None:
        out = build_executive_summary(
            lang="en",
            suite_id="SUITE_x",
            build_id="BUILD_x",
            fingerprint="a" * 64,
            scenario_cmp=scenario_cmp,
            macro_pp=macro_pp,
            composition=composition,
            writeoff_recovery_totals=writeoff_recovery_totals,
        )
        lowered = out.lower()
        for phrase in _FORBIDDEN_PHRASES:
            assert phrase not in lowered, f"forbidden phrase '{phrase}' found in executive summary"

    def test_collections_change_card_states_no_causal_attribution(
        self,
        scenario_cmp: pd.DataFrame,
        macro_pp: pd.DataFrame,
        composition: dict[str, dict[str, object]],
        writeoff_recovery_totals: pd.DataFrame,
    ) -> None:
        out = build_executive_summary(
            lang="en",
            suite_id="SUITE_x",
            build_id="BUILD_x",
            fingerprint="a" * 64,
            scenario_cmp=scenario_cmp,
            macro_pp=macro_pp,
            composition=composition,
            writeoff_recovery_totals=writeoff_recovery_totals,
        )
        assert "NOT causal evidence" in out


class TestDfToMarkdown:
    def test_empty_dataframe_renders_a_no_rows_notice(self) -> None:
        out = _df_to_markdown(pd.DataFrame())
        assert "no rows" in out

    def test_truncates_beyond_max_rows_with_a_pointer_to_the_full_csv(self) -> None:
        df = pd.DataFrame({"x": range(30)})
        out = _df_to_markdown(df, max_rows=5)
        assert "showing 5 of 30 rows" in out
        assert "tables/" in out

    def test_small_dataframe_is_not_truncated(self) -> None:
        df = pd.DataFrame({"x": [1, 2]})
        out = _df_to_markdown(df, max_rows=20)
        assert "showing" not in out


class TestBuildTechnicalReport:
    @pytest.mark.parametrize("lang", ["en", "pt-BR"])
    def test_runs_without_error_and_includes_every_section(
        self,
        lang: str,
        scenario_cmp: pd.DataFrame,
        macro_pp: pd.DataFrame,
        composition: dict[str, dict[str, object]],
    ) -> None:
        out = build_technical_report(
            lang=lang,
            build_id="BUILD_x",
            suite_id="SUITE_x",
            fingerprint="a" * 64,
            manifest={
                "dbt_version": "1.8.0",
                "duckdb_version": "1.0.0",
                "package_version": "0.7.0",
                "python_version": "3.11.9",
            },
            scenario_cmp=scenario_cmp,
            macro_pp=macro_pp,
            composition=composition,
            multiseed_summary=None,
            benchmark_profiles=[],
            reconciliation_results=[{"name": "outstanding_balance", "passed": True}],
            dbt_test_results={"passed": 135, "failed": 0},
            figures_written={"credit_funnel": "a" * 64},
        )
        assert "BUILD_x" in out
        assert "credit_funnel" in out
        assert "Not executed" in out or "Não executado" in out  # multiseed_summary=None path
        assert "Not included in this run" in out  # benchmark_profiles=[] path

    def test_multiseed_summary_section_renders_when_present(
        self,
        scenario_cmp: pd.DataFrame,
        macro_pp: pd.DataFrame,
        composition: dict[str, dict[str, object]],
    ) -> None:
        out = build_technical_report(
            lang="en",
            build_id="BUILD_x",
            suite_id="SUITE_x",
            fingerprint="a" * 64,
            manifest={},
            scenario_cmp=scenario_cmp,
            macro_pp=macro_pp,
            composition=composition,
            multiseed_summary={
                "scenario": "macroeconomic_stress",
                "scale": "smoke",
                "seeds": [1, 2, 3],
                "metric_summaries": {
                    "par90_delta": {
                        "mean_delta": 0.05,
                        "stdev_delta": 0.01,
                        "n_seeds": 3,
                        "fraction_in_expected_direction": 1.0,
                    }
                },
            },
            benchmark_profiles=[],
            reconciliation_results=[],
            dbt_test_results={},
            figures_written={},
        )
        assert "simulation variability" in out.lower()
        assert (
            "confidence interval" not in out.lower()
            or "never a real institution's statistical confidence interval" in out.lower()
        )

    def test_benchmark_profiles_rendered_separately_and_labeled_real(
        self,
        scenario_cmp: pd.DataFrame,
        macro_pp: pd.DataFrame,
        composition: dict[str, dict[str, object]],
    ) -> None:
        out = build_technical_report(
            lang="en",
            build_id="BUILD_x",
            suite_id="SUITE_x",
            fingerprint="a" * 64,
            manifest={},
            scenario_cmp=scenario_cmp,
            macro_pp=macro_pp,
            composition=composition,
            multiseed_summary=None,
            benchmark_profiles=[
                {"source_id": "uci-default-credit", "num_rows": 30000, "num_columns": 25}
            ],
            reconciliation_results=[],
            dbt_test_results={},
            figures_written={},
        )
        assert "uci-default-credit" in out
        assert "never merged, never treated as a CredLens result" in out
