"""Tests for credlens.model_validation.permutation_audit (Phase 10 gate
A) - the closed-form theoretical null SE, the self-calibrating centering
z-test, the amplitude-vs-theory check, and duplicate-permutation
detection. All fast, pure-function tests.
"""

from __future__ import annotations

import numpy as np
import pytest

from credlens.model_validation.permutation_audit import (
    amplitude_test,
    centering_test,
    detect_duplicate_permutations,
    theoretical_null_auc_se,
)


class TestTheoreticalNullAucSe:
    def test_matches_known_hanley_mcneil_formula(self) -> None:
        # n_pos=1327, n_neg=4673 (this project's real validation split)
        se = theoretical_null_auc_se(1327, 4673)
        assert se == pytest.approx(0.008979, abs=1e-5)

    def test_raises_with_zero_positives(self) -> None:
        with pytest.raises(ValueError):
            theoretical_null_auc_se(0, 100)

    def test_raises_with_zero_negatives(self) -> None:
        with pytest.raises(ValueError):
            theoretical_null_auc_se(100, 0)

    def test_smaller_samples_have_larger_se(self) -> None:
        assert theoretical_null_auc_se(50, 50) > theoretical_null_auc_se(500, 500)


class TestCenteringTest:
    def test_perfectly_centered_distribution_passes(self) -> None:
        rng = np.random.default_rng(0)
        distribution = rng.normal(loc=0.5, scale=0.01, size=1000)
        result = centering_test(distribution, expected_mean=0.5, sigma_multiplier=3.0)
        assert result.centered

    def test_clearly_off_center_distribution_fails(self) -> None:
        distribution = np.full(1000, 0.9)
        result = centering_test(distribution, expected_mean=0.5, sigma_multiplier=3.0)
        assert not result.centered

    def test_tightens_automatically_with_more_permutations(self) -> None:
        rng = np.random.default_rng(1)
        small = rng.normal(loc=0.51, scale=0.05, size=10)
        large = rng.normal(loc=0.51, scale=0.05, size=10000)
        se_small = centering_test(small).standard_error_of_mean
        se_large = centering_test(large).standard_error_of_mean
        assert se_large < se_small


class TestAmplitudeTest:
    def test_matching_theory_passes(self) -> None:
        rng = np.random.default_rng(2)
        theoretical_se = 0.01
        distribution = rng.normal(loc=0.5, scale=theoretical_se, size=999)
        result = amplitude_test(distribution, theoretical_se, ratio_min=1 / 3, ratio_max=3.0)
        assert result.within_expected_amplitude
        assert 0.5 <= result.ratio <= 1.5

    def test_much_wider_than_theory_fails(self) -> None:
        rng = np.random.default_rng(3)
        theoretical_se = 0.01
        distribution = rng.normal(loc=0.5, scale=theoretical_se * 10, size=999)
        result = amplitude_test(distribution, theoretical_se, ratio_min=1 / 3, ratio_max=3.0)
        assert not result.within_expected_amplitude


class TestDetectDuplicatePermutations:
    def test_no_duplicates_returns_empty(self) -> None:
        assert detect_duplicate_permutations(["a", "b", "c"]) == []

    def test_detects_a_repeated_fingerprint(self) -> None:
        assert detect_duplicate_permutations(["a", "b", "a", "c"]) == [2]

    def test_detects_multiple_repeats(self) -> None:
        assert detect_duplicate_permutations(["a", "a", "a"]) == [1, 2]
