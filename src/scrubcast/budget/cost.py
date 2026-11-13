"""Ensemble cost formula verified against the recorded response headers."""

_VARIABLES_PER_UNIT = 10
_DAYS_PER_UNIT = 14


def request_cost(n_vars: int, members: int, days: int) -> float:
    """Estimate units using total members and combined past and forecast days."""
    if min(n_vars, members, days) < 1:
        message = "Variable count, member count and days must be positive"
        raise ValueError(message)
    # Dividing last avoids accumulated rounding in the measured production shape.
    return n_vars * members * max(_DAYS_PER_UNIT, days) / (_VARIABLES_PER_UNIT * _DAYS_PER_UNIT)
