"""CredLens command-line interface.

Foundation phase: this CLI only verifies the installation and the project
scaffolding. It does not touch data, models, or dashboards - those belong
to later phases (see docs/roadmap.md).
"""

from __future__ import annotations

import argparse
import platform
import sys
from dataclasses import dataclass
from pathlib import Path

from credlens import __version__
from credlens.config import ConfigError, load_config
from credlens.logging_config import configure_logging, get_logger

logger = get_logger("cli")

_REQUIRED_DIRECTORIES = ("config", "docs", "src", "tests")
_MIN_PYTHON = (3, 11)


@dataclass(frozen=True)
class DoctorCheck:
    """A single foundation health check reported by `credlens doctor`."""

    name: str
    status: str  # "PASS" | "FAIL" | "INFO"
    detail: str


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="credlens",
        description=(
            "CredLens - Credit Risk & Portfolio Analytics. "
            "Foundation-phase CLI: installation and scaffolding checks only."
        ),
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Show the CredLens package version and exit.",
    )

    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("version", help="Print the CredLens package version.")
    subparsers.add_parser(
        "doctor",
        help="Check that the foundation (Python, package, config, directories) is healthy.",
    )

    return parser


def _cmd_version() -> int:
    print(f"credlens {__version__}")
    return 0


def run_doctor_checks() -> list[DoctorCheck]:
    """Run all foundation health checks and return their results.

    Exposed as a standalone function so it can be unit tested without
    parsing the CLI's stdout.
    """
    checks: list[DoctorCheck] = []

    python_version = platform.python_version()
    python_ok = sys.version_info >= _MIN_PYTHON
    checks.append(DoctorCheck("python_version", "PASS" if python_ok else "FAIL", python_version))

    checks.append(DoctorCheck("package_version", "PASS", __version__))

    try:
        config = load_config()
        checks.append(DoctorCheck("config_file", "PASS", str(config.source_path)))
    except ConfigError as exc:
        checks.append(DoctorCheck("config_file", "FAIL", str(exc)))

    for directory in _REQUIRED_DIRECTORIES:
        exists = Path(directory).is_dir()
        status = "PASS" if exists else "FAIL"
        checks.append(DoctorCheck(f"directory:{directory}", status, directory))

    # Data acquisition is a future phase. Its absence is expected and must
    # not be reported as a failure of the current installation.
    checks.append(DoctorCheck("dataset", "INFO", "not configured (future phase)"))

    return checks


def _cmd_doctor() -> int:
    checks = run_doctor_checks()

    print("CredLens doctor")
    print("=" * 16)
    for check in checks:
        print(f"[{check.status:>4}] {check.name:<24} {check.detail}")

    has_failure = any(check.status == "FAIL" for check in checks)
    print()
    print(f"Result: {'FAIL' if has_failure else 'OK'}")
    return 1 if has_failure else 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns a process exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    configure_logging()
    logger.debug("credlens CLI invoked with command=%s version_flag=%s", args.command, args.version)

    if args.version:
        return _cmd_version()
    if args.command == "version":
        return _cmd_version()
    if args.command == "doctor":
        return _cmd_doctor()

    parser.print_help()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
