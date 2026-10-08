"""Finite synthetic offline mode/provenance regressions; no measured results."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("_p114_analyze_observed_modes", ROOT / "scripts/analyze_observed.py")
analyzer = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = analyzer
spec.loader.exec_module(analyzer)
from retryscope.retained import recorded_audit


class ObservedAnalysisModes(unittest.TestCase):
    def setUp(self):
        base = Path(os.environ.get("P114_TEST_ROOT", tempfile.gettempdir())).resolve()
        self.temp = tempfile.TemporaryDirectory(prefix="p114-modes-", dir=base)
        self.directory = Path(self.temp.name).resolve()
        assert self.directory != base and self.directory.is_relative_to(base)
        self.addCleanup(self.temp.cleanup)
        self.snapshot = self.directory / "source"
        self.files = {}
        for relative in analyzer.CURRENT_SOURCE_FILES:
            source = ROOT / relative
            target = self.snapshot / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            self.files[relative] = hashlib.sha256(source.read_bytes()).hexdigest()
        self.freeze = {"analysis_mode": "current", "files": self.files}
        self.provenance = analyzer.analysis_provenance(self.freeze, "current", self.snapshot)

    def record(self, mode="historical", config=None):
        config = copy.deepcopy(config or {
            "id": "synthetic-status-retry", "stack": "requests", "mode": "native",
            "intent": {"max_wire_attempts": 2, "retryable_statuses": [503]},
        })
        row = {
            "id": config["id"], "seed": 301, "config": config,
            "trace_complete": True, "cap_exceeded": False, "wire_attempts": 2,
            "outcome": "success", "payload": "0123456789",
            "elapsed_s": 0.01, "headers_elapsed_s": 0.001,
            "events": [
                {"kind": "arrival", "index": 1, "t": 10.0},
                {"kind": "arrival", "index": 2, "t": 10.2},
            ],
            "client_events": [
                {"kind": "retry_start", "t": 10.1, "source": "synthetic.retry-owner",
                 "cause": {"kind": "status", "received_status": 503}},
            ],
        }
        row["audit_trace"] = analyzer.build_trace(row)
        intent = analyzer.audit_intent(config)
        if mode == "current":
            row["analysis_mode"] = "current"
            row["source_provenance"] = copy.deepcopy(self.provenance)
            row["audit"] = analyzer.audit(row["audit_trace"], intent)
        else:
            row["audit"] = recorded_audit(row["audit_trace"], intent, "observed")
        return row

    def validate_current(self, row):
        analyzer.validate_record_audit(
            row, analyzer.build_trace(row), analysis_mode="current", provenance=self.provenance
        )

    def matrix(self, mode):
        raw = self.directory / mode
        raw.mkdir()
        configs = json.loads((ROOT / "study/cases.json").read_text())
        rows = [self.record(mode, config) for config in configs]
        for flag in ("false", "true"):
            selected = [r for r in rows if r["config"].get("flag", "true") == flag]
            (raw / (flag + ".jsonl")).write_text(
                "".join(json.dumps(r) + "\n" for r in selected), encoding="utf-8"
            )
        freeze = self.freeze if mode == "current" else {"phase": "synthetic-historical", "files": {}}
        (raw / "freeze.json").write_text(json.dumps(freeze), encoding="utf-8")
        return raw, rows

    def test_default_historical_uses_only_retained_exact_replay(self):
        row = self.record()
        with patch.object(analyzer, "audit", side_effect=AssertionError("current validator selected")):
            analyzer.validate_record_audit(row, analyzer.build_trace(row))

    def test_current_fixture_uses_only_current_exact_replay(self):
        row = self.record("current")
        self.assertEqual(row["audit"]["verdict"], "pass")
        with patch("retryscope.retained.recorded_audit", side_effect=AssertionError("historical fallback")):
            self.validate_current(row)

    def test_current_rejects_nested_audit_tampering_with_same_verdict(self):
        row = self.record("current")
        row["audit"]["dimensions"]["classification"]["requests"][1]["owner"] = "tampered-owner"
        self.assertEqual(row["audit"]["verdict"], "pass")
        with self.assertRaisesRegex(SystemExit, "stored audit does not recompute"):
            self.validate_current(row)

    def test_current_rejects_tampered_or_ambiguous_record_provenance(self):
        for change in ("missing", "unmarked", "wrong_digest", "missing_file", "extra_file", "historical", "unknown", "conflicting_mode"):
            with self.subTest(change=change):
                row = self.record("current")
                files = row["source_provenance"]["files"]
                if change == "missing":
                    del row["source_provenance"]
                elif change == "unmarked":
                    del row["analysis_mode"]
                elif change == "wrong_digest":
                    files["src/retryscope/audit.py"] = "0" * 64
                elif change == "missing_file":
                    del files["src/retryscope/worker.py"]
                elif change == "extra_file":
                    files["extra.py"] = "0" * 64
                elif change in ("historical", "unknown"):
                    row["source_provenance"]["analysis_mode"] = change
                else:
                    row["analysis_mode"] = "historical"
                with self.assertRaises(SystemExit):
                    self.validate_current(row)

    def test_current_does_not_accept_a_retained_audit_even_if_verdict_matches(self):
        row = self.record("current")
        old = recorded_audit(row["audit_trace"], analyzer.audit_intent(row["config"]), "observed")
        self.assertEqual(row["audit"]["verdict"], old["verdict"])
        self.assertNotEqual(row["audit"], old)
        row["audit"] = old
        with self.assertRaisesRegex(SystemExit, "stored audit does not recompute"):
            self.validate_current(row)

    def test_current_helper_rejects_conflicting_expected_provenance(self):
        row = self.record("current")
        row["source_provenance"]["analysis_mode"] = "historical"
        with self.assertRaisesRegex(SystemExit, "current record source provenance"):
            analyzer.validate_record_audit(
                row, analyzer.build_trace(row), analysis_mode="current", provenance=row["source_provenance"]
            )

    def test_historical_rejects_bad_old_audit_with_same_verdict(self):
        row = self.record()
        row["audit"]["dimensions"]["classification"]["requests"][1]["role"] = "initial"
        self.assertEqual(row["audit"]["verdict"], "pass")
        with self.assertRaisesRegex(SystemExit, "stored audit does not recompute"):
            analyzer.validate_record_audit(row, analyzer.build_trace(row))

    def test_historical_does_not_try_current_validator_for_unmarked_current_json(self):
        row = self.record("current")
        del row["source_provenance"]
        del row["analysis_mode"]
        with patch.object(analyzer, "audit", side_effect=AssertionError("current fallback")):
            with self.assertRaisesRegex(SystemExit, "stored audit does not recompute"):
                analyzer.validate_record_audit(row, analyzer.build_trace(row))

    def test_historical_rejects_current_or_ambiguous_record_markers(self):
        for marker in (self.provenance, None, {"analysis_mode": "historical"}):
            with self.subTest(marker=marker):
                row = self.record()
                row["source_provenance"] = marker
                with self.assertRaisesRegex(SystemExit, "ambiguous record provenance"):
                    analyzer.validate_record_audit(row, analyzer.build_trace(row))

    def test_current_requires_explicit_freeze_mode_and_snapshot(self):
        with self.assertRaisesRegex(SystemExit, "requires --source-snapshot"):
            analyzer.analysis_provenance(self.freeze, "current", None)
        for freeze in ({"files": self.files}, {"analysis_mode": "historical", "files": self.files}):
            with self.subTest(freeze=freeze):
                with self.assertRaisesRegex(SystemExit, "freeze analysis mode"):
                    analyzer.analysis_provenance(freeze, "current", self.snapshot)

    def test_current_rejects_tampered_missing_or_extra_freeze_sources(self):
        for change in ("wrong", "missing", "extra"):
            with self.subTest(change=change):
                freeze = copy.deepcopy(self.freeze)
                if change == "wrong":
                    freeze["files"]["src/retryscope/audit.py"] = "0" * 64
                elif change == "missing":
                    del freeze["files"]["src/retryscope/worker.py"]
                else:
                    freeze["files"]["extra.py"] = "0" * 64
                with self.assertRaisesRegex(SystemExit, "freeze source provenance"):
                    analyzer.analysis_provenance(freeze, "current", self.snapshot)

    def test_current_rejects_changed_captured_implementation(self):
        (self.snapshot / "src/retryscope/audit.py").write_text("# synthetic changed source\n")
        with self.assertRaisesRegex(SystemExit, "captured source does not match"):
            analyzer.analysis_provenance(self.freeze, "current", self.snapshot)

    def test_current_rejects_missing_snapshot_dependency(self):
        missing = self.directory / "empty-source"
        missing.mkdir()
        with self.assertRaisesRegex(SystemExit, "missing current source or captured"):
            analyzer.analysis_provenance(self.freeze, "current", missing)

    def test_current_rejects_imported_module_from_another_tree(self):
        with patch.object(sys.modules["retryscope.audit"], "__file__", str(self.directory / "other.py")):
            with self.assertRaisesRegex(SystemExit, "imported from another source"):
                analyzer.analysis_provenance(self.freeze, "current", self.snapshot)

    def test_historical_rejects_conflicting_batch_mode_or_snapshot(self):
        with self.assertRaisesRegex(SystemExit, "freeze analysis mode"):
            analyzer.analysis_provenance(self.freeze, "historical", None)
        with self.assertRaisesRegex(SystemExit, "only allowed in current"):
            analyzer.analysis_provenance({}, "historical", self.snapshot)

    def test_unknown_modes_are_not_permissive(self):
        with self.assertRaisesRegex(SystemExit, "unsupported analysis mode"):
            analyzer.analysis_provenance(self.freeze, "either", self.snapshot)
        row = self.record()
        with self.assertRaisesRegex(SystemExit, "unsupported analysis mode"):
            analyzer.validate_record_audit(row, analyzer.build_trace(row), analysis_mode="either")

    def test_current_full_synthetic_matrix_validates_without_plotting(self):
        plotting_before = sys.modules.get("matplotlib")
        raw, rows = self.matrix("current")
        self.assertEqual(
            analyzer.validate(rows, raw, range(301, 302), analysis_mode="current", source_snapshot=self.snapshot),
            self.provenance,
        )
        self.assertIs(sys.modules.get("matplotlib"), plotting_before)

    def test_historical_full_synthetic_matrix_keeps_default_validation(self):
        raw, rows = self.matrix("historical")
        self.assertIsNone(analyzer.validate(rows, raw, range(301, 302)))

    def test_historical_preserves_opaque_legacy_freeze_boundary(self):
        raw, rows = self.matrix("historical")
        for content in ("", "synthetic opaque legacy freeze", "null", "[]"):
            with self.subTest(content=content):
                (raw / "freeze.json").write_text(content, encoding="utf-8")
                self.assertIsNone(analyzer.validate(rows, raw, range(301, 302)))

    def test_current_rejects_non_json_freeze_provenance(self):
        raw, rows = self.matrix("current")
        (raw / "freeze.json").write_text("synthetic opaque freeze", encoding="utf-8")
        with self.assertRaisesRegex(SystemExit, "requires JSON freeze provenance"):
            analyzer.validate(rows, raw, range(301, 302), analysis_mode="current", source_snapshot=self.snapshot)

    def test_current_matrix_rejects_one_unmarked_historical_record(self):
        raw, rows = self.matrix("current")
        rows[0] = self.record("historical", rows[0]["config"])
        with self.assertRaisesRegex(SystemExit, "current record source provenance"):
            analyzer.validate(rows, raw, range(301, 302), analysis_mode="current", source_snapshot=self.snapshot)

    def test_historical_matrix_rejects_one_current_record(self):
        raw, rows = self.matrix("historical")
        rows[0] = self.record("current", rows[0]["config"])
        with self.assertRaisesRegex(SystemExit, "record analysis mode conflicts"):
            analyzer.validate(rows, raw, range(301, 302))

    def test_current_matrix_still_rejects_trace_tampering(self):
        raw, rows = self.matrix("current")
        rows[0]["audit_trace"]["arrival_stream_complete"] = False
        with self.assertRaisesRegex(SystemExit, "stored trace does not recompute"):
            analyzer.validate(rows, raw, range(301, 302), analysis_mode="current", source_snapshot=self.snapshot)


if __name__ == "__main__":
    unittest.main(verbosity=2)
