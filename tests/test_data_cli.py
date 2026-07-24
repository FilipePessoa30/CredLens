"""Tests for the `credlens data ...` CLI commands.

HTTP is mocked via `responses`; filesystem writes are sandboxed to
`tmp_path` by monkeypatching the CLI's module-level path constants and
`load_config`, rather than touching this repository's real `data/`
directory or `config/base.yaml`. Tests deliberately never depend on real
files under `data/raw/` (git-ignored, absent on a fresh clone/CI) - every
fixture here is synthetic and self-contained.
"""

from __future__ import annotations

import csv
import io
import json
import zipfile
from pathlib import Path

import pytest
import responses

from credlens.cli import main
from credlens.config import Config, DataConfig, LoggingConfig, PathsConfig, ProjectConfig

UCI_FIXTURE_URL = "https://archive.ics.uci.edu/static/public/350/data.csv"
SOUTH_GERMAN_FIXTURE_URL = "https://archive.ics.uci.edu/static/public/522/south+german+credit.zip"
BCB_FIXTURE_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.20570/dados"


def _fake_config(tmp_path: Path) -> Config:
    return Config(
        project=ProjectConfig(name="credlens", display_name="CredLens", environment="test"),
        logging=LoggingConfig(level="INFO", format="%(message)s"),
        paths=PathsConfig(data_dir="data", config_dir="config", docs_dir="docs"),
        data=DataConfig(
            raw_dir=str(tmp_path / "data" / "raw"),
            metadata_dir=str(tmp_path / "data" / "metadata"),
            http_timeout_seconds=5.0,
            http_max_retries=2,
            http_retry_backoff_seconds=0.0,
            user_agent="credlens-test-agent",
            bcb_default_start_date="01/01/2020",
            bcb_max_days_per_request=3650,
        ),
        source_path=tmp_path / "config" / "base.yaml",
    )


def _source_entry(source_id: str, acquisition_url: str, filename: str, method: str) -> str:
    return f"""  - id: {source_id}
    name: "Fixture Source {source_id}"
    role: primary_benchmark
    organization: "Fixture Org"
    homepage: "https://example.invalid"
    acquisition_url: "{acquisition_url}"
    acquisition_method: {method}
    filename: "{filename}"
    authentication: none
    license: "CC BY 4.0"
    license_url: "https://example.invalid/license"
    doi: null
    citation: "Fixture citation."
    country: "Fixtureland"
    period: "2020"
    granularity: "row per fixture"
    observation_unit: "fixture"
    target_variable: "target"
    format: csv
    update_frequency: "static"
    restrictions: "none"
    redistribution: allowed_with_attribution
    status: approved
    verified_at_utc: "2026-01-01T00:00:00Z"
    notes: "Fixture note."
"""


def _minimal_registry_yaml(source_id: str = "uci-default-credit") -> str:
    entry = _source_entry(source_id, UCI_FIXTURE_URL, "fixture.csv", "http_get")
    return f"schema_version: 1\nsources:\n{entry}"


def _multi_source_registry_yaml() -> str:
    entries = (
        _source_entry("uci-default-credit", UCI_FIXTURE_URL, "fixture.csv", "http_get")
        + _source_entry(
            "south-german-credit", SOUTH_GERMAN_FIXTURE_URL, "south_german_credit.zip", "http_get"
        )
        + _source_entry("bcb-sgs-20570", BCB_FIXTURE_URL, "bcb_sgs_20570.json", "bcb_sgs")
    )
    return f"schema_version: 1\nsources:\n{entries}"


def _south_german_credit_zip_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "SouthGermanCredit.asc",
            "laufkont laufzeit kredit\n1 18 1\n2 9 0\n3 12 1\n",
        )
    return buffer.getvalue()


def _setup_sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, registry_yaml: str) -> Path:
    """Point every CLI data-layer path constant at `tmp_path` and write
    `registry_yaml` there, without touching this repository's real files.
    """
    monkeypatch.chdir(tmp_path)
    registry_path = tmp_path / "data" / "metadata" / "source_registry.yaml"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(registry_yaml, encoding="utf-8")

    manifest_path = tmp_path / "data" / "metadata" / "file_manifest.csv"
    schemas_dir = tmp_path / "data" / "metadata" / "schemas"
    audit_reports_dir = tmp_path / "reports" / "data_audit"

    monkeypatch.setattr("credlens.cli.REGISTRY_PATH", registry_path)
    monkeypatch.setattr("credlens.cli.MANIFEST_PATH", manifest_path)
    monkeypatch.setattr("credlens.cli.SCHEMAS_DIR", schemas_dir)
    monkeypatch.setattr("credlens.cli.AUDIT_REPORTS_DIR", audit_reports_dir)
    monkeypatch.setattr(
        "credlens.cli.AUDIT_METRICS_PATH", audit_reports_dir / "quality_metrics.json"
    )
    monkeypatch.setattr("credlens.cli.load_config", lambda: _fake_config(tmp_path))

    return tmp_path


@pytest.fixture
def sandboxed_data_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Sandbox with a single uci-default-credit-shaped fixture source."""
    return _setup_sandbox(tmp_path, monkeypatch, _minimal_registry_yaml())


@pytest.fixture
def sandboxed_multi_source_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Sandbox with uci-default-credit, south-german-credit, and
    bcb-sgs-20570-shaped fixture sources, for testing per-source loaders
    and --source filters without depending on real acquired files.
    """
    return _setup_sandbox(tmp_path, monkeypatch, _multi_source_registry_yaml())


# --- sources -----------------------------------------------------------------


def test_data_sources_works_offline_against_the_real_registry(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["data", "sources"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "uci-default-credit" in captured.out
    assert "home-credit" in captured.out


def test_data_sources_reports_error_for_broken_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    broken = tmp_path / "broken.yaml"
    broken.write_text("not: [valid", encoding="utf-8")
    monkeypatch.setattr("credlens.cli.REGISTRY_PATH", broken)

    exit_code = main(["data", "sources"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "Error" in captured.out


# --- fetch ---------------------------------------------------------------------


def test_data_fetch_unknown_source_fails_cleanly(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["data", "fetch", "--source", "not-a-real-source"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "Unknown source id" in captured.out


def test_data_fetch_home_credit_is_blocked_without_any_network_call(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Uses the real repository registry deliberately - this must stay
    # blocked and must never attempt a network call, however it's invoked.
    exit_code = main(["data", "fetch", "--source", "home-credit"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "BLOCKED_REQUIRES_USER_ACCESS" in captured.out


@responses.activate
def test_data_fetch_downloads_and_writes_manifest(
    sandboxed_data_cli: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    responses.add(
        responses.GET,
        UCI_FIXTURE_URL,
        body=b"id,x\n1,2\n3,4\n",
        status=200,
        content_type="text/csv",
    )

    exit_code = main(["data", "fetch", "--source", "uci-default-credit"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Manifest updated" in captured.out

    manifest_path = sandboxed_data_cli / "data" / "metadata" / "file_manifest.csv"
    assert manifest_path.is_file()
    downloaded_file = sandboxed_data_cli / "data" / "raw" / "uci_default_credit" / "fixture.csv"
    assert downloaded_file.read_bytes() == b"id,x\n1,2\n3,4\n"


@responses.activate
def test_data_fetch_refuses_overwrite_then_force_succeeds(
    sandboxed_data_cli: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    responses.add(responses.GET, UCI_FIXTURE_URL, body=b"id,x\n1,2\n", status=200)
    main(["data", "fetch", "--source", "uci-default-credit"])

    responses.add(responses.GET, UCI_FIXTURE_URL, body=b"id,x\n9,9\n", status=200)
    exit_code_no_force = main(["data", "fetch", "--source", "uci-default-credit"])
    captured = capsys.readouterr()
    assert exit_code_no_force == 1
    assert "FAILED" in captured.out

    exit_code_force = main(["data", "fetch", "--source", "uci-default-credit", "--force"])
    assert exit_code_force == 0
    downloaded_file = sandboxed_data_cli / "data" / "raw" / "uci_default_credit" / "fixture.csv"
    assert downloaded_file.read_bytes() == b"id,x\n9,9\n"


# --- verify --------------------------------------------------------------------


def test_data_verify_without_manifest_fails_cleanly(
    sandboxed_data_cli: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(["data", "verify"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "nothing to verify" in captured.out.lower()


@responses.activate
def test_data_verify_reports_ok_after_a_clean_fetch(
    sandboxed_data_cli: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    responses.add(responses.GET, UCI_FIXTURE_URL, body=b"id,x\n1,2\n", status=200)
    main(["data", "fetch", "--source", "uci-default-credit"])

    exit_code = main(["data", "verify"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "OK" in captured.out


@responses.activate
def test_data_verify_detects_tampered_file(
    sandboxed_data_cli: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    responses.add(responses.GET, UCI_FIXTURE_URL, body=b"id,x\n1,2\n", status=200)
    main(["data", "fetch", "--source", "uci-default-credit"])

    downloaded_file = sandboxed_data_cli / "data" / "raw" / "uci_default_credit" / "fixture.csv"
    downloaded_file.write_bytes(b"tampered,content\n0,0\n")

    exit_code = main(["data", "verify"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "MISMATCH" in captured.out


# --- audit ---------------------------------------------------------------------


def test_data_audit_without_manifest_fails_cleanly_and_does_not_download(
    sandboxed_data_cli: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(["data", "audit"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "nothing has been acquired" in captured.out.lower()


@responses.activate
def test_data_audit_writes_quality_metrics_and_updates_manifest_counts(
    sandboxed_data_cli: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    responses.add(responses.GET, UCI_FIXTURE_URL, body=b"ID,X1\n1,10\n2,20\n3,30\n", status=200)
    main(["data", "fetch", "--source", "uci-default-credit"])

    exit_code = main(["data", "audit"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "3 rows x 2 cols" in captured.out

    metrics_path = sandboxed_data_cli / "reports" / "data_audit" / "quality_metrics.json"
    assert metrics_path.is_file()
    payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert "uci-default-credit" in payload["sources"]

    manifest_path = sandboxed_data_cli / "data" / "metadata" / "file_manifest.csv"
    with manifest_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["num_rows"] == "3"
    assert rows[0]["num_columns"] == "2"
    assert rows[0]["verification_status"] == "audited"


# --- multi-source: per-format audit loaders and --source filters -----------------


@responses.activate
def test_data_fetch_bcb_group_alias_fetches_all_bcb_sources(
    sandboxed_multi_source_cli: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    responses.add(
        responses.GET, BCB_FIXTURE_URL, json=[{"data": "01/01/2020", "valor": "100"}], status=200
    )

    exit_code = main(["data", "fetch", "--source", "bcb-sgs"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "bcb-sgs-20570" in captured.out
    json_file = sandboxed_multi_source_cli / "data" / "raw" / "bcb_sgs" / "bcb_sgs_20570.json"
    assert json_file.is_file()


def test_data_fetch_bcb_group_alias_fails_when_no_bcb_sources_registered(
    sandboxed_data_cli: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The single-source sandbox only registers a http_get source.
    exit_code = main(["data", "fetch", "--source", "bcb-sgs"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "No BCB SGS sources registered" in captured.out


@responses.activate
def test_data_audit_south_german_credit_loader_reads_extracted_asc(
    sandboxed_multi_source_cli: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    responses.add(
        responses.GET,
        SOUTH_GERMAN_FIXTURE_URL,
        body=_south_german_credit_zip_bytes(),
        status=200,
        content_type="application/zip",
    )

    fetch_exit = main(["data", "fetch", "--source", "south-german-credit"])
    assert fetch_exit == 0

    exit_code = main(["data", "audit", "--source", "south-german-credit"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "3 rows x 3 cols" in captured.out


@responses.activate
def test_data_audit_bcb_loader_reads_json_series(
    sandboxed_multi_source_cli: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    responses.add(
        responses.GET,
        BCB_FIXTURE_URL,
        json=[
            {"data": "01/01/2020", "valor": "100"},
            {"data": "01/02/2020", "valor": "110"},
        ],
        status=200,
    )
    main(["data", "fetch", "--source", "bcb-sgs-20570"])

    exit_code = main(["data", "audit", "--source", "bcb-sgs-20570"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "2 rows x 2 cols" in captured.out


@responses.activate
def test_data_verify_source_filter_limits_output_to_one_source(
    sandboxed_multi_source_cli: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    responses.add(responses.GET, UCI_FIXTURE_URL, body=b"id,x\n1,2\n", status=200)
    responses.add(
        responses.GET,
        SOUTH_GERMAN_FIXTURE_URL,
        body=_south_german_credit_zip_bytes(),
        content_type="application/zip",
    )
    main(["data", "fetch", "--source", "uci-default-credit"])
    main(["data", "fetch", "--source", "south-german-credit"])
    capsys.readouterr()  # discard fetch output - only verify's output is under test

    exit_code = main(["data", "verify", "--source", "south-german-credit"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "south-german-credit" in captured.out
    assert "uci-default-credit" not in captured.out


def test_data_verify_source_filter_unknown_source_reports_no_entries(
    sandboxed_data_cli: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Write an empty-but-valid manifest so the "no manifest at all" branch
    # isn't what's being tested here - only the --source filter is.
    manifest_path = sandboxed_data_cli / "data" / "metadata" / "file_manifest.csv"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        "source_id,relative_path,filename,size_bytes,sha256,retrieved_at_utc,url,format,"
        "num_rows,num_columns,verification_status,source_version_or_date,license,notes\n",
        encoding="utf-8",
    )

    exit_code = main(["data", "verify", "--source", "does-not-exist"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "No manifest entries found" in captured.out


def test_data_sources_reports_coherence_issues_for_unbacked_verified_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    registry_yaml = _minimal_registry_yaml().replace("status: approved", "status: verified")
    _setup_sandbox(tmp_path, monkeypatch, registry_yaml)

    exit_code = main(["data", "sources"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Coherence issues:" in captured.out
    assert "no manifest entry exists" in captured.out


# --- top-level dispatch ----------------------------------------------------------


def test_data_without_subcommand_prints_usage(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["data"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "credlens data" in captured.out


def test_doctor_reports_data_sources_status(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["doctor"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "data_sources" in captured.out
    assert "registered" in captured.out
