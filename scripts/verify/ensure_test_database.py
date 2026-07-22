from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings


def main() -> int:
    url = get_settings().database.url
    database = url.rsplit("/", 1)[-1].split("?", 1)[0]
    if not database.endswith("_test"):
        print(f"ERROR: PostgreSQL integration requires *_test database, got: {database}", file=sys.stderr)
        return 1
    print(f"OK test-database database={database}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

