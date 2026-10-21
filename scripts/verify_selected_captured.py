#!/usr/bin/env python3
"""Explicit OFFLINE replay of the adopted native-policy captured generation.

Not native recollection and not execution of today's live native-policy sources.
Only a disposable full artifact copy receives the nine frozen source files;
verify_selected and its live source-equality guard remain unchanged.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

import verify_selected as selected

# Fixed collection queue for this capture format, not a freeze-controlled list
# of arbitrary files to install/import. Keep the collector's guard unchanged.
CAPTURE_FILES = (
    "study/cases.json", "scripts/run_observed_current.py",
    "src/retryscope/__init__.py", "src/retryscope/observed_worker.py",
    "src/retryscope/worker.py", "src/retryscope/checker.py",
    "src/retryscope/observation.py", "src/retryscope/audit.py",
    "src/retryscope/responder.py",
)
ROUTE = "adopted-captured-generation-offline"


@contextmanager
def captured_artifact(root=selected.ROOT, *, temp_parent=None):
    """Validate all nine snapshots before copying or importing captured code.

    Yield (temporary artifact, generation identity). Other files, including all
    results/freezes and verifier/migration helpers, are copied without changes;
    those helpers are not claimed to be attested by the nine-source freeze.
    The original artifact is never written. Cleanup also runs after a failure.
    """
    root = Path(root).resolve()
    raw = selected.inside(root, "results/raw/native-policy")
    freeze_bytes = (raw / "freeze.json").read_bytes()
    freeze = selected.parse(freeze_bytes.decode("utf-8"), "native-policy freeze")
    selected.same(freeze.get("analysis_mode"), "current", "captured collection analysis mode")
    files = freeze.get("files")
    selected.require(isinstance(files, dict), "missing captured source provenance")
    selected.same(sorted(files), sorted(CAPTURE_FILES), "captured source provenance file set")
    snapshot = selected.inside(root, "results/raw/native-policy/source-snapshot")
    sources = {}
    for relative in CAPTURE_FILES:
        path = selected.inside(snapshot, relative)
        selected.require(path.is_file(), f"missing captured snapshot: {relative}")
        content = path.read_bytes()
        selected.same(hashlib.sha256(content).hexdigest(), files[relative],
                      f"captured snapshot digest {relative}")
        sources[relative] = content
    selected.same(sorted(p.relative_to(snapshot).as_posix()
                         for p in snapshot.rglob("*") if p.is_file()),
                  sorted(CAPTURE_FILES), "captured snapshot file set")
    generation = {"collection_utc": freeze["utc"], "phase": freeze["phase"],
                  "collection_analysis_mode": freeze["analysis_mode"],
                  "freeze_sha256": hashlib.sha256(freeze_bytes).hexdigest(),
                  "files": files}
    parent = Path(temp_parent if temp_parent is not None else tempfile.gettempdir()).resolve()
    selected.require(not parent.is_relative_to(root), "temporary copy must be outside input artifact")
    # Keep the prefix short for complete copies at deep Windows stage paths.
    with tempfile.TemporaryDirectory(prefix="rs-", dir=parent) as directory:
        replay = Path(directory).resolve() / "artifact"
        shutil.copytree(root, replay)
        for relative, content in sources.items():
            selected.inside(replay, relative).write_bytes(content)
        yield replay, generation


def verify(root=selected.ROOT, paper_dir=None, *, temp_parent=None):
    with captured_artifact(root, temp_parent=temp_parent) as (replay, generation):
        # No patched guard, fallback validator, row rewrite or summary subset.
        report = selected.verify(replay, paper_dir)
        report["route"] = ROUTE
        report["input_artifact_root"] = Path(root).resolve().as_posix()
        report["captured_generation"] = generation
        report["execution_context"] = {
            "native_policy_sources": "nine exact captured files in disposable full artifact copy",
            "native_recollection": False,
            "today_live_native_policy_execution": False,
            "temporary_copy_removed_on_return": True,
            "other_helpers": "copied from input artifact; not attested by the nine-source freeze",
            "current_label": "fixed collection queue/mode, not today's live implementation",
        }
        report["scope"] = (
            "Captured source generation replay; not native recollection and not today's live "
            "native-policy execution. " + report["scope"])
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=selected.ROOT, help="input artifact, read only")
    parser.add_argument("--paper-dir", type=Path, help="optional existing paper; read count macros only")
    parser.add_argument("--temp-parent", type=Path, help="existing temporary-copy parent outside input artifact")
    args = parser.parse_args(argv)
    try:
        report = verify(args.root, args.paper_dir, temp_parent=args.temp_parent)
    except (Exception, SystemExit) as exc:
        report = {"schema": 1, "status": "hold", "route": ROUTE,
                  "all_history_verified": False, "error": str(exc)}
    print(json.dumps(report, indent=2, allow_nan=False))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
