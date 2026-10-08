import importlib.util
from pathlib import Path
import subprocess

import pytest


@pytest.fixture
def verifier():
    path = Path(__file__).parents[1] / "scripts/verify_all.py"
    spec = importlib.util.spec_from_file_location("unit_verifier", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("summary", ["226 passed in 0.4s", "234 passed in 0.5s", "248 passed in 0.6s"])
def test_successful_pytest_summary_has_no_fixed_count(verifier, monkeypatch, summary):
    def successful_run(command, **kwargs):
        assert command[1:5] == ["-B", "-m", "pytest", "-q"]
        return subprocess.CompletedProcess(command, 0, stdout=summary + "\n", stderr="")
    monkeypatch.setattr(verifier.subprocess, "run", successful_run)
    assert verifier.run_unit_tests() == summary


def test_pytest_failure_is_not_accepted_from_success_looking_output(verifier, monkeypatch):
    def failed_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, stdout="234 passed, 1 failed", stderr="unit failure")
    monkeypatch.setattr(verifier.subprocess, "run", failed_run)
    with pytest.raises(SystemExit, match="command failed"):
        verifier.run_unit_tests()


def test_unresolved_sources_stop_before_regeneration(verifier, monkeypatch):
    commands = []
    def unresolved_source(command, **kwargs):
        commands.append(command)
        assert Path(command[-1]).name == "verify_frozen_sources.py"
        raise SystemExit("unresolved historical source")
    monkeypatch.setattr(verifier.sys, "argv", ["verify_all.py"])
    monkeypatch.setattr(verifier, "run_checked", unresolved_source)
    with pytest.raises(SystemExit, match="unresolved historical source"):
        verifier.main()
    assert len(commands) == 1
