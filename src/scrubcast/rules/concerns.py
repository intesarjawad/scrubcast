"""Official concern variants mapped to evaluable and omitted weather criteria."""

from typing import TYPE_CHECKING

from scrubcast.rules.loader import load_rules

if TYPE_CHECKING:
    from scrubcast.models.rules import ConcernMatch


def normalise_concern(name: str) -> ConcernMatch:
    """Preserve unmapped official text so audits can report gaps in rule coverage."""
    return load_rules().normalise_concern(name)
