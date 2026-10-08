"""Offline mock collection only: synthetic timestamps are not study measurements."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import analyze_observed as analyzer
import run_observed_current as runner
import run_observed_study as historical_runner
from retryscope.retained import recorded_audit


def synthetic_record(config, seed, phase, historical=False):
    row = {
        "id": config["id"], "config": copy.deepcopy(config), "seed": seed, "phase": phase,
        "trace_complete": True, "cap_exceeded": False, "wire_attempts": 2,
        "outcome": "success", "payload": "0123456789", "elapsed_s": 0.01,
        "headers_elapsed_s": 0.001,
        "events": [{"kind": "arrival", "index": 1, "t": 10.0},
                   {"kind": "arrival", "index": 2, "t": 10.2}],
        "client_events": [{"kind": "retry_start", "t": 10.1, "source": "synthetic.retry-owner",
                           "cause": {"kind": "status", "received_status": 503}}],
    }
    row["audit_trace"] = analyzer.build_trace(row)
    intent = analyzer.audit_intent(config)
    row["audit"] = (recorded_audit(row["audit_trace"], intent, "observed") if historical
                    else analyzer.audit(row["audit_trace"], intent))
    return row


class CurrentCollectorContract(unittest.TestCase):
    def setUp(self):
        base = Path(os.environ.get("P114_TEST_ROOT", tempfile.gettempdir())).resolve()
        self.temp = tempfile.TemporaryDirectory(prefix="p114-collector-", dir=base)
        self.directory = Path(self.temp.name).resolve()
        assert self.directory != base and self.directory.is_relative_to(base)
        self.addCleanup(self.temp.cleanup)
        for owner, name in ((socket, "socket"), (runner.subprocess, "Popen")):
            guard = patch.object(owner, name, side_effect=AssertionError("offline test attempted I/O"))
            guard.start()
            self.addCleanup(guard.stop)
        self.out = self.directory / "fresh"
        self.calls = []

    def mock_policy_process(self, command, *, cwd, env, check, timeout):
        self.assertTrue(check)
        self.assertGreater(timeout, 0)
        self.assertLessEqual(timeout, 900)
        snapshot = self.out / "source-snapshot"
        self.assertEqual(cwd, snapshot)
        self.assertEqual(Path(command[2]), snapshot / "scripts/run_observed_current.py")
        self.assertEqual(command[command.index("--run-mode") + 1], "current")
        self.assertEqual(env["PYTHONPATH"], str(snapshot / "src"))
        freeze = json.loads((self.out / "freeze.json").read_text())
        self.assertEqual(set(freeze["files"]), set(runner.CURRENT_SOURCE_FILES))
        self.assertEqual(len(freeze["files"]), 9)
        spec = importlib.util.spec_from_file_location("_p114_captured_collector", command[2])
        captured_runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(captured_runner)
        self.assertEqual(captured_runner.ROOT, snapshot.resolve())
        flag = command[command.index("--policy-flag") + 1]

        def mock_collector(config, seed, phase):
            # This executes only after all nine captured bytes and freeze exist.
            for relative, digest in freeze["files"].items():
                self.assertEqual(hashlib.sha256((snapshot / relative).read_bytes()).hexdigest(), digest)
            self.calls.append((flag, config["id"], seed))
            return synthetic_record(config, seed, phase)

        captured_runner.collect_policy(self.out, flag, "301", "", collector=mock_collector)

    def produce_current(self):
        with patch.object(runner.subprocess, "run", side_effect=self.mock_policy_process) as process:
            freeze = runner.run_current(self.out, "301", "")
        self.assertEqual(process.call_count, 2)
        rows = analyzer.load_jsonl([self.out / "false.jsonl", self.out / "true.jsonl"])
        return freeze, rows

    def validate_current(self, rows):
        return analyzer.validate(rows, self.out, range(301, 302), analysis_mode="current",
                                 source_snapshot=self.out / "source-snapshot")

    def test_captured_collector_metadata_is_accepted_by_current_analyzer(self):
        freeze, rows = self.produce_current()
        configs = json.loads((ROOT / "study/cases.json").read_text())
        self.assertEqual(len(rows), len(configs))
        self.assertEqual(len(self.calls), len(configs))
        expected = {"analysis_mode": "current", "files": freeze["files"]}
        self.assertEqual(self.validate_current(rows), expected)
        self.assertTrue(all(row["analysis_mode"] == "current" and row["source_provenance"] == expected
                            for row in rows))
        self.assertIn("scripts/run_observed_current.py", expected["files"])
        self.assertNotIn("scripts/run_observed_study.py", expected["files"])
        self.assertNotIn("retryscope.observed_worker", sys.modules)
        self.assertNotIn("matplotlib", sys.modules)

    def test_current_cli_dispatches_capture_before_mock_collection(self):
        with patch.object(sys, "argv", ["run_observed_current.py", "--run-mode", "current",
                                        "--out", str(self.out), "--seeds", "301"]):
            with patch.object(runner.subprocess, "run", side_effect=self.mock_policy_process):
                with patch("builtins.print"):
                    runner.main()
        rows = analyzer.load_jsonl([self.out / "false.jsonl", self.out / "true.jsonl"])
        self.assertIsNotNone(self.validate_current(rows))

    def test_default_historical_delegates_original_commands_and_exact_validation(self):
        configs = json.loads((ROOT / "study/cases.json").read_text())

        def historical_process(command, *, cwd, env, check):
            self.assertEqual(command[:3], [sys.executable, "-m", "retryscope.observed_worker"])
            self.assertEqual(cwd, ROOT)
            self.assertEqual(env["PYTHONPATH"], str(ROOT / "src"))
            self.assertTrue(check)
            target = Path(command[command.index("--output") + 1])
            flag = command[command.index("--flag") + 1]
            rows = [synthetic_record(c, 301, "observed", historical=True)
                    for c in configs if c.get("flag", "true") == flag]
            with target.open("x", encoding="utf-8") as output:
                output.write("".join(json.dumps(row) + "\n" for row in rows))

        with patch.object(sys, "argv", ["run_observed_current.py", "--out", str(self.out), "--seeds", "301"]):
            with patch.object(runner, "run_current", side_effect=AssertionError("current selected")):
                with patch.object(historical_runner.subprocess, "run", side_effect=historical_process) as process:
                    with patch("builtins.print"):
                        runner.main()
        self.assertEqual(process.call_count, 2)
        freeze = json.loads((self.out / "freeze.json").read_text())
        self.assertNotIn("analysis_mode", freeze)
        self.assertEqual(len(freeze["files"]), 5)
        self.assertFalse((self.out / "source-snapshot").exists())
        rows = analyzer.load_jsonl([self.out / "false.jsonl", self.out / "true.jsonl"])
        self.assertTrue(all("source_provenance" not in row and "analysis_mode" not in row for row in rows))
        self.assertIsNone(analyzer.validate(rows, self.out, range(301, 302)))
        row = next(row for row in rows if row["id"] == "req_native_success")
        row["audit"]["dimensions"]["classification"]["requests"][1]["role"] = "initial"
        with self.assertRaisesRegex(SystemExit, "stored audit does not recompute"):
            analyzer.validate(rows, self.out, range(301, 302))

    def test_current_records_cannot_be_analyzed_as_historical(self):
        _, rows = self.produce_current()
        with self.assertRaisesRegex(SystemExit, "freeze analysis mode"):
            analyzer.validate(rows, self.out, range(301, 302))

    def test_collected_record_audit_and_source_tampering_rejected(self):
        _, rows = self.produce_current()
        for change in ("audit", "digest", "mode", "unmarked", "missing"):
            with self.subTest(change=change):
                tampered = copy.deepcopy(rows)
                row = next(row for row in tampered if row["id"] == "req_native_success")
                if change == "audit":
                    row["audit"]["dimensions"]["classification"]["requests"][1]["owner"] = "tampered"
                elif change == "digest":
                    row["source_provenance"]["files"]["scripts/run_observed_current.py"] = "0" * 64
                elif change == "mode":
                    row["analysis_mode"] = "historical"
                elif change == "unmarked":
                    del row["analysis_mode"]
                else:
                    del row["source_provenance"]
                with self.assertRaises(SystemExit):
                    self.validate_current(tampered)

    def test_existing_directory_refused_before_any_collection(self):
        self.out.mkdir()
        with patch.object(runner.subprocess, "run", side_effect=AssertionError("collection started")):
            with self.assertRaises(FileExistsError):
                runner.run_current(self.out, "301", "")
        self.assertEqual(list(self.out.iterdir()), [])

    def test_source_tampering_before_or_during_collection_refused(self):
        for during in (False, True):
            with self.subTest(during=during):
                out = self.directory / str(during)
                runner.prepare_current(out, "301", "")
                source = out / "source-snapshot/src/retryscope/audit.py"
                calls = []

                def collector(config, seed, phase):
                    calls.append(config["id"])
                    source.write_bytes(b"# synthetic source tampering\n")
                    return synthetic_record(config, seed, phase)

                if not during:
                    source.write_bytes(b"# synthetic source tampering\n")
                with self.assertRaisesRegex(SystemExit, "captured source does not match"):
                    runner.collect_policy(out, "true", "301", "", collector=collector)
                self.assertEqual(len(calls), int(during))
                if during:
                    self.assertEqual((out / "true.jsonl").read_text(), "")

    def test_premarked_or_conflicting_collector_records_not_retagged(self):
        case = "req_native_success"
        for conflict in ("provenance", "seed", "config", "phase"):
            with self.subTest(conflict=conflict):
                selected = self.directory / conflict
                runner.prepare_current(selected, "301", case)

                def collector(config, seed, phase):
                    row = synthetic_record(config, seed, phase)
                    if conflict == "provenance":
                        row["source_provenance"] = {"analysis_mode": "historical"}
                    elif conflict == "seed":
                        row["seed"] = 302
                    elif conflict == "config":
                        row["config"]["scenario"] = "synthetic-conflict"
                    else:
                        row["phase"] = "historical"
                    return row

                with self.assertRaises(SystemExit):
                    runner.collect_policy(selected, "true", "301", case, collector=collector)
                self.assertEqual((selected / "true.jsonl").read_text(), "")

    def test_batch_control_and_freeze_digest_tampering_rejected_before_callback(self):
        freeze = runner.prepare_current(self.out, "301", "")
        with self.assertRaisesRegex(SystemExit, "controls conflict"):
            runner.collect_policy(self.out, "true", "302", "", collector=synthetic_record)
        freeze["files"]["src/retryscope/worker.py"] = "0" * 64
        (self.out / "freeze.json").write_text(json.dumps(freeze))
        with self.assertRaisesRegex(SystemExit, "freeze source provenance"):
            runner.collect_policy(self.out, "true", "301", "", collector=synthetic_record)
        self.assertFalse((self.out / "true.jsonl").exists())

    def test_child_environment_does_not_inherit_tokens_proxies_or_user_home(self):
        with patch.dict(os.environ, {"AWS_ACCESS_KEY_ID": "synthetic-not-a-credential",
                                    "HF_TOKEN": "synthetic-not-a-credential", "HTTP_PROXY": "synthetic",
                                    "https_proxy": "synthetic", "HOME": "synthetic-other-home",
                                    "AZURE_CLIENT_SECRET": "synthetic-not-a-credential"}):
            env = runner.child_environment(self.out, self.out / "source-snapshot")
        for key in ("AWS_ACCESS_KEY_ID", "HF_TOKEN", "HTTP_PROXY", "https_proxy", "AZURE_CLIENT_SECRET"):
            self.assertNotIn(key, env)
        self.assertEqual(env["HOME"], str(self.out))
        self.assertEqual(env["AWS_SHARED_CREDENTIALS_FILE"], os.devnull)

    def test_current_cli_requires_explicit_fresh_out_and_rejects_mixed_controls(self):
        for args in (["--run-mode", "current"], ["--policy-flag", "true"], ["--run-mode", "either"]):
            with self.subTest(args=args), patch.object(sys, "argv", ["runner"] + args):
                with patch("sys.stderr"), self.assertRaises(SystemExit):
                    runner.main()

    def test_current_shared_deadline_stops_before_spawning_policy(self):
        with patch.object(runner.time, "monotonic", side_effect=[0, 901]):
            with patch.object(runner.subprocess, "run", side_effect=AssertionError("collection started")):
                with self.assertRaisesRegex(SystemExit, "15-minute bound"):
                    runner.run_current(self.out, "301", "")
        self.assertFalse((self.out / "false.jsonl").exists())

    def test_analyzer_rejects_collector_batch_digest_tampering(self):
        freeze, rows = self.produce_current()
        freeze["files"]["scripts/run_observed_current.py"] = "0" * 64
        (self.out / "freeze.json").write_text(json.dumps(freeze))
        with self.assertRaisesRegex(SystemExit, "freeze source provenance"):
            self.validate_current(rows)

    def test_current_main_writes_derived_summary_without_optional_plot_dependency(self):
        _, rows = self.produce_current()
        for filename in ("false.jsonl", "true.jsonl"):
            selected = [dict(row) for row in rows if row["_source_file"] == filename]
            for row in selected:
                row["legacy_check"] = {"verdict": row["audit"]["verdict"]}
                del row["_source_file"]
            (self.out / filename).write_text(
                "".join(json.dumps(row) + "\n" for row in selected), encoding="utf-8")
        derived = self.directory / "derived"
        plotting = types.ModuleType("matplotlib")
        plotting.use = MagicMock()
        plotting.rcParams = {}
        pyplot = types.ModuleType("matplotlib.pyplot")
        pyplot.subplots = MagicMock(return_value=(MagicMock(), MagicMock()))
        pyplot.close = MagicMock()
        args = ["analyze_observed.py", "--raw", str(self.out), "--out", str(derived),
                "--analysis-mode", "current", "--source-snapshot", str(self.out / "source-snapshot"),
                "--seed-start", "301", "--seed-stop", "302"]
        with patch.object(sys, "argv", args), patch("builtins.print"):
            with patch.dict(sys.modules, {"matplotlib": plotting, "matplotlib.pyplot": pyplot}):
                analyzer.main()
        summary = json.loads((derived / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["records"], 89)
        self.assertEqual(summary["analysis_mode"], "current")
        self.assertEqual(summary["raw_sha256"], {
            name: hashlib.sha256((self.out / name).read_bytes()).hexdigest()
            for name in ("false.jsonl", "true.jsonl")})
        self.assertTrue((derived / "observed-macros.tex").is_file())
        self.assertEqual(pyplot.subplots.call_count, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
