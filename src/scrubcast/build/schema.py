"""Export JSON Schema and a shared definition graph for TypeScript declarations."""

import argparse
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic.json_schema import models_json_schema

from scrubcast.build.contracts import Hindcast, Latest, Past
from scrubcast.models.assessment import LaunchAssessment
from scrubcast.models.rules import RuleSet

if TYPE_CHECKING:
    from pydantic import BaseModel


def write_schemas(directory: Path) -> None:
    """Emit serialization contracts with shared models compiled only once."""
    models: dict[str, type[BaseModel]] = {
        "latest": Latest,
        "past": Past,
        "launch": LaunchAssessment,
        "rule_set": RuleSet,
        "hindcast": Hindcast,
    }
    directory.mkdir(parents=True, exist_ok=True)
    for name, model in models.items():
        schema = model.model_json_schema(mode="serialization", by_alias=False)
        (directory / f"{name}.schema.json").write_text(
            json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    references, definitions = models_json_schema(
        [(model, "serialization") for model in models.values()],
        title="PublicData",
        by_alias=False,
    )
    definitions["anyOf"] = list(references.values())
    sys.stdout.write(json.dumps(definitions, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export public data schemas")
    parser.add_argument("--output", type=Path, default=Path("schemas"))
    write_schemas(parser.parse_args().output)
