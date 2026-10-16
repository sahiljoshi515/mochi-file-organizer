"""Time every verifier call NanoAgent makes while it runs organize-folder on a worst-case folder at the
limits (tests/perf/worst.py): each call is NanoAgent's own verifier helper, a fresh sandboxed process
that runs the function twice under one 60 s limit. Run with NanoAgent's Python:

    <nanoagent venv>/bin/python tests/perf/verifier_times.py . dense-office-1000 [--sandbox seatbelt]
        [--harness ~/mochi-dev/harness] [--out times.json]

Prints (and writes) JSON: every verifier call with its seconds, the slowest, and the verdict. The run
is the scripted agent of tests/cases/agent.py: survey, apply in calls of 30, submit.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

from nanoagent.plugin import load_manifest, sandbox
from nanoagent.plugin import verifier as nanoagent_verifier
from nanoagent.plugin.python import plugin_python
from nanoagent.plugin.tasks import run_task

HERE = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("plugin")
    parser.add_argument("folder", help="a folder of tests/perf/worst.py FOLDERS")
    parser.add_argument("--sandbox", default="seatbelt", choices=list(sandbox.SANDBOXES))
    parser.add_argument("--harness", default=str(Path.home() / "mochi-dev" / "harness"))
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    sys.path[:0] = [args.harness, str(HERE.parent)]
    import scripted_task  # the lab harness: the scripted agent and RUSH Lab's staging

    from perf import worst

    manifest = load_manifest(args.plugin)
    sandbox.configure(args.sandbox, None if args.sandbox == "none" else plugin_python(sys.executable))
    calls: list[dict] = []
    original = nanoagent_verifier._call

    def timed(root, name, arguments, classes, workspace):
        started = time.perf_counter()
        try:
            return original(root, name, arguments, classes, workspace)
        finally:
            calls.append({"function": name, "of": arguments[0], "seconds": round(time.perf_counter() - started, 2)})

    nanoagent_verifier._call = timed
    workspace = Path(tempfile.mkdtemp(prefix="file-organizer-perf-"))
    try:
        files = worst.FOLDERS[args.folder]()
        for path, data in files.items():
            target = workspace / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        agent_code = (HERE.parent / "cases" / "agent.py").read_text(encoding="utf-8")
        steps = [
            {"tool": "survey", "arguments": {"folder": "Downloads"}, "save_as": "survey"},
            {"python": agent_code + "\ndecide(outputs, 'Downloads', None)\n"},
            {"tool": "apply", "arguments": "$ref:batch0", "save_as": "last"},
            {"tool": "apply", "arguments": "$ref:batch1", "save_as": "last"},
            {"tool": "submit", "arguments": "$ref:last.summary"},
        ]
        agent = scripted_task.ScriptedAgent(steps, workspace, "Done.")
        started = time.perf_counter()
        outcome = asyncio.run(
            run_task(
                manifest,
                manifest.task("organize-folder"),
                {"folder": "Downloads"},
                workspace,
                make_agent=lambda _prompt: agent,
                make_decider=None,
                timeout=170.0,
                on_event=lambda _kind, _data: None,
                stage=scripted_task.web_stage(workspace, False),
            )
        )
        report = {
            "folder": args.folder,
            "files": sum(path.startswith("Downloads/") for path in files),
            "bytes": sum(len(data) for path, data in files.items() if path.startswith("Downloads/")),
            "agent_folder_bytes": sum(map(len, files.values())),
            "sandbox": args.sandbox,
            "run_seconds": round(time.perf_counter() - started, 1),
            "calls": calls,
            "slowest": max(calls, key=lambda call: call["seconds"]),
            "valid": outcome.verdict.valid,
            "score": outcome.verdict.score,
            "message": outcome.verdict.message,
        }
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
    text = json.dumps(report, indent=1)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
