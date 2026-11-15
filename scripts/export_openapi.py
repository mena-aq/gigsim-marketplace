"""Export the API contract without connecting to external services."""

import json
from pathlib import Path

from apps.api.main import app

path = Path(__file__).resolve().parents[1] / "apps/web/openapi.json"
path.write_text(json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n")
