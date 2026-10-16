import os
import sys
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS))  # builders, messy, oracle
CORPUS = TESTS / "corpus" / "corpus-cache"


def pytest_collection_modifyitems(config, items):
    if CORPUS.is_dir() and any(CORPUS.iterdir()):
        return
    if os.environ.get("FILE_ORGANIZER_CORPUS"):
        return
    skip = pytest.mark.skip(reason="needs the real-file corpus: uv run python tests/corpus/fetch.py")
    for item in items:
        if "corpus" in item.keywords:
            item.add_marker(skip)
