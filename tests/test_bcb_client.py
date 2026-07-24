"""Tests for credlens.data.bcb_client: HTTP mocked via `responses`."""

from __future__ import annotations

import json

import pytest
import responses

from credlens.data.bcb_client import (
    BcbClientError,
    EmptySeriesError,
    fetch_series,
)

SERIES_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.99999/dados"


@responses.activate
def test_fetch_series_parses_response_and_preserves_value_strings() -> None:
    payload = [
        {"data": "01/01/2020", "valor": "1234567"},
        {"data": "01/02/2020", "valor": "1234890"},
    ]
    responses.add(responses.GET, SERIES_URL, json=payload, status=200)

    result = fetch_series(99999, "01/01/2020", "01/02/2020")

    assert result.num_observations == 2
    parsed = json.loads(result.raw_json)
    assert parsed == payload
    # Values must be preserved exactly as strings - no numeric coercion.
    assert isinstance(parsed[0]["valor"], str)


@responses.activate
def test_fetch_series_empty_response_raises_empty_series_error() -> None:
    responses.add(responses.GET, SERIES_URL, json=[], status=200)

    with pytest.raises(EmptySeriesError):
        fetch_series(99999, "01/01/2020", "01/02/2020")


@responses.activate
def test_fetch_series_non_list_response_raises() -> None:
    responses.add(responses.GET, SERIES_URL, json={"error": "bad request"}, status=200)

    with pytest.raises(BcbClientError, match="unexpected JSON shape"):
        fetch_series(99999, "01/01/2020", "01/02/2020")


@responses.activate
def test_fetch_series_non_json_response_raises() -> None:
    responses.add(responses.GET, SERIES_URL, body="not json at all", status=200)

    with pytest.raises(BcbClientError, match="non-JSON content"):
        fetch_series(99999, "01/01/2020", "01/02/2020")


@responses.activate
def test_fetch_series_client_error_is_not_retried() -> None:
    responses.add(responses.GET, SERIES_URL, status=400, body="invalid dataInicial")

    with pytest.raises(BcbClientError, match="HTTP 400"):
        fetch_series(99999, "01/01/2020", "01/02/2020", max_retries=3)

    assert len(responses.calls) == 1


@responses.activate
def test_fetch_series_retries_on_server_error() -> None:
    responses.add(responses.GET, SERIES_URL, status=503)
    responses.add(responses.GET, SERIES_URL, json=[{"data": "01/01/2020", "valor": "1"}])

    result = fetch_series(99999, "01/01/2020", "01/02/2020", max_retries=2, retry_backoff_seconds=0)

    assert len(responses.calls) == 2
    assert result.num_observations == 1


def test_fetch_series_rejects_start_after_end() -> None:
    with pytest.raises(BcbClientError, match="is after end_date"):
        fetch_series(99999, "01/02/2020", "01/01/2020")


def test_fetch_series_rejects_malformed_date() -> None:
    with pytest.raises(BcbClientError, match="Invalid date"):
        fetch_series(99999, "2020-01-01", "01/02/2020")


@responses.activate
def test_fetch_series_partitions_long_ranges_into_windows() -> None:
    # A 20-day range with a 10-day window should issue 2 requests.
    responses.add(responses.GET, SERIES_URL, json=[{"data": "05/01/2020", "valor": "1"}])
    responses.add(responses.GET, SERIES_URL, json=[{"data": "15/01/2020", "valor": "2"}])

    result = fetch_series(99999, "01/01/2020", "20/01/2020", max_days_per_request=10)

    assert len(responses.calls) == 2
    assert result.num_observations == 2


@responses.activate
def test_fetch_series_deduplicates_identical_boundary_observations() -> None:
    # Simulates the real chunking-boundary bug this project's own audit
    # tooling caught: two windows returning the exact same observation.
    responses.add(responses.GET, SERIES_URL, json=[{"data": "01/12/2024", "valor": "100"}])
    responses.add(responses.GET, SERIES_URL, json=[{"data": "01/12/2024", "valor": "100"}])

    result = fetch_series(99999, "01/01/2020", "20/01/2020", max_days_per_request=10)

    assert result.num_observations == 1


@responses.activate
def test_fetch_series_keeps_distinct_observations_on_same_date() -> None:
    # A genuine data disagreement (same date, different value) must NOT be
    # silently deduplicated - only byte-for-byte identical repeats are.
    responses.add(responses.GET, SERIES_URL, json=[{"data": "01/12/2024", "valor": "100"}])
    responses.add(responses.GET, SERIES_URL, json=[{"data": "01/12/2024", "valor": "999"}])

    result = fetch_series(99999, "01/01/2020", "20/01/2020", max_days_per_request=10)

    assert result.num_observations == 2
