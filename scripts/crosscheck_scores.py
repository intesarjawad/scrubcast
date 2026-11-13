"""Write reference values for audit.scores, computed with the independent scores package.

Run through `make crosscheck`, which supplies scores and xarray for this process only.
Neither is a dependency of scrubcast.
"""

import json
from pathlib import Path

import numpy as np
import xarray as xr
from scores.continuous.correlation import spearmanr
from scores.probability import brier_score, crps_for_ensemble, rank_histogram, roc_auc

SEED = 20261105
CASES = 400
MEMBERS = 7
DECIMALS = 1
GOLDEN = Path(__file__).parents[1] / "tests" / "golden" / "scores_crosscheck.json"


def _array(values: np.ndarray, *dims: str) -> xr.DataArray:
    return xr.DataArray(values, dims=dims)


def main() -> None:
    """Generate the seeded data set and write the reference values."""
    rng = np.random.default_rng(SEED)
    truth = rng.normal(size=CASES)
    x = np.round(truth + rng.normal(scale=0.8, size=CASES), DECIMALS)
    y = np.round(truth + rng.normal(scale=0.8, size=CASES), DECIMALS)
    events = (truth + rng.normal(scale=0.5, size=CASES) > 0.3).astype(float)
    probabilities = np.round(np.clip(0.5 + 0.35 * x, 0.0, 1.0), DECIMALS)
    reference_probability = float(events.mean())
    members = np.round(truth[:, None] + rng.normal(scale=1.0, size=(CASES, MEMBERS)), DECIMALS)
    observations = np.round(truth + rng.normal(scale=0.3, size=CASES), DECIMALS)

    reference_score = float(
        brier_score(_array(np.full(CASES, reference_probability), "case"), _array(events, "case"))
    )
    forecast_score = float(brier_score(_array(probabilities, "case"), _array(events, "case")))
    crps = crps_for_ensemble(
        _array(members, "case", "member"),
        _array(observations, "case"),
        "member",
        method="fair",
        preserve_dims=["case"],
    )
    histogram = rank_histogram(
        _array(members, "case", "member"), _array(observations, "case"), "member"
    )

    golden = {
        "seed": SEED,
        "inputs": {
            "x": x.tolist(),
            "y": y.tolist(),
            "events": events.tolist(),
            "probabilities": probabilities.tolist(),
            "reference_probability": reference_probability,
            "members": members.tolist(),
            "observations": observations.tolist(),
        },
        "expected": {
            "spearman": float(spearmanr(_array(x, "case"), _array(y, "case"))),
            "auc": float(roc_auc(_array(probabilities, "case"), _array(events, "case"))),
            "brier_score": forecast_score,
            "brier_skill_score": 1.0 - forecast_score / reference_score,
            "crps": crps.values.tolist(),
            "rank_histogram": histogram.values.tolist(),
        },
    }
    GOLDEN.write_text(json.dumps(golden, indent=1) + "\n")


if __name__ == "__main__":
    main()
