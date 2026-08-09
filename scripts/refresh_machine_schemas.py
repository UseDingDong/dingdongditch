"""Regenerate package-distributed machine-contract JSON Schema resources.

Run from a repository checkout after changing ``dingdongditch.contract_schema``:

    python scripts/refresh_machine_schemas.py

The committed resources are verified against this same generator in tests.
"""

from __future__ import annotations

import json
from pathlib import Path

from dingdongditch.contract_schema import schema, schema_names


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIRECTORY = ROOT / "dingdongditch" / "schemas"


def main() -> None:
    SCHEMA_DIRECTORY.mkdir(exist_ok=True)
    for name in schema_names():
        target = SCHEMA_DIRECTORY / f"{name}.schema.json"
        target.write_text(
            json.dumps(schema(name), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(target.relative_to(ROOT))


if __name__ == "__main__":
    main()
