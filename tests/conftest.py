import os
import sys
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS))  # builders, messy, oracle
CORPUS = TESTS / "corpus" / "corpus-cache"


def pytest_collection_modifyitems(config, items):
    if not os.environ.get("FILE_ORGANIZER_PERF"):
        slow = pytest.mark.skip(reason="the timing tests at the limits are opt-in: FILE_ORGANIZER_PERF=1 uv run pytest -m perf")
        for item in items:
            if "perf" in item.keywords:
                item.add_marker(slow)
    if (CORPUS.is_dir() and any(CORPUS.iterdir())) or os.environ.get("FILE_ORGANIZER_CORPUS"):
        return
    skip = pytest.mark.skip(reason="needs the real-file corpus: uv run python tests/corpus/fetch.py")
    for item in items:
        if "corpus" in item.keywords:
            item.add_marker(skip)
