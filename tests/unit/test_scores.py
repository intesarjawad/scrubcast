import json
from pathlib import Path

import numpy as np
import pytest

from scrubcast.audit.scores import (
    auc,
    bootstrap_interval,
    brier_score,
    brier_skill_score,
    crps_ensemble,
    rank_histogram,
    spearman,
)

GOLDEN = Path(__file__).parents[1] / "golden" / "scores_crosscheck.json"
TOLERANCE = 1e-9


def test_spearman_of_one_swap_is_one_half() -> None:
    # Ranks equal values; d = (0, -1, 1), sum d^2 = 2, so 1 - 6 * 2 / (3 * (9 - 1)) = 0.5.
    assert spearman([1, 2, 3], [1, 3, 2]) == pytest.approx(0.5, abs=TOLERANCE)


def test_spearman_uses_average_ranks_for_ties() -> None:
    # x ranks 1, 2.5, 2.5, 4 and y ranks 1, 2, 3, 4, both with mean 2.5.
    # Centered x: -1.5, 0, 0, 1.5 and y: -1.5, -0.5, 0.5, 1.5.
    # Sum of products 4.5, sum of squares 4.5 and 5, so r = 4.5 / sqrt(22.5) = 3 / sqrt(10).
    assert spearman([1, 2, 2, 3], [1, 2, 3, 4]) == pytest.approx(3 / 10**0.5, abs=TOLERANCE)


def test_spearman_is_one_for_any_increasing_relation() -> None:
    assert spearman([1, 2, 3, 4], [1, 10, 100, 1000]) == pytest.approx(1.0, abs=TOLERANCE)


def test_auc_of_separated_groups() -> None:
    assert auc([0.1, 0.2, 0.8, 0.9], [0, 0, 1, 1]) == pytest.approx(1.0, abs=TOLERANCE)
    assert auc([0.1, 0.2, 0.8, 0.9], [1, 1, 0, 0]) == pytest.approx(0.0, abs=TOLERANCE)


def test_auc_counts_ties_as_half() -> None:
    # Events score 0.5 and 0.8, non-events 0.2 and 0.5. Four pairs:
    # 0.5 > 0.2 is 1, 0.5 = 0.5 is 0.5, 0.8 > 0.2 is 1, 0.8 > 0.5 is 1. 3.5 / 4 = 0.875.
    assert auc([0.2, 0.5, 0.5, 0.8], [0, 0, 1, 1]) == pytest.approx(0.875, abs=TOLERANCE)


def test_brier_of_a_perfect_forecast_is_zero() -> None:
    assert brier_score([1.0, 0.0, 1.0], [1, 0, 1]) == 0.0


def test_brier_score_of_a_mixed_forecast() -> None:
    # (0.9 - 1)^2 = 0.01, (0.2 - 0)^2 = 0.04, (0.6 - 0)^2 = 0.36; mean = 0.41 / 3.
    assert brier_score([0.9, 0.2, 0.6], [1, 0, 0]) == pytest.approx(0.41 / 3, abs=TOLERANCE)


def test_brier_skill_against_a_constant_reference() -> None:
    # A constant 0.5 scores 0.25 on every case. Skill = 1 - (0.41 / 3) / 0.25 = 0.45333...
    skill = brier_skill_score([0.9, 0.2, 0.6], [1, 0, 0], reference_probability=0.5)
    assert skill == pytest.approx(1 - 0.41 / 0.75, abs=TOLERANCE)


def test_crps_of_one_member_is_absolute_error() -> None:
    assert crps_ensemble([3.0], 5.0) == pytest.approx(2.0, abs=TOLERANCE)


def test_crps_of_three_members() -> None:
    # Members 1, 2, 4 and observation 3: mean |x - y| = (2 + 1 + 1) / 3 = 4/3.
    # Pair distances 1, 3, 2 sum to 6, so 12 over ordered pairs; 12 / (2 * 3 * 2) = 1.
    assert crps_ensemble([1.0, 2.0, 4.0], 3.0) == pytest.approx(4 / 3 - 1, abs=TOLERANCE)


def test_rank_histogram_splits_ties_across_ranks() -> None:
    members = [[1, 2, 3]] * 4
    # Observation 0 is below every member: bin 0. Observation 2.5 has two members below: bin 2.
    # Observation 2 equals one member with one below: half to bin 1 and half to bin 2.
    # Observation 5 is above all: bin 3. Totals 1, 0.5, 1.5, 1 over 4 cases.
    histogram = rank_histogram(members, [0, 2.5, 2, 5])
    np.testing.assert_allclose(histogram, [0.25, 0.125, 0.375, 0.25], atol=TOLERANCE)


def test_bootstrap_is_reproducible_and_brackets_the_sample_statistic() -> None:
    values = np.arange(1.0, 21.0)
    first = bootstrap_interval(np.mean, values, np.random.default_rng(7))
    second = bootstrap_interval(np.mean, values, np.random.default_rng(7))
    assert first == second
    # The sample mean of 1..20 is 10.5.
    assert first[0] < 10.5 < first[1]


def test_bootstrap_of_constant_values_collapses_to_that_value() -> None:
    interval = bootstrap_interval(np.mean, np.full(5, 3.0), np.random.default_rng(1))
    assert interval == (3.0, 3.0)


def test_bootstrap_keeps_pairs_together() -> None:
    pairs = np.column_stack([np.arange(1.0, 9.0), np.arange(1.0, 9.0) ** 3])
    interval = bootstrap_interval(
        lambda sample: spearman(sample[:, 0], sample[:, 1]),
        pairs,
        np.random.default_rng(3),
        resamples=50,
    )
    assert interval[1] == pytest.approx(1.0, abs=TOLERANCE)


@pytest.mark.parametrize(
    "call",
    [
        lambda: spearman([], []),
        lambda: spearman([1.0], [1.0]),
        lambda: spearman([1.0, 1.0], [1.0, 2.0]),
        lambda: spearman([1.0, 2.0], [1.0]),
        lambda: spearman([1.0, np.nan], [1.0, 2.0]),
        lambda: auc([0.1, 0.9], [1, 1]),
        lambda: auc([0.1, 0.9], [0, 0]),
        lambda: auc([0.1, 0.9], [0, 2]),
        lambda: auc([], []),
        lambda: brier_score([1.2], [1]),
        lambda: brier_score([np.nan], [1]),
        lambda: brier_skill_score([0.5, 0.5], [1, 1], reference_probability=1.0),
        lambda: brier_skill_score([0.5], [1], reference_probability=1.5),
        lambda: crps_ensemble([], 1.0),
        lambda: crps_ensemble([1.0, np.nan], 1.0),
        lambda: crps_ensemble([1.0, 2.0], np.nan),
        lambda: rank_histogram([[1.0, 2.0]], [1.0, 2.0]),
        lambda: rank_histogram([[1.0, np.nan]], [1.0]),
        lambda: rank_histogram([1.0, 2.0], [1.0]),
        lambda: bootstrap_interval(np.mean, [], np.random.default_rng(0)),
        lambda: bootstrap_interval(np.mean, [1.0], np.random.default_rng(0), resamples=0),
        lambda: bootstrap_interval(np.mean, [1.0], np.random.default_rng(0), confidence=1.0),
    ],
)
def test_unusable_input_is_rejected(call: object) -> None:
    assert callable(call)
    with pytest.raises(ValueError, match=r"\w"):
        call()


def test_crosscheck_matches_independent_reference() -> None:
    golden = json.loads(GOLDEN.read_text())
    given = golden["inputs"]
    expected = golden["expected"]
    members = np.array(given["members"])
    observations = np.array(given["observations"])

    assert spearman(given["x"], given["y"]) == pytest.approx(expected["spearman"], abs=TOLERANCE)
    assert auc(given["probabilities"], given["events"]) == pytest.approx(
        expected["auc"], abs=TOLERANCE
    )
    assert brier_score(given["probabilities"], given["events"]) == pytest.approx(
        expected["brier_score"], abs=TOLERANCE
    )
    assert brier_skill_score(
        given["probabilities"], given["events"], given["reference_probability"]
    ) == pytest.approx(expected["brier_skill_score"], abs=TOLERANCE)
    crps = [crps_ensemble(row, obs) for row, obs in zip(members, observations, strict=True)]
    np.testing.assert_allclose(crps, expected["crps"], atol=TOLERANCE, rtol=0)
    np.testing.assert_allclose(
        rank_histogram(members, observations), expected["rank_histogram"], atol=TOLERANCE, rtol=0
    )
