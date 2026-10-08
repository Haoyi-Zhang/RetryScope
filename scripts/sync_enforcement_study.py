#!/usr/bin/env python3
"""Compare a thread timeout signal with a terminated process boundary."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
import datetime
import hashlib
import json
import multiprocessing as mp
import os
from pathlib import Path
import platform
import random
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from retryscope.audit import AuditIntent, audit
from retryscope.responder import Reply, Responder


def perform(session: Any, url: str, scenario: str, scale: float) -> dict[str, Any]:
    """One complete synchronous application operation."""
    started = time.monotonic()
    attempts = 0
    try:
        attempts += 1
        response = session.get(url + "/data", timeout=(0.5 * scale, 1.0 * scale))
        if scenario == "retry_delay" and response.status_code == 503:
            time.sleep(0.45 * scale)
            attempts += 1
            response = session.get(url + "/data", timeout=(0.5 * scale, 1.0 * scale))
        response.raise_for_status()
        payload = response.content.decode("ascii")
        return {
            "worker_outcome": "success",
            "worker_payload": payload,
            "worker_attempts": attempts,
            "worker_elapsed_s": time.monotonic() - started,
        }
    except Exception as exc:
        return {
            "worker_outcome": "error",
            "worker_exception": type(exc).__name__,
            "worker_error": str(exc)[:200],
            "worker_attempts": attempts,
            "worker_elapsed_s": time.monotonic() - started,
        }


def process_worker(conn: Any, url: str, scenario: str, scale: float) -> None:
    import requests
    session = requests.Session()
    session.trust_env = False
    try:
        conn.send({"kind": "ready", "pid": os.getpid(), "requests": requests.__version__})
        command = conn.recv()
        if command != "go":
            raise RuntimeError("unexpected supervisor command")
        result = perform(session, url, scenario, scale)
        conn.send({"kind": "result", **result})
    except BaseException as exc:
        try:
            conn.send({"kind": "worker_failure", "exception": type(exc).__name__, "error": str(exc)[:200]})
        except BaseException:
            pass
        raise
    finally:
        session.close()
        conn.close()


def replies(scenario: str, scale: float) -> list[Reply]:
    if scenario == "trickle":
        return [Reply(chunk_delay=0.06 * scale)]
    if scenario == "slow_headers":
        return [Reply(header_delay=0.30 * scale)]
    if scenario == "retry_delay":
        return [Reply(status=503), Reply()]
    if scenario == "success":
        return [Reply()]
    raise ValueError(scenario)


def run_thread(case: dict[str, Any], server: Responder) -> dict[str, Any]:
    import requests
    setup_start = time.monotonic()
    session = requests.Session()
    session.trust_env = False
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="retryscope-sync")
    ready = time.monotonic()
    budget = 0.25 * case["scale"]
    record: dict[str, Any] = {"setup_s": ready - setup_start, "budget_s": budget}
    operation_start = time.monotonic()
    future = executor.submit(perform, session, server.url, case["scenario"], case["scale"])
    try:
        result = future.result(timeout=budget)
        record.update(mechanism_outcome="completed", timeout_signalled=False, **result)
    except FutureTimeout:
        record.update(
            mechanism_outcome="timeout",
            timeout_signalled=True,
            timeout_signal_s=time.monotonic() - operation_start,
            cancel_return=future.cancel(),
        )
    finally:
        executor.shutdown(wait=True, cancel_futures=True)
        if future.done() and not future.cancelled():
            try:
                record.setdefault("post_signal_worker", future.result())
            except BaseException as exc:
                record.setdefault("post_signal_worker", {"worker_outcome": "error", "worker_exception": type(exc).__name__})
        session.close()
    record.update(
        cleanup_elapsed_s=time.monotonic() - operation_start,
        cleanup_complete=True,
        worker_alive_after=False,
        operation_start_t=operation_start,
        operation_end_t=time.monotonic(),
    )
    return record


def run_process(case: dict[str, Any], server: Responder) -> dict[str, Any]:
    context = mp.get_context("spawn")
    parent, child = context.Pipe(duplex=True)
    setup_start = time.monotonic()
    process = context.Process(
        target=process_worker,
        args=(child, server.url, case["scenario"], case["scale"]),
        name="retryscope-operation",
    )
    process.start()
    child.close()
    if not parent.poll(10):
        process.kill(); process.join(2)
        raise RuntimeError("worker did not become ready")
    ready_message = parent.recv()
    if ready_message.get("kind") != "ready":
        process.kill(); process.join(2)
        raise RuntimeError(f"unexpected ready message: {ready_message}")
    ready = time.monotonic()
    budget = 0.25 * case["scale"]
    record: dict[str, Any] = {
        "setup_s": ready - setup_start,
        "budget_s": budget,
        "worker_pid": ready_message.get("pid"),
        "worker_requests_version": ready_message.get("requests"),
        "process_start_method": context.get_start_method(),
    }
    operation_start = time.monotonic()
    parent.send("go")
    process.join(timeout=budget)
    terminated = False
    killed = False
    if process.is_alive():
        record.update(
            mechanism_outcome="timeout",
            timeout_signalled=True,
            timeout_signal_s=time.monotonic() - operation_start,
        )
        terminated = True
        process.terminate()
        process.join(timeout=2)
        if process.is_alive():
            killed = True
            process.kill()
            process.join(timeout=2)
    else:
        record.update(mechanism_outcome="completed", timeout_signalled=False)
        if parent.poll(0.2):
            message = parent.recv()
            if message.get("kind") == "result":
                record.update({key: value for key, value in message.items() if key != "kind"})
            else:
                record.update(worker_outcome="error", worker_exception=message.get("exception"), worker_error=message.get("error"))
        else:
            record.update(worker_outcome="error", worker_exception="MissingWorkerResult")
    record.update(
        terminated=terminated,
        killed=killed,
        worker_exitcode=process.exitcode,
        worker_alive_after=process.is_alive(),
        cleanup_elapsed_s=time.monotonic() - operation_start,
        cleanup_complete=not process.is_alive(),
        operation_start_t=operation_start,
        operation_end_t=time.monotonic(),
    )
    parent.close()
    return record


def cases() -> list[dict[str, Any]]:
    return [
        {"id": f"{mode}_{scenario}_{scale}", "mode": mode, "scenario": scenario, "scale": scale}
        for mode in ("thread_future", "process_watchdog")
        for scenario in ("success", "trickle", "slow_headers", "retry_delay")
        for scale in (1.0, 1.5)
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    selected_cases = cases()
    seeds = [700] if args.smoke else list(range(701, 707))
    if args.smoke:
        selected_cases = [case for case in selected_cases if case["scenario"] in ("success", "trickle") and case["scale"] == 1.0]
    sources = [
        Path(__file__),
        ROOT / "study/sync-enforcement-protocol.md",
        ROOT / "src/retryscope/responder.py",
        ROOT / "src/retryscope/audit.py",
    ]
    freeze = {
        "utc": datetime.datetime.now(datetime.UTC).isoformat(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "cases": selected_cases,
        "seeds": seeds,
        "sources": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources},
    }
    (args.out / "freeze.json").write_text(json.dumps(freeze, indent=2) + "\n")
    with (args.out / "records.jsonl").open("x") as output:
        for seed in seeds:
            order = selected_cases[:]
            random.Random(seed).shuffle(order)
            for case in order:
                with Responder(replies(case["scenario"], case["scale"])) as server:
                    if case["mode"] == "thread_future":
                        record = run_thread(case, server)
                    else:
                        record = run_process(case, server)
                    quiesced = server.quiesce(timeout=2)
                    record.update(
                        id=case["id"], case=case, seed=seed,
                        server_quiesced=quiesced,
                        arrival_stream_complete=quiesced and not server.cap_exceeded,
                        wire_attempts=server.count,
                        events=list(server.events),
                        cap_exceeded=server.cap_exceeded,
                    )
                    record["arrivals"] = [
                        {"id": event["index"], "t": event["t"]}
                        for event in server.events if event["kind"] == "arrival"
                    ]
                    record["cleanup_audit"] = audit(
                        record,
                        AuditIntent(
                            budget_s=record["budget_s"], tolerance_s=0.04,
                            boundary="cleanup",
                            provenance="explicit local synchronous operation cleanup boundary",
                        ),
                    )
                    expected = "completed" if case["scenario"] == "success" else "timeout"
                    record["expected_mechanism_outcome"] = expected
                    output.write(json.dumps(record, sort_keys=True, allow_nan=False) + "\n")
                    output.flush()
            print(f"completed {seed}", flush=True)


if __name__ == "__main__":
    main()
