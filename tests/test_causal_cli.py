import json

from retryscope.causal import WitnessLedger, deterministic_operation_id
from retryscope.causal_cli import main


def test_causal_cli_joins_json_arrays(tmp_path):
    ledger = WitnessLedger(deterministic_operation_id("cli"))
    ticket = ledger.admit(role="initial", owner="client")
    client = tmp_path / "client.json"
    wire = tmp_path / "wire.json"
    out = tmp_path / "trace.json"
    client.write_text(json.dumps(ledger.events))
    wire.write_text(json.dumps([{
        "kind": "arrival",
        "global_index": 1,
        "operation_index": 1,
        "ordinal": ticket.ordinal,
        "operation_id": ticket.operation_id,
        "attempt_id": ticket.attempt_id,
        "witness_valid": True,
    }]))
    assert main([
        "--client-events", str(client),
        "--wire-events", str(wire),
        "--operation-id", ledger.operation_id,
        "--stream-complete",
        "--output", str(out),
    ]) == 0
    assert json.loads(out.read_text())["causal_join_complete"] is True


def test_causal_cli_rejects_non_object_jsonl(tmp_path):
    client = tmp_path / "client.jsonl"
    wire = tmp_path / "wire.jsonl"
    client.write_text("[]\n")
    wire.write_text("")
    assert main([
        "--client-events", str(client),
        "--wire-events", str(wire),
        "--operation-id", "1" * 32,
    ]) == 3
