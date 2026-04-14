"""Generate JSON Schema files from Pydantic models.

Run this script to regenerate schema artifacts:
    python schemas/generate_schemas.py
"""

from __future__ import annotations

import json
from pathlib import Path

from docos.models.page import Frontmatter
from docos.models.patch import Patch
from docos.models.run import RunManifest

SCHEMAS_DIR = Path(__file__).resolve().parent

MODELS = [
    ("run", RunManifest),
    ("page", Frontmatter),
    ("patch", Patch),
]


def main() -> None:
    SCHEMAS_DIR.mkdir(parents=True, exist_ok=True)
    for name, model in MODELS:
        schema = model.model_json_schema()
        target = SCHEMAS_DIR / f"{name}.schema.json"
        target.write_text(json.dumps(schema, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"  wrote {target}")


if __name__ == "__main__":
    main()
