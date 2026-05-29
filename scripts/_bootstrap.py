"""scripts/* 공통: src 경로·.env 로드."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def setup() -> Path:
    if str(SRC) not in sys.path:
        sys.path.insert(0, str(SRC))
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    return ROOT
