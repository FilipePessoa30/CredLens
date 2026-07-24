"""Client for the Banco Central do Brasil (BCB) SGS time-series API.

Fetches a raw JSON time series by code and an explicit date range. Does
not parse or convert values (no decimal-separator assumption, no gap
filling) - that belongs to a later, explicitly separate analytical phase.
See docs/data_sources.md for the specific series used and why, and
docs/data_licensing.md for the ODbL license that governs BCB open data.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import requests

from credlens.logging_config import get_logger

logger = get_logger("data.bcb_client")

DEFAULT_BASE_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados"
DEFAULT_USER_AGENT = (
    "credlens-data-acquisition/0.1 "
    "(+https://github.com/OWNER/credlens-credit-analytics; portfolio project)"
)


class BcbClientError(Exception):
    """The BCB SGS API could not be queried, or returned an unusable response."""


class EmptySeriesError(BcbClientError):
    """The API responded successfully but with zero observations."""


@dataclass(frozen=True)
class BcbSeriesResult:
    code: int
    start_date: str  # DD/MM/AAAA, as sent to the API
    end_date: str
    raw_json: str  # every returned observation, re-serialized verbatim (no value parsing)
    num_observations: int
    retrieved_at_utc: str
    final_url: str


def _format_br_date(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def _parse_br_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%d/%m/%Y").date()
    except ValueError as exc:
        raise BcbClientError(
            f"Invalid date '{value}': expected DD/MM/AAAA (e.g. 01/01/2020)."
        ) from exc


def _deduplicate_boundary_observations(observations: list[object], code: int) -> list[object]:
    """Remove exact-duplicate observations caused by chunking a query into
    multiple date windows.

    BCB's SGS API applies month-inclusive date semantics: for a monthly
    series, a window ending mid-month and the next window starting the
    following day can both legitimately return that same month's single
    observation (identical date AND value), because both windows overlap
    that calendar month even though their day ranges do not overlap. This
    removes only byte-for-byte identical repeats; if the same date ever
    appeared with two *different* values, that is left untouched here and
    would instead surface as a duplicate-row finding in
    `credlens.data.audit` for a human to look at, rather than being
    silently resolved by this client.
    """
    seen: set[str] = set()
    deduped: list[object] = []
    duplicates_removed = 0
    for obs in observations:
        key = json.dumps(obs, sort_keys=True)
        if key in seen:
            duplicates_removed += 1
            continue
        seen.add(key)
        deduped.append(obs)

    if duplicates_removed:
        logger.warning(
            "BCB SGS series %d: removed %d duplicate observation(s) caused by "
            "date-window chunking overlap.",
            code,
            duplicates_removed,
        )
    return deduped


def _split_windows(start: date, end: date, max_days: int) -> list[tuple[date, date]]:
    windows: list[tuple[date, date]] = []
    cursor = start
    while cursor <= end:
        window_end = min(cursor + timedelta(days=max_days - 1), end)
        windows.append((cursor, window_end))
        cursor = window_end + timedelta(days=1)
    return windows


def _get_with_retries(
    url: str,
    params: dict[str, str],
    *,
    timeout_seconds: float,
    max_retries: int,
    retry_backoff_seconds: float,
    user_agent: str,
) -> tuple[str, str]:
    headers = {"User-Agent": user_agent}
    last_error: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            response = requests.get(url, params=params, headers=headers, timeout=timeout_seconds)
            if 400 <= response.status_code < 500:
                raise BcbClientError(
                    f"BCB SGS API refused the request: HTTP {response.status_code} "
                    f"for series query {params.get('dataInicial')}-{params.get('dataFinal')}. "
                    f"Body: {response.text[:300]}"
                )
            response.raise_for_status()
            return response.text, response.url
        except BcbClientError:
            raise
        except requests.RequestException as exc:
            last_error = exc
            logger.warning("BCB SGS attempt %d/%d failed: %s", attempt, max_retries, exc)
            if attempt < max_retries:
                time.sleep(retry_backoff_seconds * attempt)

    raise BcbClientError(f"BCB SGS request failed after {max_retries} attempt(s): {last_error}")


def fetch_series(
    code: int,
    start_date: str,
    end_date: str,
    *,
    base_url: str = DEFAULT_BASE_URL,
    timeout_seconds: float = 30.0,
    max_retries: int = 3,
    retry_backoff_seconds: float = 2.0,
    user_agent: str = DEFAULT_USER_AGENT,
    max_days_per_request: int = 3650,
) -> BcbSeriesResult:
    """Fetch one BCB SGS series over `[start_date, end_date]` (DD/MM/AAAA).

    Both dates are required and explicit - this client never queries an
    open-ended range, and never fills missing dates. If the span exceeds
    `max_days_per_request`, the request is partitioned into sequential
    windows and every returned observation is concatenated, in order, into
    a single re-serialized JSON array (`raw_json`) - values themselves are
    passed through as strings exactly as BCB returns them, with no
    decimal-separator assumption or numeric coercion.

    Raises:
        BcbClientError: invalid dates, or the request failed after retries.
        EmptySeriesError: the API returned zero observations for the range.
    """
    start = _parse_br_date(start_date)
    end = _parse_br_date(end_date)
    if start > end:
        raise BcbClientError(f"start_date {start_date} is after end_date {end_date}.")

    observations: list[object] = []
    final_url = ""

    for window_start, window_end in _split_windows(start, end, max_days_per_request):
        url = base_url.format(code=code)
        params = {
            "formato": "json",
            "dataInicial": _format_br_date(window_start),
            "dataFinal": _format_br_date(window_end),
        }
        body, final_url = _get_with_retries(
            url,
            params,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            retry_backoff_seconds=retry_backoff_seconds,
            user_agent=user_agent,
        )
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as exc:
            raise BcbClientError(f"BCB SGS series {code} returned non-JSON content: {exc}") from exc
        if not isinstance(parsed, list):
            raise BcbClientError(
                f"BCB SGS series {code} returned an unexpected JSON shape (expected a list)."
            )
        observations.extend(parsed)

    observations = _deduplicate_boundary_observations(observations, code)

    if not observations:
        raise EmptySeriesError(
            f"BCB SGS series {code} returned zero observations for {start_date}-{end_date}."
        )

    logger.info("Fetched BCB SGS series %d: %d observation(s).", code, len(observations))

    return BcbSeriesResult(
        code=code,
        start_date=start_date,
        end_date=end_date,
        raw_json=json.dumps(observations, ensure_ascii=False),
        num_observations=len(observations),
        retrieved_at_utc=datetime.now(UTC).isoformat(),
        final_url=final_url,
    )
