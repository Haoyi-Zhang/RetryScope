#!/usr/bin/env python3
"""Resolve principal frozen-source declarations without changing any evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PRINCIPAL_PHASES = ("observed", "extension", "async-boundary", "sync-enforcement")


def sha256(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def resolve_frozen_sources(root: Path = ROOT) -> dict[str, Any]:
    relocations = json.loads((root / "evidence/FROZEN-SOURCE-MAP.json").read_text(encoding="utf-8"))["relocations"]
    entries: list[dict[str, Any]] = []
    for phase in PRINCIPAL_PHASES:
        freeze_path = f"results/raw/{phase}/freeze.json"
        freeze = json.loads((root / freeze_path).read_text(encoding="utf-8"))
        declarations = freeze.get("files", freeze.get("sources"))
        if not isinstance(declarations, dict) or not declarations:
            raise ValueError(f"missing source declarations: {freeze_path}")
        for frozen_path, expected in declarations.items():
            live_digest = sha256(root / frozen_path)
            entry: dict[str, Any] = {
                "phase": phase, "freeze": freeze_path, "frozen_path": frozen_path,
                "expected_sha256": expected, "current_sha256": live_digest,
                "resolved_path": None,
            }
            if live_digest == expected:
                entry["resolved_path"] = frozen_path
            else:
                for relocation in relocations:
                    if relocation["frozen_path"] == frozen_path and relocation["sha256"] == expected:
                        preserved_path = relocation["preserved_path"]
                        if sha256(root / preserved_path) == expected:
                            entry["resolved_path"] = preserved_path
                            break
            entries.append(entry)
    unresolved = [entry for entry in entries if entry["resolved_path"] is None]
    return {
        "status": "unresolved" if unresolved else "resolved",
        "declared_entries": len(entries), "resolved_entries": len(entries) - len(unresolved),
        "entries": entries, "unresolved": unresolved,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    report = resolve_frozen_sources(args.root)
    print(json.dumps(report, indent=2))
    return 1 if report["unresolved"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
