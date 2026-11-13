"""Verification statistics for forecasts compared with what happened.

Every function is pure: no I/O, no clock, no global random state. Input that cannot
give a meaningful statistic (empty, non-finite, mismatched lengths, a single class,
a constant series) raises ValueError rather than returning NaN.
"""

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from collections.abc import Callable

    from numpy.typing import ArrayLike, NDArray


def _finite_1d(name: str, values: ArrayLike, *, minimum: int = 1) -> NDArray[np.float64]:
    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 1:
        message = f"{name} must be one-dimensional, got {array.ndim} dimensions"
        raise ValueError(message)
    if array.size < minimum:
        message = f"{name} needs at least {minimum} value(s), got {array.size}"
        raise ValueError(message)
    if not np.isfinite(array).all():
        message = f"{name} contains NaN or infinite values; drop them before scoring"
        raise ValueError(message)
    return array


def _paired(
    first_name: str, first: ArrayLike, second_name: str, second: ArrayLike, *, minimum: int = 1
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    a = _finite_1d(first_name, first, minimum=minimum)
    b = _finite_1d(second_name, second, minimum=minimum)
    if a.size != b.size:
        message = (
            f"{first_name} and {second_name} must have equal length, got {a.size} and {b.size}"
        )
        raise ValueError(message)
    return a, b


def _average_ranks(values: NDArray[np.float64]) -> NDArray[np.float64]:
    """Rank from 1; tied values share the mean of the ranks they span."""
    _, inverse, counts = np.unique(values, return_inverse=True, return_counts=True)
    upper = np.cumsum(counts)
    lower = upper - counts + 1
    return ((lower + upper) / 2.0)[inverse]


def spearman(x: ArrayLike, y: ArrayLike) -> float:
    """Spearman rank correlation: Pearson correlation of average ranks.

    Raises ValueError for fewer than two pairs or when either series is constant,
    because the correlation is undefined there.
    """
    a, b = _paired("x", x, "y", y, minimum=2)
    ranks_a = _average_ranks(a) - (a.size + 1) / 2.0
    ranks_b = _average_ranks(b) - (b.size + 1) / 2.0
    denominator = float(np.sqrt(np.sum(ranks_a**2) * np.sum(ranks_b**2)))
    if denominator == 0.0:
        message = "Spearman correlation is undefined when x or y is constant"
        raise ValueError(message)
    return float(np.sum(ranks_a * ranks_b) / denominator)


def _binary(name: str, values: ArrayLike) -> NDArray[np.bool_]:
    array = _finite_1d(name, values)
    if not np.isin(array, (0.0, 1.0)).all():
        message = f"{name} must contain only 0 and 1"
        raise ValueError(message)
    return array == 1.0


def auc(scores: ArrayLike, events: ArrayLike) -> float:
    """Area under the ROC curve as the Mann-Whitney statistic with tie correction.

    The result is the probability that a random event has a higher score than a random
    non-event, counting a tie as one half. Raises ValueError unless both classes occur.
    """
    values, labels = _paired("scores", scores, "events", events)
    positive = _binary("events", labels)
    event_count = int(positive.sum())
    non_event_count = positive.size - event_count
    if event_count == 0 or non_event_count == 0:
        message = "AUC needs at least one event and one non-event"
        raise ValueError(message)
    rank_sum = float(_average_ranks(values)[positive].sum())
    return (rank_sum - event_count * (event_count + 1) / 2.0) / (event_count * non_event_count)


def _probabilities(
    probabilities: ArrayLike, events: ArrayLike
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    p, outcomes = _paired("probabilities", probabilities, "events", events)
    if ((p < 0.0) | (p > 1.0)).any():
        message = "probabilities must lie in [0, 1]"
        raise ValueError(message)
    return p, _binary("events", outcomes).astype(np.float64)


def brier_score(probabilities: ArrayLike, events: ArrayLike) -> float:
    """Mean squared difference between forecast probability and the 0/1 outcome."""
    p, outcomes = _probabilities(probabilities, events)
    return float(np.mean((p - outcomes) ** 2))


def brier_skill_score(
    probabilities: ArrayLike, events: ArrayLike, reference_probability: float
) -> float:
    """One minus the ratio of the Brier score to that of a constant reference forecast.

    Positive values beat the reference. Raises ValueError when the reference scores a
    perfect zero, since the ratio is then undefined.
    """
    p, outcomes = _probabilities(probabilities, events)
    if not 0.0 <= reference_probability <= 1.0:
        message = "reference_probability must lie in [0, 1]"
        raise ValueError(message)
    reference = float(np.mean((reference_probability - outcomes) ** 2))
    if reference == 0.0:
        message = "Brier skill is undefined when the reference forecast is perfect"
        raise ValueError(message)
    return 1.0 - float(np.mean((p - outcomes) ** 2)) / reference


def crps_ensemble(members: ArrayLike, observation: float) -> float:
    """Fair ensemble CRPS: mean|x_i - y| - sum_ij|x_i - x_j| / (2 m (m - 1)).

    The correction removes the bias a finite ensemble puts on the score. A single
    member has no spread to correct, so its score is the absolute error.
    """
    x = _finite_1d("members", members)
    if not np.isfinite(observation):
        message = "observation must be finite"
        raise ValueError(message)
    size = x.size
    error = float(np.mean(np.abs(x - observation)))
    if size == 1:
        return error
    spread = float(np.sum(np.abs(x[:, None] - x[None, :])))
    return error - spread / (2.0 * size * (size - 1))


def rank_histogram(members: ArrayLike, observations: ArrayLike) -> NDArray[np.float64]:
    """Relative frequency of the observation's rank among the sorted members.

    Rows of `members` are cases and columns are members, so the result has
    members + 1 bins. An observation equal to several members spreads its weight
    equally over the ranks it could take, which keeps a calibrated ensemble flat.
    """
    ensemble = np.asarray(members, dtype=np.float64)
    if ensemble.ndim != 2 or ensemble.shape[0] == 0 or ensemble.shape[1] == 0:
        message = "members must be a non-empty (cases, members) array"
        raise ValueError(message)
    if not np.isfinite(ensemble).all():
        message = "members contains NaN or infinite values; drop them before scoring"
        raise ValueError(message)
    observed = _finite_1d("observations", observations)
    if observed.size != ensemble.shape[0]:
        message = (
            f"observations must have one value per case, got {observed.size} for "
            f"{ensemble.shape[0]} cases"
        )
        raise ValueError(message)
    below: NDArray[np.int64] = (ensemble < observed[:, None]).sum(axis=1)
    equal: NDArray[np.int64] = (ensemble == observed[:, None]).sum(axis=1)
    bins = np.arange(ensemble.shape[1] + 1, dtype=np.int64)
    covered = (bins >= below[:, None]) & (bins <= (below + equal)[:, None])
    weights = covered / (equal + 1.0)[:, None]
    return np.asarray(weights.sum(axis=0) / ensemble.shape[0], dtype=np.float64)


def bootstrap_interval(
    statistic: Callable[[NDArray[np.float64]], float],
    values: ArrayLike,
    rng: np.random.Generator,
    *,
    resamples: int = 2000,
    confidence: float = 0.95,
) -> tuple[float, float]:
    """Percentile bootstrap interval, resampling whole rows of `values` with replacement.

    For paired statistics pass a (cases, columns) array so each pair stays together.
    The generator is injected, so a seeded generator reproduces the interval.
    """
    data = np.asarray(values, dtype=np.float64)
    if data.ndim == 0 or data.shape[0] == 0:
        message = "values needs at least one row"
        raise ValueError(message)
    if resamples < 1:
        message = "resamples must be at least 1"
        raise ValueError(message)
    if not 0.0 < confidence < 1.0:
        message = "confidence must lie strictly between 0 and 1"
        raise ValueError(message)
    rows = rng.integers(0, data.shape[0], size=(resamples, data.shape[0]))
    estimates = np.array([statistic(data[row]) for row in rows], dtype=np.float64)
    tail = (1.0 - confidence) / 2.0
    lower, upper = np.quantile(estimates, [tail, 1.0 - tail])
    return float(lower), float(upper)
