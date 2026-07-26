"""Tests for credlens.generation.testing_support and the injectable
output-root mechanism it wraps (Phase 6 gate B). Proves, with real
generation calls (not mocks), the exact requirements section 5.3 of the
Phase 6 brief lists:

  - a test generates and removes data ONLY under its own tmp_path root;
  - a pre-existing "official" suite is left completely untouched by a
    colliding-parameter test that uses an isolated root;
  - safe_rmtree() refuses overly broad/unauthorized roots;
  - relative and absolute paths cannot escape the allowed root.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from credlens.generation.config import (
    DEFAULT_CONFIG_PATH,
    load_generation_config,
    with_output_dirs,
)
from credlens.generation.orchestrator import generate_scenario
from credlens.generation.suite import generate_suite, load_suite_manifest
from credlens.generation.testing_support import (
    PROTECTED_ROOTS,
    UnsafeCleanupError,
    assert_root_is_safe,
    delete_exact_run_dir,
    isolated_manifest_dir,
    isolated_output_dirs,
    safe_rmtree,
)

# The exact coordinates the Phase 5 report documented as colliding with a
# real official run - used here DELIBERATELY, to prove the isolation
# mechanism (not a different seed) is what prevents the collision.
_COLLIDING_SEED = 2026
_COLLIDING_SCENARIO = "baseline"
_COLLIDING_SCALE = "smoke"


def _real_baseline_smoke_2026_run_id_if_known() -> str | None:
    # Best-effort: if the real official run exists on disk, fetch its
    # exact id for a stronger assertion; otherwise skip that comparison
    # rather than depend on repository state this test doesn't control.
    real_root = Path("data/synthetic")
    if not real_root.is_dir():
        return None
    for entry in real_root.iterdir():
        if entry.name.startswith("RUN_baseline_smoke_2026_"):
            return entry.name
    return None


class TestIsolatedGenerationNeverTouchesSharedRoots:
    def test_generate_scenario_writes_only_under_tmp_path(self, tmp_path: Path) -> None:
        operational_dir, truth_dir = isolated_output_dirs(tmp_path)
        config = with_output_dirs(
            load_generation_config(DEFAULT_CONFIG_PATH),
            operational_dir=operational_dir,
            truth_dir=truth_dir,
        )

        outcome = generate_scenario(
            scenario=_COLLIDING_SCENARIO,
            scale_name=_COLLIDING_SCALE,
            seed=_COLLIDING_SEED,
            force=True,
            config_override=config,
        )

        # Every byte this call wrote lives under tmp_path - nothing was
        # ever written to the real data/synthetic/ or
        # data/synthetic_truth/ roots for this run id.
        assert str(outcome.operational_dir).startswith(str(operational_dir))
        assert str(outcome.truth_dir).startswith(str(truth_dir))
        assert not (Path("data/synthetic") / outcome.generation_run_id).exists()
        assert not (Path("data/synthetic_truth") / outcome.generation_run_id).exists()

        safe_rmtree(tmp_path, allowed_root=tmp_path)
        assert not operational_dir.exists()

    def test_colliding_coordinates_do_not_produce_the_official_run_directory(
        self, tmp_path: Path
    ) -> None:
        """Proves isolation holds even with parameters IDENTICAL to a
        real official run's own (scenario, scale, seed) - the exact case
        section 5.2 forbids solving by 'just change the seed'."""
        operational_dir, truth_dir = isolated_output_dirs(tmp_path)
        config = with_output_dirs(
            load_generation_config(DEFAULT_CONFIG_PATH),
            operational_dir=operational_dir,
            truth_dir=truth_dir,
        )
        outcome = generate_scenario(
            scenario=_COLLIDING_SCENARIO,
            scale_name=_COLLIDING_SCALE,
            seed=_COLLIDING_SEED,
            force=True,
            config_override=config,
        )
        # Overriding the output roots is part of the hashed config
        # payload, so even the run_id itself differs from what the real
        # baseline/smoke/2026 config would produce - defense in depth on
        # top of the physical directory separation.
        real_run_id = _real_baseline_smoke_2026_run_id_if_known()
        if real_run_id is not None:
            assert outcome.generation_run_id != real_run_id
        assert outcome.generation_run_id.startswith("RUN_baseline_smoke_2026_")


class TestOfficialSuiteSurvivesACollidingSuiteGeneration:
    def test_official_suite_manifest_and_runs_untouched(self, tmp_path: Path) -> None:
        """The concrete scenario the Phase 5 report describes: a suite
        generated at the SAME (scale, seed) an official demonstration
        suite already occupies must not disturb that official suite's
        manifest or run directories at all, because it never writes to
        their shared roots in the first place."""
        official_manifest_path = (
            Path("reports/synthetic_validation/suites")
            / f"SUITE_{_COLLIDING_SCALE}_{_COLLIDING_SEED}.json"
        )
        official_manifest_existed_before = official_manifest_path.is_file()
        official_manifest_before = (
            official_manifest_path.read_text(encoding="utf-8")
            if official_manifest_existed_before
            else None
        )
        real_run_id_before = _real_baseline_smoke_2026_run_id_if_known()

        operational_dir, truth_dir = isolated_output_dirs(tmp_path)
        manifest_dir = isolated_manifest_dir(tmp_path)

        outcome = generate_suite(
            scale_name=_COLLIDING_SCALE,
            seed=_COLLIDING_SEED,
            force=True,
            output_dirs=(operational_dir, truth_dir),
            manifest_dir=manifest_dir,
        )

        assert outcome.manifest_path == manifest_dir / f"{outcome.suite_id}.json"
        assert outcome.manifest_path.is_file()
        # The isolated manifest lives entirely under tmp_path - nowhere
        # near the shared, git-tracked reports/ root.
        assert str(outcome.manifest_path).startswith(str(manifest_dir))
        assert str(outcome.manifest_path).startswith(str(tmp_path))

        # The official manifest (if it existed) is byte-identical to
        # before - this isolated suite generation never wrote to it.
        if official_manifest_existed_before:
            assert official_manifest_path.is_file()
            assert official_manifest_path.read_text(encoding="utf-8") == official_manifest_before
        # The official baseline run's id (if it existed before) still
        # resolves to a real directory - this isolated suite generation
        # never touched it.
        if real_run_id_before is not None:
            assert (Path("data/synthetic") / real_run_id_before).is_dir()

        loaded = load_suite_manifest(outcome.suite_id, manifest_dir=manifest_dir)
        assert loaded["suite_id"] == outcome.suite_id

        safe_rmtree(tmp_path, allowed_root=tmp_path)


class TestSafeRmtreeRejectsUnauthorizedRoots:
    @pytest.mark.parametrize("protected", PROTECTED_ROOTS)
    def test_rejects_every_protected_root_directly(self, protected: str) -> None:
        with pytest.raises(UnsafeCleanupError):
            assert_root_is_safe(Path(protected))

    def test_rejects_a_root_that_contains_a_protected_root(self) -> None:
        # "data" contains "data/synthetic" - must be rejected even though
        # "data" itself is not literally in PROTECTED_ROOTS.
        with pytest.raises(UnsafeCleanupError):
            assert_root_is_safe(Path("data"))

    def test_rejects_the_repo_root_itself(self) -> None:
        with pytest.raises(UnsafeCleanupError):
            assert_root_is_safe(Path("."))

    def test_accepts_a_genuine_tmp_path_root(self, tmp_path: Path) -> None:
        resolved = assert_root_is_safe(tmp_path)
        assert resolved == tmp_path.resolve()

    def test_safe_rmtree_refuses_to_delete_a_protected_path(self) -> None:
        with pytest.raises(UnsafeCleanupError):
            safe_rmtree(Path("data/synthetic/anything"), allowed_root=Path("data/synthetic"))


class TestSafeRmtreeNoPathEscape:
    def test_relative_traversal_outside_allowed_root_is_rejected(self, tmp_path: Path) -> None:
        inner = tmp_path / "inner"
        inner.mkdir()
        outside = tmp_path.parent / "escaped_via_dotdot"
        escape_attempt = inner / ".." / ".." / outside.name
        with pytest.raises(UnsafeCleanupError):
            safe_rmtree(escape_attempt, allowed_root=inner)

    def test_absolute_path_outside_allowed_root_is_rejected(self, tmp_path: Path) -> None:
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        other = tmp_path / "sibling_not_allowed"
        other.mkdir()
        with pytest.raises(UnsafeCleanupError):
            safe_rmtree(other, allowed_root=allowed)

    def test_path_genuinely_inside_allowed_root_is_deleted(self, tmp_path: Path) -> None:
        allowed = tmp_path / "allowed"
        target = allowed / "nested" / "dir"
        target.mkdir(parents=True)
        marker = target / "marker.txt"
        marker.write_text("x", encoding="utf-8")

        safe_rmtree(target, allowed_root=allowed)

        assert not target.exists()
        assert allowed.exists()  # only the target subtree was removed


class TestSequentialIsolatedBuildsDoNotInterfere:
    def test_two_isolated_generations_do_not_remove_each_others_output(
        self, tmp_path: Path
    ) -> None:
        root_a = tmp_path / "a"
        root_b = tmp_path / "b"
        op_a, truth_a = isolated_output_dirs(root_a)
        op_b, truth_b = isolated_output_dirs(root_b)

        config_a = with_output_dirs(
            load_generation_config(DEFAULT_CONFIG_PATH), operational_dir=op_a, truth_dir=truth_a
        )
        config_b = with_output_dirs(
            load_generation_config(DEFAULT_CONFIG_PATH), operational_dir=op_b, truth_dir=truth_b
        )

        outcome_a = generate_scenario(
            scenario="baseline",
            scale_name="smoke",
            seed=909_001,
            force=True,
            config_override=config_a,
        )
        outcome_b = generate_scenario(
            scenario="baseline",
            scale_name="smoke",
            seed=909_002,
            force=True,
            config_override=config_b,
        )

        # Cleaning up root_a's tree must never touch root_b's tree.
        safe_rmtree(root_a, allowed_root=root_a)
        assert not (op_a / outcome_a.generation_run_id).exists()
        assert (op_b / outcome_b.generation_run_id).exists()

        safe_rmtree(root_b, allowed_root=root_b)
        assert not (op_b / outcome_b.generation_run_id).exists()


class TestDeleteExactRunDir:
    """delete_exact_run_dir is the narrow escape hatch legacy,
    not-yet-isolated-root CLI-level tests use (e.g. test_monte_carlo_two_seeds)
    - stricter than safe_rmtree: an allowlist of exactly two roots, a
    strict RUN_... id shape, and direct-child-only resolution."""

    def test_rejects_a_root_not_in_the_allowlist(self, tmp_path: Path) -> None:
        with pytest.raises(UnsafeCleanupError):
            delete_exact_run_dir(tmp_path, "RUN_whatever_0000")

    def test_rejects_an_empty_run_id(self) -> None:
        with pytest.raises(UnsafeCleanupError):
            delete_exact_run_dir(Path("data/synthetic"), "")

    def test_rejects_a_run_id_with_traversal_sequence(self) -> None:
        with pytest.raises(UnsafeCleanupError):
            delete_exact_run_dir(Path("data/synthetic"), "../escaped")

    def test_rejects_a_run_id_not_matching_credlens_shape(self) -> None:
        with pytest.raises(UnsafeCleanupError):
            delete_exact_run_dir(Path("data/synthetic"), "not_a_real_run_id")

    def test_deletes_only_the_exact_named_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Exercise the real allowlisted root name, but redirect cwd so the
        # test never touches the real data/synthetic/ tree.
        monkeypatch.chdir(tmp_path)
        root = tmp_path / "data" / "synthetic"
        target = root / "RUN_keep_me_out_0001"
        sibling = root / "RUN_do_not_touch_0002"
        target.mkdir(parents=True)
        sibling.mkdir(parents=True)

        delete_exact_run_dir(Path("data/synthetic"), "RUN_keep_me_out_0001")

        assert not target.exists()
        assert sibling.exists()
