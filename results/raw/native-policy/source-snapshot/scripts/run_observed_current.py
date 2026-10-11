#!/usr/bin/env python3
"""Source-bound collector entry point; historical behavior remains the default.

Current: --run-mode current --out NEW_DIRECTORY [--seeds 301,302,...].
Analyze with --analysis-mode current --raw NEW_DIRECTORY
--source-snapshot NEW_DIRECTORY/source-snapshot --out NEW_ANALYSIS_DIRECTORY.
This captures owned sources, not SDK dependencies or historical worker recovery.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import time
from typing import Any, Callable, Mapping

ROOT = Path(__file__).resolve().parents[1]
CURRENT_SOURCE_FILES = (
    "study/cases.json", "scripts/run_observed_current.py",
    "src/retryscope/__init__.py", "src/retryscope/observed_worker.py",
    "src/retryscope/worker.py", "src/retryscope/checker.py",
    "src/retryscope/observation.py", "src/retryscope/audit.py",
    "src/retryscope/responder.py",
)


def match_source_provenance(freeze: Mapping[str, Any], root: Path,
                            snapshot: Path) -> dict[str, Any]:
    """Require one exact nine-file source map, not an either-validator fallback."""
    if freeze.get("analysis_mode") != "current":
        raise SystemExit("freeze analysis mode is missing or conflicts with selected mode")
    files = {}
    for relative in CURRENT_SOURCE_FILES:
        live, captured = root / relative, snapshot / relative
        if not live.is_file() or not captured.is_file():
            raise SystemExit(f"missing current source or captured snapshot: {relative}")
        digest = hashlib.sha256(live.read_bytes()).hexdigest()
        if hashlib.sha256(captured.read_bytes()).hexdigest() != digest:
            raise SystemExit(f"captured source does not match current implementation: {relative}")
        files[relative] = digest
    if freeze.get("files") != files:
        raise SystemExit("current freeze source provenance does not match captured implementation")
    return {"analysis_mode": "current", "files": files}


def prepare_current(out: Path, seeds: str, ids: str) -> dict[str, Any]:
    """Capture before any collection; never reuse a directory or retrofit rows."""
    seed_values = [int(value) for value in seeds.split(",")]
    if not seed_values or len(set(seed_values)) != len(seed_values):
        raise SystemExit("current seeds must be nonempty and unique")
    sources = {relative: (ROOT / relative).read_bytes() for relative in CURRENT_SOURCE_FILES}
    configs = json.loads(sources["study/cases.json"])
    selected = set(ids.split(",")) if ids else set()
    if selected - {config["id"] for config in configs}:
        raise SystemExit("unknown current case id")
    out.mkdir(parents=True, exist_ok=False)
    snapshot = out / "source-snapshot"
    for relative, content in sources.items():
        target = snapshot / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as output:
            output.write(content)
    freeze = {
        "utc": datetime.datetime.now(datetime.UTC).isoformat(),
        "phase": "observed-current", "analysis_mode": "current",
        "seeds": seeds, "ids": ids,
        "files": {relative: hashlib.sha256(content).hexdigest()
                  for relative, content in sources.items()},
    }
    match_source_provenance(freeze, ROOT, snapshot)
    with (out / "freeze.json").open("x", encoding="utf-8") as output:
        output.write(json.dumps(freeze, indent=2) + "\n")
    return freeze


def collect_policy(out: Path, flag: str, seeds: str, ids: str,
                   *, collector: Callable[..., dict[str, Any]] | None = None) -> int:
    """Write newly returned records only. Callback injection is for offline tests."""
    if flag not in {"false", "true"}:
        raise SystemExit("unsupported current policy flag")
    snapshot = out / "source-snapshot"
    freeze = json.loads((out / "freeze.json").read_text(encoding="utf-8"))
    if (freeze.get("phase") != "observed-current" or freeze.get("seeds") != seeds
            or freeze.get("ids") != ids):
        raise SystemExit("current policy controls conflict with captured batch")
    provenance = match_source_provenance(freeze, ROOT, snapshot)
    configs = json.loads((snapshot / "study/cases.json").read_text(encoding="utf-8"))
    selected = set(ids.split(",")) if ids else set()
    configs = [config for config in configs if config.get("flag", "true") == flag
               and (not selected or config["id"] in selected)]
    if collector is None:
        if ROOT != snapshot.resolve():
            raise SystemExit("current collection must execute from the captured source snapshot")
        sys.path.insert(0, str(snapshot / "src"))
        os.environ["AWS_NEW_RETRIES_2026"] = flag
        from retryscope.observed_worker import run
        for name in ("retryscope", "retryscope.observed_worker", "retryscope.worker",
                     "retryscope.checker", "retryscope.observation", "retryscope.audit",
                     "retryscope.responder"):
            relative = "src/" + name.replace(".", "/") + ("/__init__.py" if name == "retryscope" else ".py")
            if Path(sys.modules[name].__file__).resolve() != (snapshot / relative).resolve():
                raise SystemExit(f"current collector imported from another source: {name}")
        collector = run
    count = 0
    with (out / f"{flag}.jsonl").open("x", encoding="utf-8") as output:
        for seed in map(int, seeds.split(",")):
            order = list(configs)
            random.Random(seed + 7919).shuffle(order)
            for config in order:
                match_source_provenance(freeze, ROOT, snapshot)
                row = collector(json.loads(json.dumps(config)), seed, freeze["phase"])
                match_source_provenance(freeze, ROOT, snapshot)
                if "analysis_mode" in row or "source_provenance" in row:
                    raise SystemExit("collector returned premarked or ambiguous record provenance")
                if (row.get("id") != config["id"] or row.get("config") != config
                        or row.get("seed") != seed or row.get("phase") != freeze["phase"]):
                    raise SystemExit("collector record does not match captured batch controls")
                row = dict(row)
                row["analysis_mode"] = "current"
                row["source_provenance"] = provenance
                output.write(json.dumps(row, sort_keys=True) + "\n")
                output.flush()
                count += 1
    return count


def child_environment(out: Path, snapshot: Path) -> dict[str, str]:
    """Do not inherit cloud tokens, profiles, proxy settings or credential homes."""
    allowed = {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LANG", "LC_ALL", "TZ"}
    env = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    env.update({
        "PYTHONPATH": str(snapshot / "src"), "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1", "HOME": str(out), "USERPROFILE": str(out),
        "APPDATA": str(out), "LOCALAPPDATA": str(out), "NO_PROXY": "127.0.0.1",
        "AWS_EC2_METADATA_DISABLED": "true", "AWS_CONFIG_FILE": os.devnull,
        "AWS_SHARED_CREDENTIALS_FILE": os.devnull,
        "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1", "HF_HUB_DISABLE_TELEMETRY": "1",
    })
    return env


def run_current(out: Path, seeds: str, ids: str) -> dict[str, Any]:
    out = out.resolve()
    freeze = prepare_current(out, seeds, ids)
    snapshot = out / "source-snapshot"
    deadline = time.monotonic() + 900  # Finite shared bound for both policy children.
    for flag in ("false", "true"):
        match_source_provenance(freeze, ROOT, snapshot)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise SystemExit("current collection exceeded the 15-minute bound")
        command = [sys.executable, "-B", str(snapshot / "scripts/run_observed_current.py"),
                   "--run-mode", "current", "--out", str(out), "--seeds", seeds,
                   "--ids", ids, "--policy-flag", flag]
        subprocess.run(command, cwd=snapshot, env=child_environment(out, snapshot),
                       check=True, timeout=remaining)
        match_source_provenance(freeze, ROOT, snapshot)
    return freeze


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-mode", choices=["historical", "current"], default="historical")
    parser.add_argument("--out", type=Path, help="current requires a new output directory")
    parser.add_argument("--seeds", default=",".join(map(str, range(301, 313))))
    parser.add_argument("--ids", default="")
    parser.add_argument("--policy-flag", choices=["false", "true"], help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.run_mode == "historical":
        if args.policy_flag:
            parser.error("--policy-flag is only allowed in current mode")
        import run_observed_study
        old_argv = sys.argv
        sys.argv = [str(ROOT / "scripts/run_observed_study.py"), "--seeds", args.seeds,
                    "--ids", args.ids]
        if args.out is not None:
            sys.argv += ["--out", str(args.out)]
        try:
            run_observed_study.main()
        finally:
            sys.argv = old_argv
        return
    if args.out is None:
        parser.error("current mode requires --out NEW_DIRECTORY")
    if args.policy_flag:
        collect_policy(args.out.resolve(), args.policy_flag, args.seeds, args.ids)
    else:
        print(json.dumps(run_current(args.out, args.seeds, args.ids), indent=2))


if __name__ == "__main__":
    main()
