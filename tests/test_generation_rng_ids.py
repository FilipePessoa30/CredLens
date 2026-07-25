"""Tests for credlens.generation.rng and credlens.generation.ids:
reproducible substreams and deterministic, non-CPF-shaped identifiers."""

from __future__ import annotations

import re

import pytest

from credlens.generation.ids import IdFactory, run_short_hash
from credlens.generation.rng import STREAM_NAMES, RunRandomStreams

_CPF_LIKE_PATTERN = re.compile(r"^\d{3}\.?\d{3}\.?\d{3}-?\d{2}$")


class TestRunRandomStreams:
    def test_same_seed_produces_identical_draws_per_stream(self) -> None:
        a = RunRandomStreams(42)
        b = RunRandomStreams(42)
        for name in STREAM_NAMES:
            draw_a = a.stream(name).random(5).tolist()
            draw_b = b.stream(name).random(5).tolist()
            assert draw_a == draw_b

    def test_different_seed_produces_different_draws(self) -> None:
        a = RunRandomStreams(1)
        b = RunRandomStreams(2)
        assert a.stream("customers").random(5).tolist() != b.stream("customers").random(5).tolist()

    def test_streams_are_mutually_independent(self) -> None:
        """Consuming one stream must not shift another - each is its own
        Generator derived from an independent SeedSequence child, not a
        shared global state."""
        run = RunRandomStreams(7)
        untouched = RunRandomStreams(7)

        run.stream("customers").random(100)  # consume a lot from one stream

        assert (
            run.stream("payments").random(5).tolist()
            == untouched.stream("payments").random(5).tolist()
        )

    def test_unknown_stream_name_raises(self) -> None:
        run = RunRandomStreams(1)
        with pytest.raises(KeyError):
            run.stream("not_a_real_stream")

    def test_every_declared_stream_is_reachable(self) -> None:
        run = RunRandomStreams(1)
        for name in STREAM_NAMES:
            assert run.stream(name) is not None


class TestIdFactory:
    def test_ids_are_sequential_and_prefixed(self) -> None:
        factory = IdFactory("customer", "abcd1234")
        ids = [factory.next() for _ in range(3)]
        assert ids == [
            "CUS_abcd1234_0000001",
            "CUS_abcd1234_0000002",
            "CUS_abcd1234_0000003",
        ]

    def test_ids_are_unique_within_a_run(self) -> None:
        factory = IdFactory("application", "abcd1234")
        ids = [factory.next() for _ in range(500)]
        assert len(set(ids)) == 500

    def test_ids_never_look_like_a_cpf(self) -> None:
        factory = IdFactory("customer", "abcd1234")
        for _ in range(50):
            generated_id = factory.next()
            assert not _CPF_LIKE_PATTERN.match(generated_id)

    def test_ids_are_not_uuid4_shaped(self) -> None:
        """A uuid4 has 4 hyphen-separated groups with a version nibble -
        this project's ids use a single underscore-delimited, sequential
        shape instead."""
        factory = IdFactory("contract", "abcd1234")
        generated_id = factory.next()
        assert generated_id.count("-") == 0

    def test_unknown_entity_raises(self) -> None:
        with pytest.raises(KeyError):
            IdFactory("not_a_real_entity", "abcd1234")

    def test_count_tracks_how_many_ids_were_issued(self) -> None:
        factory = IdFactory("payment", "abcd1234")
        assert factory.count == 0
        factory.next()
        factory.next()
        assert factory.count == 2

    def test_two_factories_with_same_run_hash_but_different_entities_dont_collide(self) -> None:
        customer_factory = IdFactory("customer", "abcd1234")
        contract_factory = IdFactory("contract", "abcd1234")
        assert customer_factory.next() != contract_factory.next()


def test_run_short_hash_is_a_deterministic_prefix() -> None:
    full_hash = "a" * 64
    assert run_short_hash(full_hash, length=8) == "a" * 8
    assert run_short_hash(full_hash) == run_short_hash(full_hash)
