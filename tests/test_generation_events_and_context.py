"""Tests for credlens.generation.writeoffs, .collections, .recoveries,
.macro, and .truth - the smaller event-decision and context modules."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from credlens.contracts.loader import load_contract
from credlens.generation.collections import should_contact
from credlens.generation.config import (
    CollectionsConfig,
    RecoveryConfig,
    WriteOffConfig,
    load_generation_config,
)
from credlens.generation.ids import IdFactory
from credlens.generation.macro import generate_macro_context
from credlens.generation.population import generate_customers
from credlens.generation.recoveries import recovery_event_row, schedule_recovery
from credlens.generation.rng import RunRandomStreams
from credlens.generation.truth import attach_contract_truth, generate_latent_customer_truth
from credlens.generation.writeoffs import should_write_off, write_off_event_row


class TestWriteOffDecision:
    def test_below_threshold_is_not_written_off(self) -> None:
        config = WriteOffConfig(dpd_threshold=150)
        assert should_write_off(149, config) is False

    def test_at_or_above_threshold_is_written_off(self) -> None:
        config = WriteOffConfig(dpd_threshold=150)
        assert should_write_off(150, config) is True
        assert should_write_off(200, config) is True

    def test_write_off_event_row_amount_reconciles(self) -> None:
        row = write_off_event_row(
            "ctr-1",
            pd.Timestamp("2024-06-15"),
            Decimal("100"),
            Decimal("20"),
            Decimal("5"),
            150,
            IdFactory("write_off", "h"),
        )
        assert row["amount"] == 125.0
        assert row["principal"] == 100.0
        assert row["interest"] == 20.0
        assert row["fees"] == 5.0
        assert row["reason"] == "policy_threshold"


class TestCollectionsDecision:
    def test_below_every_threshold_no_contact(self) -> None:
        config = CollectionsConfig(
            contact_dpd_thresholds=[15, 45, 75], promise_to_pay_probability=0.3
        )
        assert should_contact(10, config) is False

    def test_at_a_threshold_triggers_contact(self) -> None:
        config = CollectionsConfig(
            contact_dpd_thresholds=[15, 45, 75], promise_to_pay_probability=0.3
        )
        assert should_contact(15, config) is True
        assert should_contact(46, config) is True


class TestRecoveryScheduling:
    def test_zero_probability_never_schedules(self) -> None:
        config = RecoveryConfig(
            recovery_probability=0.0,
            recovery_fraction_min=0.1,
            recovery_fraction_max=0.3,
            max_months_after_write_off=6,
        )
        rng = np.random.default_rng(1)
        assert schedule_recovery(Decimal("1000"), config, rng) is None

    def test_certain_probability_always_schedules_within_window(self) -> None:
        config = RecoveryConfig(
            recovery_probability=1.0,
            recovery_fraction_min=0.1,
            recovery_fraction_max=0.3,
            max_months_after_write_off=6,
        )
        rng = np.random.default_rng(1)
        result = schedule_recovery(Decimal("1000"), config, rng)
        assert result is not None
        month_offset, amount = result
        assert 1 <= month_offset <= 6
        assert Decimal("50") <= amount <= Decimal("400")  # 5%-40% of 1000, generous bound

    def test_recovery_amount_never_exceeds_write_off_amount(self) -> None:
        config = RecoveryConfig(
            recovery_probability=1.0,
            recovery_fraction_min=0.05,
            recovery_fraction_max=0.4,
            max_months_after_write_off=6,
        )
        rng = np.random.default_rng(3)
        for _ in range(20):
            result = schedule_recovery(Decimal("500"), config, rng)
            assert result is not None
            _, amount = result
            assert amount <= Decimal("500")

    def test_recovery_event_row_shape(self) -> None:
        rng = np.random.default_rng(1)
        row = recovery_event_row(
            "ctr-1",
            "wo-1",
            pd.Timestamp("2024-08-01"),
            Decimal("50"),
            IdFactory("recovery", "h"),
            rng,
        )
        assert row["contract_id"] == "ctr-1"
        assert row["write_off_id"] == "wo-1"
        assert row["amount"] == 50.0


class TestMacroContext:
    def test_only_real_bcb_rows_are_ever_produced_in_baseline(self) -> None:
        df = generate_macro_context(pd.Timestamp("2024-01-01"), pd.Timestamp("2024-12-31"))
        if df.empty:
            pytest.skip("Real BCB raw files not present (git-ignored) - nothing to check.")
        assert (df["source_type"] == "public_bcb_observation").all()
        assert (~df["is_synthetic"]).all()
        assert df["series_code"].isin([20570, 21112]).all()

    def test_empty_period_with_no_overlap_produces_no_rows(self) -> None:
        df = generate_macro_context(pd.Timestamp("1900-01-01"), pd.Timestamp("1900-12-31"))
        assert df.empty
        assert list(df.columns) == [
            "source_type",
            "source_id",
            "series_code",
            "reference_date",
            "value",
            "unit",
            "is_synthetic",
            "retrieved_at",
        ]


class TestTruthLayer:
    def test_latent_propensity_is_bounded_0_1(self) -> None:
        cfg = load_generation_config()
        customers = generate_customers(
            50,
            cfg.period,
            "RUN_test",
            IdFactory("customer", "h"),
            RunRandomStreams(1).stream("customers"),
        )
        truth = generate_latent_customer_truth(customers, RunRandomStreams(1).stream("truth"))
        assert truth["latent_payment_propensity"].between(0, 1).all()

    def test_truth_table_never_shares_columns_with_customers_contract(self) -> None:
        """Structural proof of docs/adr/0007: the truth table's own
        columns must never collide with what customers.yaml declares
        (customer_id is the only, deliberate, join key exception)."""
        customers_contract = load_contract(Path("contracts/operational/customers.yaml"))
        truth_columns = {"customer_id", "latent_payment_propensity"}
        overlap = truth_columns.intersection(customers_contract.column_names) - {"customer_id"}
        assert overlap == set()

    def test_contract_truth_carries_customer_propensity_down(self) -> None:
        cfg = load_generation_config()
        customers = generate_customers(
            20,
            cfg.period,
            "RUN_test",
            IdFactory("customer", "h"),
            RunRandomStreams(1).stream("customers"),
        )
        customer_truth = generate_latent_customer_truth(
            customers, RunRandomStreams(1).stream("truth")
        )
        contracts = pd.DataFrame(
            {"contract_id": ["ctr-1"], "customer_id": [customers["customer_id"].iloc[0]]}
        )
        contract_truth = attach_contract_truth(contracts, customer_truth)
        expected = customer_truth.set_index("customer_id")["latent_payment_propensity"].loc[
            customers["customer_id"].iloc[0]
        ]
        assert contract_truth["latent_payment_propensity"].iloc[0] == expected
