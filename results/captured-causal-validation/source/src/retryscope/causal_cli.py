"""Join client and wire witness JSONL into an audit-ready causal trace."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from .causal import join_causal_trace
from .cli import strict_load


def _load_events(path: Path) -> list[dict[str, Any]]:
    if path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("event input exceeds 16 MiB")
    if path.suffix == ".jsonl":
        rows = []
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"line {number} is not an object")
            rows.append(value)
        return rows
    value = strict_load(path)
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        raise ValueError("event input must be an array of objects or JSONL objects")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client-events", type=Path, required=True)
    parser.add_argument("--wire-events", type=Path, required=True)
    parser.add_argument("--operation-id", required=True)
    parser.add_argument("--stream-complete", action="store_true",
                        help="trusted declaration that both input streams are closed for this operation; otherwise treat them as prefixes")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        trace = join_causal_trace(
            _load_events(args.client_events),
            _load_events(args.wire_events),
            operation_id=args.operation_id,
            stream_complete=args.stream_complete,
        )
        text = json.dumps(trace, indent=2, sort_keys=True, allow_nan=False) + "\n"
        if args.output:
            args.output.write_text(text, encoding="utf-8")
        else:
            sys.stdout.write(text)
        return 0 if trace["causal_join_complete"] else 2
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"Invalid causal witness input: {exc}\n")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
