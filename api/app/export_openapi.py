"""Write the OpenAPI specification to docs/openapi.json.

Usage (from the api/ directory):
    python -m app.export_openapi
"""

import json
from pathlib import Path

from app.config import REPO_ROOT
from app.main import create_app

OPENAPI_PATH = REPO_ROOT / "docs" / "openapi.json"


def render_openapi() -> str:
    return json.dumps(create_app().openapi(), indent=2, ensure_ascii=False) + "\n"


def main() -> None:
    Path(OPENAPI_PATH).write_text(render_openapi(), encoding="utf-8")
    print(f"OpenAPI specification written to {OPENAPI_PATH}")


if __name__ == "__main__":
    main()
