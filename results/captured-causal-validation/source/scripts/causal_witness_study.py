#!/usr/bin/env python3
"""Execute the bounded causal-witness concurrency study on loopback HTTP only."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import random
from threading import Barrier
import time
from typing import Any, Callable

import requests
import urllib3

from retryscope.audit import AuditIntent, audit
from retryscope.causal import WitnessLedger, deterministic_operation_id, join_causal_trace
from retryscope.causal_fixture import CausalResponder, PAYLOAD

STACKS = ("requests", "urllib3")
SCENARIOS = ("retry", "nested", "constituent", "recovery")
CONCURRENCIES = (1, 2, 4, 8)
SEEDS = (11, 23, 37, 53, 71, 89)
ATTEMPTS = {"retry": 2, "nested": 4, "constituent": 4, "recovery": 2}


@dataclass
class OperationResult:
    operation_id: str
    client_events: list[dict[str, Any]]
    outcome: str
    payload_digest: str | None
    payload_complete: bool
    elapsed_s: float
    error: str | None


def _jitter(seed: int, operation_index: int, stage: int, concurrency: int) -> None:
    # Admissions are synchronized before each stage. Reverse-order delays force
    # arrival order to differ from client-event order without random sleeps.
    slots = (concurrency - 1 - operation_index + seed + stage * 3) % max(concurrency, 1)
    time.sleep(slots * 0.0007)


def _requests_send(session: requests.Session, url: str, headers: dict[str, str], *, stream: bool = False):
    return session.get(url, headers=headers, timeout=(1.0, 1.0), stream=stream)


def _urllib3_send(pool: urllib3.PoolManager, url: str, headers: dict[str, str], *, stream: bool = False):
    return pool.request(
        "GET",
        url,
        headers=headers,
        retries=False,
        timeout=urllib3.Timeout(connect=1.0, read=1.0),
        preload_content=not stream,
    )


def _status(response: Any) -> int:
    return int(response.status_code if hasattr(response, "status_code") else response.status)


def _body(response: Any) -> bytes:
    return bytes(response.content if hasattr(response, "content") else response.data)


def _close(response: Any) -> None:
    close = getattr(response, "close", None)
    if callable(close):
        close()
    release = getattr(response, "release_conn", None)
    if callable(release):
        release()


def _read_stream(response: Any, stack: str) -> tuple[bytes, BaseException | None]:
    chunks: list[bytes] = []
    try:
        if stack == "requests":
            for chunk in response.iter_content(chunk_size=8):
                if chunk:
                    chunks.append(chunk)
        else:
            while True:
                chunk = response.read(8)
                if not chunk:
                    break
                chunks.append(chunk)
        return b"".join(chunks), None
    except BaseException as exc:  # captured as evidence, then recovered locally
        return b"".join(chunks), exc
    finally:
        _close(response)


def _intent(scenario: str) -> AuditIntent:
    if scenario == "retry":
        return AuditIntent(max_wire_attempts=2, retryable_statuses=(503,), required_outcome="success")
    if scenario == "nested":
        return AuditIntent(max_wire_attempts=4, retryable_statuses=(503,), required_outcome="success")
    if scenario == "constituent":
        return AuditIntent(max_wire_attempts=4, retryable_statuses=(503,), required_outcome="success")
    if scenario == "recovery":
        return AuditIntent(
            max_wire_attempts=2,
            retryable_statuses=(),
            allow_body_recovery=True,
            required_outcome="success",
            expected_payload=hashlib.sha256(PAYLOAD).hexdigest(),
        )
    raise AssertionError(scenario)


def _run_operation(
    *,
    stack: str,
    scenario: str,
    concurrency: int,
    seed: int,
    operation_index: int,
    base_url: str,
    barriers: list[Barrier],
) -> OperationResult:
    label = f"{stack}:{scenario}:{concurrency}:{seed}:{operation_index}"
    ledger = WitnessLedger(deterministic_operation_id(label))
    started = time.monotonic()
    error: str | None = None
    outcome = "error"
    payload: bytes | None = None
    client: Any
    if stack == "requests":
        client = requests.Session()
        client.trust_env = False
        send: Callable[..., Any] = lambda url, headers, stream=False: _requests_send(client, url, headers, stream=stream)
    else:
        client = urllib3.PoolManager(num_pools=1, maxsize=2)
        send = lambda url, headers, stream=False: _urllib3_send(client, url, headers, stream=stream)

    def admit_send(stage: int, *, role: str, owner: str, path: str, parent=None, cause=None, headers=None, stream=False):
        ticket = ledger.admit(
            role=role,
            owner=owner,
            parent=parent,
            cause=cause,
            nonce=f"{seed}-{operation_index}-{stage}",
        )
        barriers[stage - 1].wait(timeout=2.0)
        _jitter(seed, operation_index, stage, concurrency)
        merged = ledger.headers(ticket)
        if headers:
            merged.update(headers)
        response = send(base_url + path, merged, stream=stream)
        return ticket, response

    try:
        if scenario == "retry":
            first, response = admit_send(1, role="initial", owner=f"{stack}.operation", path="/retry")
            status = _status(response)
            ledger.complete(first, status=status, bytes_read=len(_body(response)))
            _close(response)
            second, response = admit_send(
                2,
                role="retry",
                owner=f"{stack}.status-policy",
                path="/retry",
                parent=first,
                cause={"kind": "status", "received_status": status},
            )
            status = _status(response)
            payload = _body(response)
            ledger.complete(second, status=status, bytes_read=len(payload))
            _close(response)
            outcome = "success" if status == 200 and payload == PAYLOAD else "error"

        elif scenario == "nested":
            parent = None
            owners = (f"{stack}.inner", f"{stack}.inner", "outer-wrapper", f"{stack}.inner")
            for stage, owner in enumerate(owners, start=1):
                if stage == 1:
                    role = "initial"
                    cause = None
                else:
                    role = "retry"
                    cause = {"kind": "status", "received_status": 503}
                ticket, response = admit_send(
                    stage,
                    role=role,
                    owner=owner,
                    path="/nested",
                    parent=parent,
                    cause=cause,
                )
                status = _status(response)
                body = _body(response)
                ledger.complete(ticket, status=status, bytes_read=len(body))
                _close(response)
                parent = ticket
                if stage == 4:
                    payload = body
                    outcome = "success" if status == 200 and body == PAYLOAD else "error"

        elif scenario == "constituent":
            assembled: list[bytes] = []
            first, response = admit_send(1, role="constituent", owner="read-plan", path="/constituent/meta")
            status = _status(response)
            ledger.complete(first, status=status, bytes_read=len(_body(response)))
            _close(response)
            second, response = admit_send(2, role="constituent", owner="read-plan", path="/constituent/a")
            status = _status(response)
            body = _body(response)
            assembled.append(body)
            ledger.complete(second, status=status, bytes_read=len(body))
            _close(response)
            third, response = admit_send(3, role="constituent", owner="read-plan", path="/constituent/b")
            status = _status(response)
            ledger.complete(third, status=status, bytes_read=len(_body(response)))
            _close(response)
            fourth, response = admit_send(
                4,
                role="retry",
                owner=f"{stack}.status-policy",
                path="/constituent/b",
                parent=third,
                cause={"kind": "status", "received_status": status},
            )
            status = _status(response)
            body = _body(response)
            assembled.append(body)
            ledger.complete(fourth, status=status, bytes_read=len(body))
            _close(response)
            payload = b"".join(assembled)
            outcome = "success" if status == 200 and payload == PAYLOAD else "error"

        elif scenario == "recovery":
            first, response = admit_send(1, role="initial", owner=f"{stack}.reader", path="/recovery", stream=True)
            partial, read_error = _read_stream(response, stack)
            ledger.complete(first, error=read_error or "missing expected body failure", bytes_read=len(partial))
            if read_error is None:
                raise RuntimeError("truncated fixture did not produce a body error")
            second, response = admit_send(
                2,
                role="recovery",
                owner=f"{stack}.reader",
                path="/recovery",
                parent=first,
                cause={"kind": "body_error", "exception": type(read_error).__name__},
                headers={"Range": f"bytes={len(partial)}-"},
            )
            status = _status(response)
            remainder = _body(response)
            ledger.complete(second, status=status, bytes_read=len(remainder))
            _close(response)
            payload = partial + remainder
            outcome = "success" if status == 206 and payload == PAYLOAD else "error"
        else:
            raise AssertionError(scenario)
    except BaseException as exc:
        error = f"{type(exc).__module__}.{type(exc).__name__}: {exc}"
        outcome = "error"
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()
        clear = getattr(client, "clear", None)
        if callable(clear):
            clear()

    elapsed = time.monotonic() - started
    digest = hashlib.sha256(payload).hexdigest() if payload is not None else None
    return OperationResult(
        operation_id=ledger.operation_id,
        client_events=ledger.events,
        outcome=outcome,
        payload_digest=digest,
        payload_complete=payload is not None,
        elapsed_s=elapsed,
        error=error,
    )


def _timestamp_assignment(client_events: list[dict[str, Any]], wire_events: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    admissions = sorted((event for event in client_events if event.get("kind") == "admission"), key=lambda event: event["t_ns"])
    arrivals = sorted((event for event in wire_events if event.get("kind") == "arrival" and event.get("witness_valid")), key=lambda event: event["t_ns"])
    used: set[int] = set()
    result: dict[tuple[str, str], dict[str, Any]] = {}
    previous = -1
    for arrival in arrivals:
        candidates = [
            (index, event)
            for index, event in enumerate(admissions)
            if index not in used and previous <= event["t_ns"] <= arrival["t_ns"]
        ]
        if candidates:
            index, event = max(candidates, key=lambda pair: pair[1]["t_ns"])
            used.add(index)
            result[(arrival["operation_id"], arrival["attempt_id"])] = event
        previous = arrival["t_ns"]
    return result


def _score_batch(results: list[OperationResult], wire_events: list[dict[str, Any]], scenario: str) -> dict[str, Any]:
    client_events = [event for result in results for event in result.client_events]
    timestamp = _timestamp_assignment(client_events, wire_events)
    admissions = {
        (event["operation_id"], event["attempt_id"]): event
        for event in client_events
        if event.get("kind") == "admission"
    }
    traces = {result.operation_id: join_causal_trace(
        client_events, wire_events, operation_id=result.operation_id,
        stream_complete=True, outcome=result.outcome, payload=result.payload_digest,
        payload_complete=result.payload_complete, elapsed_s=result.elapsed_s)
        for result in results}
    token_predictions = {(op, row.get('attempt_id')): row
                         for op, trace in traces.items() for row in trace['arrivals']
                         if row.get('attribution_witness')}
    valid_arrivals = [event for event in wire_events if event.get("kind") == "arrival" and event.get("witness_valid")]
    valid_arrivals.sort(key=lambda event: event["t_ns"])
    token_correct = timestamp_correct = 0
    timestamp_role_correct = timestamp_owner_correct = 0
    adjacency_role_correct = 0
    token_role_correct = token_owner_correct = 0
    expected_edges: set[tuple[str, str, str, str, str]] = set()
    timestamp_edges: set[tuple[str, str, str, str, str]] = set()
    token_edges: set[tuple[str, str, str, str, str]] = set()
    by_operation: dict[str, list[dict[str, Any]]] = {}
    for arrival in valid_arrivals:
        by_operation.setdefault(arrival["operation_id"], []).append(arrival)
        key = (arrival["operation_id"], arrival["attempt_id"])
        truth = admissions[key]
        token = token_predictions.get(key)
        token_correct += int(token is not None and token.get('attempt_id') == truth['attempt_id'])
        token_role_correct += int(token is not None and token.get('role') == truth.get('role'))
        token_owner_correct += int(token is not None and token.get('owner') == truth.get('owner'))
        predicted = timestamp.get(key)
        if predicted and predicted["attempt_id"] == truth["attempt_id"] and predicted["operation_id"] == truth["operation_id"]:
            timestamp_correct += 1
        if predicted and predicted.get("role") == truth.get("role"):
            timestamp_role_correct += 1
        if predicted and predicted.get("owner") == truth.get("owner"):
            timestamp_owner_correct += 1
        if truth.get("parent_attempt_id"):
            expected_edges.add((truth["operation_id"], truth["parent_attempt_id"], truth["attempt_id"], truth["role"], truth["owner"]))
        if predicted and predicted.get("parent_attempt_id"):
            timestamp_edges.add((
                arrival["operation_id"],
                predicted["parent_attempt_id"],
                arrival["attempt_id"],
                predicted["role"],
                predicted["owner"],
            ))
    for operation_id, arrivals in by_operation.items():
        arrivals.sort(key=lambda event: event["operation_index"])
        for index, arrival in enumerate(arrivals):
            truth = admissions[(operation_id, arrival["attempt_id"])]
            predicted_role = "initial" if index == 0 else "retry"
            adjacency_role_correct += int(predicted_role == truth["role"])

    audit_verdicts: dict[str, int] = {"pass": 0, "mismatch": 0, "unknown": 0}
    joins_complete = 0
    for result in results:
        trace = traces[result.operation_id]
        ordinals = {row['id']: row.get('attempt_id') for row in trace['arrivals']}
        for row in trace['arrivals']:
            parent = ordinals.get(row.get('retry_of'))
            if parent and row.get('attribution_witness'):
                token_edges.add((result.operation_id, parent, row['attempt_id'], row['role'], row['owner']))
        joins_complete += int(trace["causal_join_complete"])
        audit_verdicts[audit(trace, _intent(scenario))["verdict"]] += 1

    def edge_metrics(predicted: set[tuple[str, str, str, str, str]]) -> dict[str, Any]:
        true_positive = len(predicted & expected_edges)
        precision = true_positive / len(predicted) if predicted else (1.0 if not expected_edges else 0.0)
        recall = true_positive / len(expected_edges) if expected_edges else 1.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        return {
            "predicted": len(predicted),
            "expected": len(expected_edges),
            "true_positive": true_positive,
            "precision": precision,
            "recall": recall,
            "f1": f1,
        }

    total = len(valid_arrivals)
    return {
        "operations": len(results),
        "wire_attempts": total,
        "joins_complete": joins_complete,
        "audit_verdicts": audit_verdicts,
        "assignment_accuracy": {
            "causal_token": token_correct / total if total else 1.0,
            "timestamp_window": timestamp_correct / total if total else 1.0,
        },
        "role_accuracy": {
            "causal_token": token_role_correct / total if total else 1.0,
            "timestamp_window": timestamp_role_correct / total if total else 1.0,
            "adjacency": adjacency_role_correct / total if total else 1.0,
        },
        "owner_accuracy": {
            "causal_token": token_owner_correct / total if total else 1.0,
            "timestamp_window": timestamp_owner_correct / total if total else 1.0,
        },
        "edge_metrics": {
            "causal_token": edge_metrics(token_edges),
            "timestamp_window": edge_metrics(timestamp_edges),
        },
    }


def run_cell(stack: str, scenario: str, concurrency: int, seed: int) -> dict[str, Any]:
    random.seed(seed)
    barriers = [Barrier(concurrency) for _ in range(ATTEMPTS[scenario])]
    with CausalResponder() as responder:
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = [
                pool.submit(
                    _run_operation,
                    stack=stack,
                    scenario=scenario,
                    concurrency=concurrency,
                    seed=seed,
                    operation_index=index,
                    base_url=responder.url,
                    barriers=barriers,
                )
                for index in range(concurrency)
            ]
            results = [future.result(timeout=10.0) for future in futures]
        if not responder.quiesce():
            raise RuntimeError("responder did not quiesce")
        wire_events = [dict(event) for event in responder.events]
    score = _score_batch(results, wire_events, scenario)
    if any(result.error for result in results):
        raise RuntimeError(f"operation failure: {[result.error for result in results if result.error]}")
    return {
        "schema": 1,
        "stack": stack,
        "scenario": scenario,
        "concurrency": concurrency,
        "seed": seed,
        "score": score,
        "operations": [
            {
                "operation_id": result.operation_id,
                "outcome": result.outcome,
                "payload_digest": result.payload_digest,
                "payload_complete": result.payload_complete,
                "elapsed_s": result.elapsed_s,
                "client_events": result.client_events,
            }
            for result in results
        ],
        "wire_events": wire_events,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--stacks", default=",".join(STACKS))
    parser.add_argument("--scenarios", default=",".join(SCENARIOS))
    parser.add_argument("--concurrency", default=",".join(map(str, CONCURRENCIES)))
    parser.add_argument("--seeds", default=",".join(map(str, SEEDS)))
    args = parser.parse_args()
    stacks = tuple(item for item in args.stacks.split(",") if item)
    scenarios = tuple(item for item in args.scenarios.split(",") if item)
    levels = tuple(int(item) for item in args.concurrency.split(",") if item)
    seeds = tuple(int(item) for item in args.seeds.split(",") if item)
    if any(stack not in STACKS for stack in stacks) or any(scenario not in SCENARIOS for scenario in scenarios):
        raise SystemExit("unsupported stack or scenario")
    if any(level not in CONCURRENCIES for level in levels) or any(seed not in SEEDS for seed in seeds):
        raise SystemExit("unsupported concurrency or seed")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        for stack in stacks:
            for scenario in scenarios:
                for concurrency in levels:
                    for seed in seeds:
                        record = run_cell(stack, scenario, concurrency, seed)
                        stream.write(json.dumps(record, sort_keys=True, allow_nan=False) + "\n")
                        stream.flush()
                        score = record["score"]
                        print(
                            f"{stack} {scenario} c={concurrency} seed={seed} "
                            f"token={score['assignment_accuracy']['causal_token']:.3f} "
                            f"time={score['assignment_accuracy']['timestamp_window']:.3f} "
                            f"audit={score['audit_verdicts']}",
                            flush=True,
                        )


if __name__ == "__main__":
    main()
