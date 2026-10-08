import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


@pytest.fixture
def resolver():
    path = Path(__file__).parents[1] / "scripts/verify_frozen_sources.py"
    spec = importlib.util.spec_from_file_location("source_resolver", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def synthetic_evidence(root, phases, digest, relocations=()):
    for phase in phases:
        directory = root / "results/raw" / phase
        directory.mkdir(parents=True)
        key = "files" if phase == "observed" else "sources"
        (directory / "freeze.json").write_text(json.dumps({key: {"src/worker.py": digest}}))
    evidence = root / "evidence"
    evidence.mkdir(exist_ok=True)
    (evidence / "FROZEN-SOURCE-MAP.json").write_text(json.dumps({"relocations": list(relocations)}))


@pytest.mark.parametrize("phase", ["observed", "extension", "async-boundary", "sync-enforcement"])
def test_each_principal_phase_resolves_matching_live_bytes(resolver, tmp_path, phase):
    resolver.PRINCIPAL_PHASES = (phase,)
    worker = tmp_path / "src/worker.py"
    worker.parent.mkdir()
    worker.write_bytes(b"owned synthetic source\n")
    digest = hashlib.sha256(worker.read_bytes()).hexdigest()
    synthetic_evidence(tmp_path, (phase,), digest)
    report = resolver.resolve_frozen_sources(tmp_path)
    assert report["status"] == "resolved" and report["resolved_entries"] == 1
    assert report["entries"][0]["resolved_path"] == "src/worker.py"


def test_changed_live_source_resolves_only_genuine_snapshot(resolver, tmp_path):
    historical = b"owned historical source\n"
    digest = hashlib.sha256(historical).hexdigest()
    synthetic_evidence(tmp_path, resolver.PRINCIPAL_PHASES, digest, [{
        "frozen_path": "src/worker.py", "preserved_path": "evidence/old-worker.py", "sha256": digest,
    }])
    (tmp_path / "src").mkdir()
    (tmp_path / "src/worker.py").write_bytes(b"owned current source\n")
    (tmp_path / "evidence/old-worker.py").write_bytes(historical)
    report = resolver.resolve_frozen_sources(tmp_path)
    assert report["resolved_entries"] == 4 and report["unresolved"] == []
    assert all(entry["resolved_path"] == "evidence/old-worker.py" for entry in report["entries"])


@pytest.mark.parametrize("source_state", ["missing", "changed_live", "incorrect_snapshot"])
def test_unresolved_source_fails_read_only(resolver, tmp_path, capsys, source_state):
    digest = hashlib.sha256(b"owned historical source\n").hexdigest()
    relocations = [{"frozen_path": "src/worker.py", "preserved_path": "evidence/old-worker.py", "sha256": digest}]
    synthetic_evidence(tmp_path, resolver.PRINCIPAL_PHASES, digest, relocations)
    if source_state != "missing":
        (tmp_path / "src").mkdir()
        (tmp_path / "src/worker.py").write_bytes(b"owned current source\n")
    if source_state == "incorrect_snapshot":
        (tmp_path / "evidence/old-worker.py").write_bytes(b"not the historical bytes\n")
    before = {path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    assert resolver.main(["--root", str(tmp_path)]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["resolved_entries"] == 0 and len(report["unresolved"]) == 4
    after = {path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    assert before == after
