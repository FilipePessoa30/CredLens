"""Phase 10 gate B - guards against tolerance-masking patterns creeping
back into `.github/workflows/ci.yml`. A `|| true` (or equivalent) after a
critical validation command silently turns a real failure into a green
check mark; the incident this test defends against is exactly that
pattern, previously present on the CI-scoped independent-validation step
(removed once the permutation counts were raised enough - see gate B's
note in that step and in `config/model_validation/validation.yml`) - to
mask an unwinnable-at-that-scale statistical gate.

Fast, pure parsing test - no subprocess, no CredLens import.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml

from credlens.release.integrity import CI_WORKFLOW_MASKING_PATTERNS

REPO_ROOT = Path(__file__).resolve().parent.parent

WORKFLOW_PATH = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "ci.yml"
PYPROJECT_PATH = Path(__file__).resolve().parent.parent / "pyproject.toml"
GITIGNORE_PATH = Path(__file__).resolve().parent.parent / ".gitignore"

# Shared with credlens.release.integrity (the `credlens release validate`
# CLI check runs the exact same denylist/parser against this same file) -
# a denylist of KNOWN masking idioms, not an attempt at a general shell
# parser; anything added here must be something actually seen (or
# plausibly used) to hide a failure.
_TOLERANCE_MASKING_PATTERNS = CI_WORKFLOW_MASKING_PATTERNS

# Commands that represent a critical validation/gate check - if any of
# these substrings appear in a step's `run:` text, that step is treated
# as security-critical and is held to the no-masking rule even more
# strictly (this list is informational for the assertion messages; the
# denylist scan above already applies to every step regardless).
_CRITICAL_VALIDATION_COMMANDS = (
    "validate-independent",
    "audit-negative-controls",
    "audit-collinearity",
    "model validate",
    "dbt build",
    "dbt test",
    "pytest",
    "ruff check",
    "mypy",
)


def _load_workflow() -> tuple[dict[str, Any], str]:
    assert WORKFLOW_PATH.is_file(), f"CI workflow not found at {WORKFLOW_PATH}"
    with WORKFLOW_PATH.open(encoding="utf-8") as handle:
        raw_text = handle.read()
    # PyYAML chokes on the bare `on:` workflow-trigger key only when it is
    # parsed as a boolean by very old YAML 1.1 loaders; the modern
    # safe_load handles it correctly, so no special-casing is needed here.
    workflow: dict[str, Any] = yaml.safe_load(raw_text)
    return workflow, raw_text


def _iter_steps(workflow: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    """Yields (job_name, step_name, step_dict) for every step with a `run:` key."""
    steps: list[tuple[str, str, dict[str, Any]]] = []
    for job_name, job in workflow.get("jobs", {}).items():
        for step in job.get("steps", []):
            if "run" in step:
                steps.append((job_name, step.get("name", "<unnamed>"), step))
    return steps


class TestNoToleranceMasking:
    def test_workflow_file_exists_and_parses(self) -> None:
        workflow, _ = _load_workflow()
        assert "jobs" in workflow
        assert len(workflow["jobs"]) > 0

    def test_no_masking_pattern_in_any_run_step(self) -> None:
        workflow, _ = _load_workflow()
        offenders = []
        for job_name, step_name, step in _iter_steps(workflow):
            run_text = step["run"]
            for pattern in _TOLERANCE_MASKING_PATTERNS:
                if pattern in run_text:
                    offenders.append(f"job={job_name!r} step={step_name!r} pattern={pattern!r}")
        assert offenders == [], (
            f"Found tolerance-masking pattern(s) hiding a possible critical failure: {offenders}"
        )

    def test_no_continue_on_error_true_anywhere(self) -> None:
        workflow, _ = _load_workflow()
        offenders = []
        for job_name, job in workflow.get("jobs", {}).items():
            if job.get("continue-on-error") is True:
                offenders.append(f"job={job_name!r} (job-level)")
            for step in job.get("steps", []):
                if step.get("continue-on-error") is True:
                    offenders.append(f"job={job_name!r} step={step.get('name', '<unnamed>')!r}")
        assert offenders == [], f"Found continue-on-error: true: {offenders}"

    @pytest.mark.parametrize("command_substring", _CRITICAL_VALIDATION_COMMANDS)
    def test_critical_commands_when_present_are_never_followed_by_masking(
        self, command_substring: str
    ) -> None:
        workflow, _ = _load_workflow()
        found_at_least_one = False
        for job_name, step_name, step in _iter_steps(workflow):
            run_text = step["run"]
            if command_substring not in run_text:
                continue
            found_at_least_one = True
            for pattern in _TOLERANCE_MASKING_PATTERNS:
                assert pattern not in run_text, (
                    f"Critical command '{command_substring}' in job={job_name!r} "
                    f"step={step_name!r} is masked by pattern {pattern!r}"
                )
        # Not every command is guaranteed to be present (ruff/mypy/pytest
        # etc. run in different jobs than dbt/model validation) - this
        # loop is a no-op scan when a given command isn't used at all,
        # which is fine; the point is that IF it is used, it is unmasked.
        _ = found_at_least_one

    def test_model_validation_ci_scoped_step_has_no_trailing_true(self) -> None:
        _, raw_text = _load_workflow()
        assert "validate-independent --model-id CI_MODEL_SMOKE_v1 --ci" in raw_text
        assert "validate-independent --model-id CI_MODEL_SMOKE_v1 --ci || true" not in raw_text

    def test_negative_controls_ci_scoped_permutation_counts_can_mathematically_pass(self) -> None:
        """At CI's reduced permutation count, alpha must be reachable -
        i.e. 1/(n_ci+1) <= alpha - otherwise the gate is unwinnable and a
        future author would be tempted to reintroduce `|| true`."""
        validation_cfg_path = (
            Path(__file__).resolve().parent.parent
            / "config"
            / "model_validation"
            / "validation.yml"
        )
        cfg = yaml.safe_load(validation_cfg_path.read_text(encoding="utf-8"))
        perm_cfg = cfg["permutation_test"]
        for control_name in ("control1_score_label", "control2_pipeline_retrain"):
            control_cfg = perm_cfg[control_name]
            n_ci = int(control_cfg["n_permutations_ci"])
            alpha = float(control_cfg["alpha"])
            smallest_achievable_p = 1.0 / (n_ci + 1)
            assert smallest_achievable_p <= alpha, (
                f"{control_name}: with n_permutations_ci={n_ci}, the smallest "
                f"achievable empirical p-value is {smallest_achievable_p:.4f}, which "
                f"can never satisfy alpha={alpha} - this gate would be mathematically "
                "unwinnable at CI scale, inviting a `|| true` workaround."
            )


# Matches a `pytest <file-globs...> -m <marker-expr>` invocation inside a
# workflow `run:` block - captures the space-separated glob list and the
# (possibly quoted) marker expression.
_PYTEST_MARKER_INVOCATION = re.compile(
    r"pytest\s+((?:[\w./*_-]+\s+)+)-m\s+(\"[^\"]+\"|'[^']+'|\S+)"
)


def _pytest_marker_invocations(raw_text: str) -> list[tuple[str, str]]:
    """Every `pytest <globs> -m <expr>` invocation found anywhere in the
    workflow's raw text, as (globs_string, marker_expr) pairs. A plain
    regex scan (not per-step) - deliberately broad, since the real bug
    this defends against (a glob+marker combination matching zero tests)
    can hide in a multi-line `run: |` block just as easily as a one-liner."""
    return [
        (m.group(1).strip(), m.group(2).strip("\"'"))
        for m in _PYTEST_MARKER_INVOCATION.finditer(raw_text)
    ]


class TestMarkerFilteredInvocationsActuallyCollectTests:
    """Fase 11B - the real, 100%-reproducible bug this class defends
    against: `pytest tests/test_warehouse_*.py tests/test_generation_*.py
    -m slow` matched ZERO tests (none of those 21 files had ANY test
    marked `slow`), so pytest exited 5 ("no tests collected") on every
    single CI run since the dedicated job was introduced - never a
    Linux-vs-Windows environment difference, reproduced identically on
    this machine. Every `pytest <globs> -m <expr>` invocation in ci.yml
    is now verified, generically, to collect at least one test - so a
    FUTURE glob/marker combination that matches nothing fails locally
    long before it ever reaches CI."""

    def test_every_marker_filtered_pytest_invocation_collects_at_least_one_test(
        self,
    ) -> None:
        _, raw_text = _load_workflow()
        invocations = _pytest_marker_invocations(raw_text)
        assert invocations, "expected to find at least one 'pytest <globs> -m <expr>' invocation"

        failures = []
        for globs_str, marker_expr in invocations:
            # `subprocess.run` with a list never invokes a shell, so a
            # literal `*` would reach pytest un-expanded (unlike the real
            # `run:` step, executed by bash, which expands it first) -
            # expand every glob the same way bash would.
            expanded_paths: list[str] = []
            for pattern in globs_str.split():
                matches = sorted(REPO_ROOT.glob(pattern))
                expanded_paths.extend(str(p.relative_to(REPO_ROOT)) for p in matches)
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    *expanded_paths,
                    "-m",
                    marker_expr,
                    "--collect-only",
                    "-q",
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )
            output = result.stdout + result.stderr
            if "no tests ran" in output.lower() or "no tests collected" in output.lower():
                failures.append(f"globs={globs_str!r} marker={marker_expr!r}\n{output[-400:]}")

        assert failures == [], (
            "The following pytest invocation(s) from ci.yml collect ZERO tests - "
            "this exact pattern caused every 'no tests collected' (exit 5) CI failure:\n\n"
            + "\n---\n".join(failures)
        )


class TestMypyPythonVersionMatchesTheCiMatrix:
    """Fase 11B - the real, reproduced root cause of the Python 3.12
    'Lint, format, type-check' job failing while the identical Python
    3.11 job passed: `[tool.mypy]` hardcoded `python_version = "3.11"`,
    so mypy parsed EVERY stub - including numpy's own bundled
    `__init__.pyi` - under 3.11 grammar even when actually running
    under the 3.12 interpreter. `uv sync --python 3.12` resolves numpy
    2.5.1 (vs. 2.4.6 under 3.11), whose stub uses a PEP 695 `type X =
    ...` statement at line 737 - valid Python 3.12+ syntax, invalid
    under a 3.11 parse target - producing `error: Type statement is
    only supported in Python 3.12 and greater [syntax]` and aborting
    the entire run ("errors prevented further checking"), reproduced
    locally byte-for-byte via `uv run --python 3.12 mypy src tests
    dashboard`. Removing the pin lets mypy infer its target from
    whichever interpreter it actually runs under - exactly what a
    multi-version CI matrix needs - confirmed clean (0 errors) under
    both 3.11 and 3.12 after the fix."""

    def test_mypy_config_does_not_hardcode_a_python_version(self) -> None:
        pyproject = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
        mypy_config = pyproject["tool"]["mypy"]
        assert "python_version" not in mypy_config, (
            "[tool.mypy] must not hardcode python_version - mypy should infer its "
            "target from whichever interpreter it actually runs under, matching "
            "CI's own Python 3.11/3.12 matrix (see ci.yml's `quality` job) - a "
            "hardcoded pin previously caused mypy to parse a newer-numpy-only "
            "stub under the wrong grammar and abort with a syntax error."
        )

    def test_ci_matrix_pins_at_least_the_versions_pyproject_requires(self) -> None:
        pyproject = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
        requires_python = pyproject["project"]["requires-python"]
        assert requires_python.startswith(">="), requires_python
        minimum = requires_python.removeprefix(">=")

        workflow, _ = _load_workflow()
        matrix_versions = workflow["jobs"]["quality"]["strategy"]["matrix"]["python-version"]
        assert minimum in matrix_versions, (
            f"pyproject.toml requires-python={requires_python!r} but ci.yml's "
            f"quality job matrix only tests {matrix_versions!r}"
        )


class TestDemoFactoryGitignoreRules:
    """Fase 11C Gate B - `credlens demo prepare` regenerates the
    dashboard's demo bundle and the monitoring reference+batches
    on demand; none of it may ever be silently re-tracked. Verified
    against REAL git behavior (`git check-ignore`), not just a string
    search over .gitignore's own text, in a throwaway tmp_path repo
    that copies this repo's real .gitignore - never the real repo's
    own index."""

    @pytest.fixture()
    def gitignore_copy_repo(self, tmp_path: Path) -> Path:
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        (tmp_path / ".gitignore").write_bytes(GITIGNORE_PATH.read_bytes())
        return tmp_path

    @pytest.mark.parametrize(
        "candidate_path",
        [
            "dashboard/demo_data/funnel_monthly.parquet",
            "dashboard/demo_data/demo_factory_manifest.json",
            # Fase 11D - git rm --cached'd: orphaned once the *.parquet
            # tables they reference became gitignored (Fase 11C), a
            # confirmed regression on a genuinely fresh clone (see the
            # matching .gitignore comment). The factory regenerates both.
            "dashboard/demo_data/manifest.json",
            "dashboard/demo_data/insights.yml",
            "reports/monitoring/reference/REF_SOME_MODEL.json",
            "reports/monitoring/reference/REF_SOME_MODEL__population.csv",
            "reports/monitoring/reference/REF_SOME_MODEL__alert_thresholds.json",
            "reports/monitoring/reference/REF_SOME_MODEL__factory_manifest.json",
            "reports/monitoring/runs/BATCHSET_REF_SOME_MODEL/batch_manifest.json",
            "reports/monitoring/runs/RUN_x/run.json",
            # Fase 11E - the three `EXP_behavioral_default_v*__{suffix}.
            # csv` exceptions below must NOT also un-ignore a CI-scoped
            # experiment sharing the same table-name suffix - confirmed
            # as a real, direct contributor to "Prove no official
            # modeling/model_validation artifact was ever altered"
            # failing on a genuine GitHub Actions run (31219985691, PR
            # #2, SHA 4132949): CI_MODEL_SMOKE__vif.csv/__coefficient_
            # classification.csv/__thresholds.csv showed up as
            # untracked-but-not-ignored - see the matching .gitignore
            # comments (narrowed from a bare `*` to the official
            # experiment-id family).
            "reports/model_validation/tables/CI_MODEL_SMOKE__vif.csv",
            "reports/model_validation/tables/CI_MODEL_SMOKE__coefficient_classification.csv",
            "reports/modeling/tables/CI_MODEL_SMOKE__thresholds.csv",
        ],
    )
    def test_generated_artifact_paths_are_ignored(
        self, gitignore_copy_repo: Path, candidate_path: str
    ) -> None:
        result = subprocess.run(
            ["git", "check-ignore", "-q", candidate_path],
            cwd=gitignore_copy_repo,
            capture_output=True,
        )
        assert result.returncode == 0, f"expected '{candidate_path}' to be gitignored"

    @pytest.mark.parametrize(
        "candidate_path",
        [
            "reports/monitoring/monitoring_report.md",
            "reports/monitoring/detection_evaluation.json",
            "reports/monitoring/false_alert_study.json",
            "warehouse/seeds/dim_dpd_bucket.csv",
            "reports/modeling/experiments/EXP_behavioral_default_v1/split_assignment.csv",
            "reports/modeling/tables/EXP_behavioral_default_v1__thresholds.csv",
            # Fase 11D - same category: a small, deterministic, per-
            # feature summary of the already-frozen official model, read
            # by production code (credlens.model_validation), not a bulk
            # per-row output - see the matching .gitignore comment.
            "reports/model_validation/tables/EXP_behavioral_default_v1__coefficient_classification.csv",
            # Fase 11E - same category as the entry directly above: a
            # small, deterministic, per-feature VIF table for the
            # already-frozen official model, read unconditionally by
            # production code (credlens.model_validation.remediation.
            # compare_five_models) - confirmed missing on a genuine
            # GitHub Actions Linux runner (FileNotFoundError in
            # test_cli_remediate_and_compare) - see the matching
            # .gitignore comment.
            "reports/model_validation/tables/EXP_behavioral_default_v1__vif.csv",
            "reports/model_validation/tables/EXP_behavioral_default_v2_reduced__vif.csv",
            "reports/model_validation/tables/EXP_behavioral_default_v2_reduced_stability_only__vif.csv",
            # Fase 11E - the portfolio-analysis layer's own official,
            # versioned output tables (aggregate-only, no PII) that the
            # committed case-study notebook reads directly - confirmed
            # missing on a genuine GitHub Actions Linux runner and via
            # WSL reproduction - see the matching .gitignore comment.
            "reports/portfolio_analysis/tables/funnel_monthly.csv",
            "reports/portfolio_analysis/tables/portfolio_monthly.csv",
            "reports/modeling/models/MODEL_behavioral_default_v1.joblib",
            "src/credlens/demo/factory.py",
            # Still tracked from before this factory existed - see the
            # matching .gitignore comment for why this one specific file
            # stays excepted from the blanket reports/monitoring/
            # reference/ ignore rule until a human authorizes `git rm
            # --cached` for it (unlike dashboard/demo_data/manifest.json/
            # insights.yml above, already removed in Fase 11D - this one
            # was audited separately and found NOT to break anything on
            # a fresh clone the way the dashboard pair did).
            "reports/monitoring/reference/REF_MODEL_behavioral_default_v1.json",
            "reports/monitoring/reference/REF_MODEL_behavioral_default_v1__alert_thresholds.json",
            "reports/monitoring/runs/BATCHSET_REF_MODEL_behavioral_default_v1/batch_manifest.json",
        ],
    )
    def test_official_evidence_and_source_paths_are_never_ignored(
        self, gitignore_copy_repo: Path, candidate_path: str
    ) -> None:
        result = subprocess.run(
            ["git", "check-ignore", "-q", candidate_path],
            cwd=gitignore_copy_repo,
            capture_output=True,
        )
        assert result.returncode == 1, f"'{candidate_path}' must NOT be gitignored"


class TestMonitoringJobFetchesUciDataset:
    """Fase 11C Gate H - static-audit regression test: the `monitoring`
    job runs on its own fresh runner (only a small model/experiment
    artifact crosses the `needs: modeling-validation` boundary), and both
    `credlens monitor create-reference` and every `tests/test_monitoring_
    *.py` slow test that uses the `phase9_isolated_repo_root` fixture
    (tests/conftest.py) need data/raw/uci_default_credit/ on disk -
    gitignored, never committed, and never fetched by an earlier job on
    the SAME runner. Without an explicit fetch step here, this job fails
    as soon as it actually gets to run - previously masked in practice by
    `modeling-validation`'s own separate failure keeping `needs:` from
    ever letting this job start at all."""

    def test_monitoring_job_fetches_the_uci_dataset_before_using_it(self) -> None:
        workflow, _raw_text = _load_workflow()
        monitoring_job = workflow["jobs"]["monitoring"]
        run_steps = [step.get("run", "") for step in monitoring_job["steps"] if "run" in step]

        fetch_indices = [i for i, run in enumerate(run_steps) if "credlens data fetch" in run]
        assert fetch_indices, "the `monitoring` job never fetches the UCI benchmark dataset"

        needs_it_indices = [
            i
            for i, run in enumerate(run_steps)
            if "test_monitoring_" in run or "monitor create-reference" in run
        ]
        assert needs_it_indices, "expected steps that need the UCI dataset were not found"
        assert fetch_indices[0] < min(needs_it_indices), (
            "the UCI fetch step must run before anything that needs data/raw/ on disk"
        )


class TestDataVerifyCallsAreScopedToWhatWasActuallyFetched:
    """Fase 11E - `credlens data verify` (no --source) checks EVERY
    source in the registry (uci-default-credit, south-german-credit, the
    two bcb-sgs series), not just whatever a preceding `credlens data
    fetch` call actually downloaded in THIS job. The `modeling-
    validation` job only ever fetches uci-default-credit, so an unscoped
    `data verify` right after it deterministically failed on every real
    run (100% reproducible, confirmed from an actual GitHub Actions log -
    not the network/rate-limit flakiness this was mistakenly assumed to
    be across three prior phases): "[MISSING] bcb-sgs-... / south-german-
    credit..." for the six sources this job never fetches, even though
    "[OK] uci-default-credit" - the one source that matters here -
    always passed. `--source <id>` scopes the check to exactly what was
    fetched."""

    def test_every_unscoped_data_fetch_is_not_followed_by_an_unscoped_data_verify(self) -> None:
        workflow, _raw_text = _load_workflow()
        for job_name, job in workflow.get("jobs", {}).items():
            run_steps = [step.get("run", "") for step in job.get("steps", []) if "run" in step]
            for run in run_steps:
                if "credlens data fetch --source" not in run:
                    continue
                assert "credlens data verify\n" not in run and not run.rstrip().endswith(
                    "credlens data verify"
                ), (
                    f"job '{job_name}' runs an unscoped 'credlens data verify' after fetching "
                    "only specific source(s) - it will always report every OTHER registered "
                    "source as missing. Use 'credlens data verify --source <id>' scoped to "
                    "exactly what this job fetched."
                )


class TestJobsRunningDashboardAppTestsInstallTheDashboardExtra:
    """Fase 11E - `streamlit` is only ever pulled in via the `dashboard`
    extra (see pyproject.toml / uv.lock: it has no dependency edge from
    the `dev` group or any other extra) - a job whose `Install
    dependencies` step omits `--extra dashboard` but later runs a test
    file that imports `streamlit.testing.v1.AppTest` at module scope
    fails deterministically at collection time with ModuleNotFoundError,
    never flakiness. Confirmed from a real GitHub Actions run
    (31193005240, PR #2, SHA 2a20874): `modeling-validation`'s "Model
    Lab - AppTest execution of the 9th dashboard page" step (`pytest
    tests/test_dashboard_model_lab.py`) failed this way, right after the
    VIF-table gap above was fixed and the job could finally run far
    enough to reach it. `monitoring`'s otherwise-identical `Install
    dependencies` step had the same gap for `tests/test_dashboard_
    monitoring_lab.py` - only masked so far by `needs: modeling-
    validation` keeping that job from ever starting."""

    def test_jobs_running_a_streamlit_apptest_file_install_the_dashboard_extra(self) -> None:
        workflow, _raw_text = _load_workflow()
        tests_dir = REPO_ROOT / "tests"
        apptest_files = sorted(
            path.name
            for path in tests_dir.glob("test_dashboard_*.py")
            if "from streamlit" in path.read_text(encoding="utf-8")
        )
        assert apptest_files, "expected at least one dashboard AppTest test file"

        for job_name, job in workflow.get("jobs", {}).items():
            run_steps = [step.get("run", "") for step in job.get("steps", []) if "run" in step]
            runs_an_apptest_file = any(
                any(fname in run for fname in apptest_files) for run in run_steps
            )
            if not runs_an_apptest_file:
                continue
            installs_dashboard_extra = any("--extra dashboard" in run for run in run_steps)
            assert installs_dashboard_extra, (
                f"job '{job_name}' runs a streamlit AppTest test file but its 'Install "
                "dependencies' step never passes '--extra dashboard' - streamlit is only "
                "pulled in via that extra (see uv.lock), so pytest will fail to even "
                "collect the file with ModuleNotFoundError."
            )


class TestModelLabAppTestRunsBeforeTheCiScopedCandidateExists:
    """Fase 11E - `credlens.dashboard.model_lab._default_experiment_index`
    has no notion of "the official candidate": it returns the experiment
    behind the alphabetically-FIRST `*.manifest.json` with status
    "candidate". `tests/test_dashboard_model_lab.py::test_defaults_to_
    the_registered_candidate_not_a_gate_d_sibling` is a real-repo
    regression check that asserts the page defaults to
    EXP_behavioral_default_v1 specifically - true as long as it is the
    ONLY registered candidate. The `modeling-validation` job's own
    CI-scoped pipeline registers a second candidate,
    CI_MODEL_SMOKE_v1, which sorts alphabetically before
    MODEL_behavioral_default_v1 - confirmed by direct reproduction (and
    a real GitHub Actions run, 31206294665: PR #2, SHA d6ae2ac) that
    once both exist, the assertion fails on real content, not a code
    defect. The AppTest step must run before that second candidate is
    registered."""

    def test_apptest_step_precedes_ci_scoped_candidate_registration(self) -> None:
        workflow, _raw_text = _load_workflow()
        job = workflow["jobs"]["modeling-validation"]
        step_names = [step.get("name", "") for step in job["steps"]]

        apptest_index = next(
            (i for i, name in enumerate(step_names) if "Model Lab - AppTest execution" in name),
            None,
        )
        register_index = next(
            (
                i
                for i, name in enumerate(step_names)
                if "register a candidate and validate it" in name
            ),
            None,
        )
        assert apptest_index is not None, "expected a 'Model Lab - AppTest execution' step"
        assert register_index is not None, "expected a 'register a candidate' step"
        assert apptest_index < register_index, (
            "the Model Lab AppTest step must run BEFORE 'register a candidate and validate "
            "it' - once CI_MODEL_SMOKE_v1 is also registered as a candidate, the AppTest's "
            "own real-repo regression check (which asserts the page defaults to "
            "EXP_behavioral_default_v1) fails, since it sorts after CI_MODEL_SMOKE_v1 "
            "alphabetically."
        )


class TestModelingValidationIntegrityCheckIgnoresItsOwnCiScopedOutput:
    """Fase 11E - `modeling-validation`'s own CI-scoped pipeline
    legitimately leaves untracked CI_MODEL_SMOKE* output under
    reports/modeling/ and reports/model_validation/ (models/experiments/
    tables/figures/lifecycle - none of it gitignored by design, since a
    genuinely new OFFICIAL candidate must be free to land in the same
    paths), cleaned up in a dedicated later step. Confirmed from a real
    GitHub Actions run (31219985691, PR #2, SHA 4132949) and by local
    reproduction of the exact CI pipeline: a plain `git status
    --porcelain` (no `--untracked-files=no`) on "Prove no official
    modeling/model_validation artifact was ever altered" sees those `??`
    entries too and fails regardless of whether any OFFICIAL/tracked
    artifact was actually altered. Separately, `reports/model_
    validation/lifecycle/MODEL_behavioral_default_v1.json` is an
    append-only, `timestamp_utc`-stamped audit log - never byte-
    reproducible by re-running `validate-independent` - so the restore
    step must also `git checkout --` afterward, exactly like the
    official EXP_behavioral_default_v1 retrain step above it already
    does."""

    def test_the_integrity_check_excludes_untracked_files(self) -> None:
        workflow, _raw_text = _load_workflow()
        job = workflow["jobs"]["modeling-validation"]
        run_steps = [step.get("run", "") for step in job["steps"] if "run" in step]
        check_step = next(
            (
                run
                for run in run_steps
                if "Prove no official" not in run and "git status --porcelain" in run
            ),
            None,
        )
        assert check_step is not None, "expected a 'git status --porcelain ...' integrity check"
        assert "--untracked-files=no" in check_step, (
            "the modeling-validation job's integrity check must pass '--untracked-files=no' - "
            "this job's own CI-scoped pipeline legitimately leaves untracked (and, by design, "
            "not gitignored) CI_MODEL_SMOKE* output under the same directories, cleaned up in "
            "a later step, not here."
        )

    def test_the_restore_step_checks_out_afterward(self) -> None:
        workflow, _raw_text = _load_workflow()
        job = workflow["jobs"]["modeling-validation"]
        restore_step = next(
            (
                step
                for step in job["steps"]
                if step.get("name") == "Model validation - restore the official decision/report"
            ),
            None,
        )
        assert restore_step is not None, "expected the restore step to still exist"
        run = restore_step.get("run", "")
        assert "git checkout -- reports/modeling/ reports/model_validation/" in run, (
            "the restore step must 'git checkout --' reports/modeling/ and reports/"
            "model_validation/ afterward - reports/model_validation/lifecycle/"
            "MODEL_behavioral_default_v1.json is an append-only, timestamp-stamped audit log "
            "that re-running validate-independent can never byte-reproduce."
        )


class TestCiModelSmokeArtifactUploadIncludesTheThresholdsTable:
    """Fase 11E - `credlens.monitoring.runner._top10_threshold` reads
    `reports/modeling/tables/{experiment_id}__thresholds.csv` directly -
    a load-bearing input to `credlens monitor run`, not incidental
    output (the same dependency the .gitignore comment for the official
    EXP_behavioral_default_v1__thresholds.csv documents). The
    `modeling-validation` job's "Upload the CI-scoped model/experiment
    artifacts for the monitoring job" step only uploaded experiments/
    and models/, never tables/ - confirmed missing by direct
    reproduction and a real GitHub Actions run (31226055768, PR #2, SHA
    00c8143): `credlens monitor run` in the `monitoring` job failed with
    FileNotFoundError for reports/modeling/tables/
    CI_MODEL_SMOKE__thresholds.csv."""

    def test_the_upload_step_includes_the_tables_directory(self) -> None:
        workflow, _raw_text = _load_workflow()
        job = workflow["jobs"]["modeling-validation"]
        upload_step = next(
            (
                step
                for step in job["steps"]
                if step.get("name")
                == "Upload the CI-scoped model/experiment artifacts for the monitoring job"
            ),
            None,
        )
        assert upload_step is not None, "expected the CI-scoped artifact upload step to exist"
        upload_path = upload_step.get("with", {}).get("path", "")
        assert "reports/modeling/tables/CI_MODEL_SMOKE" in upload_path, (
            "the CI-scoped artifact upload step must also include reports/modeling/tables/"
            "CI_MODEL_SMOKE* - credlens.monitoring.runner._top10_threshold reads "
            "{experiment_id}__thresholds.csv directly from there, and the `monitoring` job "
            "runs on a fresh runner with no filesystem shared with modeling-validation."
        )
