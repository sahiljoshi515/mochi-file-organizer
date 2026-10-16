"""Writes scripted cases on folders built from the real-file corpus into an output folder outside the
repo (the corpus is never committed), for ~/mochi-dev/harness/run_cases.py:

    uv run python tests/corpus/real_cases.py OUT_DIR [COUNT]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parents[1]), str(HERE.parents[1] / "src"), str(HERE.parent), str(HERE.parent / "cases")]

import build_cases
from messy import messy, write_tar

from corpus.real import available, pools


def main() -> int:
    out = Path(sys.argv[1]).expanduser().resolve()
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 6
    if not available():
        raise SystemExit("fetch the corpus first: uv run python tests/corpus/fetch.py")
    (out / "folders").mkdir(parents=True, exist_ok=True)
    real = pools()
    written = 0
    for seed in range(count):
        profile = ["small", "medium", "multirun"][seed % 3]
        folder = "Downloads" if seed % 4 else "My Stuff"
        files = messy(1000 + seed, profile, folder, real=real)
        write_tar(files, out / "folders" / f"real-{seed}.tar")
        agent_folder = f"folders/real-{seed}.tar"
        gold = build_cases.case(f"real files, messy({1000 + seed}, {profile})", folder, agent_folder, build_cases.steps(folder), build_cases.GOLD)
        (out / f"real_gold_{seed}.json").write_text(json.dumps(gold, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        written += 1
        if seed < 2:
            stray = f"({build_cases.root_code(folder)} / 'stray.txt').write_text('stray')\n"
            bad = build_cases.case("real files, a stray file left", folder, agent_folder, build_cases.steps(folder, after=stray), build_cases.wrong("should not be"))
            (out / f"real_wrong_stray_{seed}.json").write_text(json.dumps(bad, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
            written += 1
    print(f"wrote {written} cases to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
