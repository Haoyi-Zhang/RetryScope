"""Actual adopted inputs plus benign in-memory perturbations; no evidence writes.

Standalone handoff: set P114_SELECTED_ROOT to the read-only artifact under test.
After integration the default is this test's own artifact. Works with unittest
or pytest, including Python -O; never calls collectors or historical verifier.
"""
from contextlib import redirect_stdout
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]
ROOT = Path(os.environ.get("P114_SELECTED_ROOT", str(HERE))).resolve()
spec = importlib.util.spec_from_file_location("_p114_selected_tests", HERE / "scripts/verify_selected.py")
selected = importlib.util.module_from_spec(spec)
spec.loader.exec_module(selected)


class SelectedSources(unittest.TestCase):
    def run_cli(self, *, paper=False):
        output = io.StringIO()
        args = ["--root", str(ROOT)]
        if paper:
            args += ["--paper-dir", str(ROOT.parent / "paper")]
        with redirect_stdout(output):
            status = selected.main(args)
        return status, json.loads(output.getvalue())

    def change_json(self, suffix, mutate):
        original = Path.read_text
        def changed(path, *args, **kwargs):
            text = original(path, *args, **kwargs)
            if Path(path).as_posix().endswith(suffix):
                value = selected.parse(text, "benign self-owned JSON state")
                mutate(value)
                return json.dumps(value)
            return text
        return patch.object(Path, "read_text", changed)

    def change_rows(self, suffix, mutate):
        original = selected.jsonl
        def changed(path):
            value = original(path)
            if Path(path).as_posix().endswith(suffix):
                value = copy.deepcopy(value)
                mutate(value)
            return value
        return patch.object(selected, "jsonl", side_effect=changed)

    def hold(self, context, expected):
        with context:
            code, report = self.run_cli()
        self.assertEqual(code, 1)
        self.assertEqual(report["status"], "hold")
        self.assertFalse(report["all_history_verified"])
        self.assertIn(expected, report["error"])

    def test_actual_selection_and_repeated_helper_safe_imports(self):
        sentinel = types.ModuleType("analyze_observed")
        before = sys.path[:]
        with patch.dict(sys.modules, {"analyze_observed": sentinel}):
            for _ in range(2):
                code, report = self.run_cli()
                self.assertEqual(code, 0, report.get("error"))
                self.assertIs(sys.modules["analyze_observed"], sentinel)
                self.assertEqual(sys.path, before)
                self.assertFalse(report["all_history_verified"])
                bindings = report["checks"]["retained_phase_source_bindings"]
                self.assertEqual(bindings["resolved_entries"], 12)
                self.assertEqual({r["phase"] for r in bindings["entries"]}, set(selected.RETAINED))
                self.assertEqual(report["phase_sources"], selected.PHASE_SOURCES)
                self.assertEqual(len(report["native_source_provenance"]["files"]), 9)
                self.assertEqual(report["totals"], {"configurations": 228, "operations": 2430,
                                                   "wire_requests": 4986, "maximum_wire_requests_per_operation": 13})

    def test_standalone_never_reads_sibling_paper_or_unselected_history(self):
        original = Path.read_text
        def read(path, *args, **kwargs):
            self.assertTrue(path.resolve().is_relative_to(ROOT), str(path))
            self.assertNotIn("results/raw/observed/", path.as_posix())
            self.assertNotIn("results/observed-derived/", path.as_posix())
            return original(path, *args, **kwargs)
        with patch.object(Path, "read_text", read):
            code, report = self.run_cli()
        self.assertEqual(code, 0, report.get("error"))
        self.assertEqual(report["checks"]["published_count_macros"], "not requested")

    def test_failed_replay_restores_caller_helper_state(self):
        sentinel = types.ModuleType("run_observed_current")
        before, bytecode = sys.path[:], sys.dont_write_bytecode
        with patch.dict(sys.modules, {"run_observed_current": sentinel}), self.change_rows(
                "results/raw/native-policy/false.jsonl", lambda rows: rows.pop()):
            code, report = self.run_cli()
            self.assertEqual(code, 1)
            self.assertIn("incomplete/duplicate observed", report["error"])
            self.assertIs(sys.modules["run_observed_current"], sentinel)
            self.assertEqual(sys.path, before)
            self.assertEqual(sys.dont_write_bytecode, bytecode)

    def test_current_snapshot_changed_or_missing(self):
        original = Path.read_bytes
        target = ROOT / "results/raw/native-policy/source-snapshot/src/retryscope/audit.py"
        for missing in (False, True):
            with self.subTest(missing=missing):
                def read(path):
                    return b"benign changed owned snapshot\n" if path == target else original(path)
                def is_file(path):
                    return False if path == target else real_is_file(path)
                real_is_file = Path.is_file
                with patch.object(Path, "read_bytes", read), patch.object(Path, "is_file", is_file if missing else real_is_file):
                    code, report = self.run_cli()
                self.assertEqual(code, 1)
                self.assertIn("snapshot" if missing else "captured source", report["error"])

    def test_current_freeze_exact_source_set_and_collection_controls(self):
        mutations = (
            (lambda d: d["files"].pop("src/retryscope/audit.py"), "source provenance"),
            (lambda d: d["files"].update({"benign-extra-source.py": "0" * 64}), "source provenance"),
            (lambda d: d.update(analysis_mode="historical"), "analysis mode"),
            (lambda d: d.update(ids="boto_false_default"), "matrix selection"),
            (lambda d: d.update(seeds="301,302"), "current seeds"),
            (lambda d: d.update(utc="2026-10-14T16:22:57"), "timezone-marked UTC"),
            (lambda d: d.update(benign_extra_field=True), "freeze fields"),
        )
        for mutate, message in mutations:
            with self.subTest(message=message):
                self.hold(self.change_json("results/raw/native-policy/freeze.json", mutate), message)

    def test_each_retained_phase_requires_its_declared_source(self):
        for phase, paths in selected.RETAINED.items():
            with self.subTest(phase=phase):
                self.hold(self.change_json(f"results/raw/{phase}/freeze.json",
                                          lambda d: d["sources"].pop(paths[0])), "declaration set")

    def test_each_retained_phase_rejects_unresolvable_bytes(self):
        original = Path.read_bytes
        for relative in ("evidence/source-snapshots/frozen-extension-runner.py",
                         "scripts/async_boundary_study.py", "scripts/sync_enforcement_study.py"):
            with self.subTest(relative=relative):
                def read(path):
                    return b"benign changed owned source\n" if path == ROOT / relative else original(path)
                self.hold(patch.object(Path, "read_bytes", read),
                          "retained relocation" if relative.startswith("evidence/") else "selected retained source hold")

    def test_relocation_identity_digest_and_extra_fields(self):
        mutations = (
            (lambda d: d["relocations"][0].update(preserved_path="../benign-outside.py"), "outside"),
            (lambda d: d["relocations"][0].update(sha256="invalid"), "digest"),
            (lambda d: d["relocations"][0].update(ignore=True), "relocation fields"),
            (lambda d: d["relocations"].pop(0), "selected retained source hold"),
            (lambda d: d["relocations"].append(copy.deepcopy(d["relocations"][0])), "duplicate relocation"),
        )
        for mutate, message in mutations:
            with self.subTest(message=message):
                self.hold(self.change_json("evidence/FROZEN-SOURCE-MAP.json", mutate), message)

    def test_primary_matrix_missing_duplicate_config_trace_audit_and_modes(self):
        mutations = (
            (lambda rows: rows.pop(), "incomplete/duplicate observed"),
            (lambda rows: rows.append(copy.deepcopy(rows[0])), "incomplete/duplicate observed"),
            (lambda rows: rows[0].update(seed=True), "seed/wire type"),
            (lambda rows: rows[0]["config"].update(flag="true"), "case binding"),
            (lambda rows: rows[0].update(phase="observed"), "row phase"),
            (lambda rows: rows[0].update(analysis_mode="historical"), "analysis mode"),
            (lambda rows: rows[0]["source_provenance"]["files"].update({"src/retryscope/audit.py": "0" * 64}), "provenance"),
            (lambda rows: rows[0]["audit_trace"].update(outcome="benign-bad-outcome"), "stored trace"),
            (lambda rows: rows[0]["audit"].update(verdict="benign-bad-verdict"), "stored audit"),
            (lambda rows: rows[0]["legacy_check"].update(verdict="benign-bad-verdict"), "baseline audit"),
        )
        for mutate, message in mutations:
            with self.subTest(message=message):
                self.hold(self.change_rows("results/raw/native-policy/false.jsonl", mutate), message)

    def test_all_selected_summary_and_paper_fields_are_compared(self):
        for suffix in ("results/native-policy-derived/summary.json",
                       "results/migration-derived/summary.json", "results/paper-data.json"):
            with self.subTest(suffix=suffix):
                self.hold(self.change_json(suffix, lambda d: d.update(benign_extra_field=1)), "differs")

    def test_native_and_pair_hashes_phase_accounting_and_policy_selection(self):
        mutations = (
            ("results/native-policy-derived/summary.json", lambda d: d["raw_sha256"].update({"false.jsonl": "0" * 64}), "native policy summary"),
            ("results/migration-derived/summary.json", lambda d: d["initial_raw_sha256"].update({"freeze.json": "0" * 64}), "migration summary"),
            ("results/migration-derived/summary.json", lambda d: d["phase_sources"]["extension"].update(collection="current"), "migration summary"),
            ("results/migration-derived/summary.json", lambda d: d["phase_sources"]["initial"].update(pair_observations=53), "migration summary"),
            ("results/paper-data.json", lambda d: d.update(policy_matrix="results/observed-derived"), "policy selection"),
            ("results/paper-data.json", lambda d: d.update(migration_pairs_use_retained_policy_records=True), "paper-data"),
        )
        for suffix, mutate, message in mutations:
            with self.subTest(message=message):
                self.hold(self.change_json(suffix, mutate), message)

    def test_selected_pair_records_are_recomputed(self):
        self.hold(self.change_rows("results/migration-derived/pairs.jsonl",
                                   lambda r: r[0].update(category="benign-bad-category")), "migration details")

    def test_bad_retained_raw_count_or_binding(self):
        for phase in selected.RETAINED:
            with self.subTest(phase=phase):
                self.hold(self.change_rows(f"results/raw/{phase}/records.jsonl",
                                          lambda r: r[0].update(wire_attempts=True)), "seed/wire type")

    def test_retained_summary_hashes_are_not_ignored(self):
        for derived in ("extension", "async", "sync"):
            with self.subTest(derived=derived):
                self.hold(self.change_json(f"results/{derived}-derived/summary.json",
                                          lambda d: d.update(raw_sha256="0" * 64)), "raw_sha256")

    def test_causal_count_is_taken_from_actual_operations(self):
        self.hold(self.change_rows("results/raw/causal-witness/records.jsonl",
                                   lambda r: r[0]["operations"].pop()), "concurrency count")

    def test_named_macros_not_arbitrary_matching_numbers(self):
        original = Path.read_text
        target = ROOT / "results/native-policy-derived/observed-macros.tex"
        def read(path, *args, **kwargs):
            text = original(path, *args, **kwargs)
            return text.replace("ObservedRuns", "UnrelatedNumber") if path == target else text
        self.hold(patch.object(Path, "read_text", read), "count macros")

    def test_optional_published_count_macros(self):
        if not (ROOT.parent / "paper/generated/study-macros.tex").is_file():
            self.skipTest("standalone artifact: no optional sibling paper")
        code, report = self.run_cli(paper=True)
        self.assertEqual(code, 0, report.get("error"))
        original = Path.read_text
        target = ROOT.parent / "paper/generated/study-macros.tex"
        def read(path, *args, **kwargs):
            text = original(path, *args, **kwargs)
            return text.replace("{2,430}", "{2,431}") if path == target else text
        with patch.object(Path, "read_text", read):
            code, report = self.run_cli(paper=True)
        self.assertEqual(code, 1)
        self.assertIn("count macros", report["error"])

    def test_strict_json_duplicate_keys_nonfinite_and_bool_int(self):
        for text in ('{"x":1,"x":2}', '{"x":NaN}'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                selected.parse(text, "benign self-owned fixture")
        with self.assertRaises(ValueError):
            selected.same(True, 1, "integer count")

    def test_no_collection_regeneration_or_persistent_writes(self):
        original = Path.open
        def opened(path, mode="r", *args, **kwargs):
            self.assertFalse(any(flag in mode for flag in "wax+"), str(path))
            return original(path, mode, *args, **kwargs)
        with patch.object(Path, "open", opened), patch("subprocess.run", side_effect=AssertionError("subprocess prohibited")):
            code, report = self.run_cli()
        self.assertEqual(code, 0, report.get("error"))


if __name__ == "__main__":
    unittest.main()

