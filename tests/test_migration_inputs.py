"""Stdlib-only paired-input regressions; no native runs or timing."""
import copy
from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "_p114_migration_inputs", ROOT / "scripts/analyze_migrations.py")
analyzer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analyzer)


def row(seed, **fields):
    return dict(id="selected", seed=seed, outcome="success", **fields)


class MigrationInputTests(unittest.TestCase):
    def test_duplicate_selected_seed_is_rejected(self):
        rows = [row(1), row(1, payload="different")]
        original = copy.deepcopy(rows)
        with self.assertRaisesRegex(ValueError, "duplicate pairing seed"):
            analyzer.select(rows, {"id": "selected"}, "extension")
        self.assertEqual(rows, original)

    def test_seed_requires_exact_integer_before_alias_lookup(self):
        for seed in (True, False, 1.0, 1.9, "1", None, [], {}):
            with self.subTest(seed=seed):
                with self.assertRaisesRegex(ValueError, "must be an integer"):
                    analyzer.key(row(seed), "extension")
                with self.assertRaisesRegex(ValueError, "must be an integer"):
                    analyzer.select([row(0), row(1), row(seed)],
                                    {"id": "selected"}, "extension")

    def test_id_and_file_filters_remain_in_effect(self):
        rows = [row(1, _file="true"), row(True, _file="false"),
                dict(id="other", seed=1), row(1, _file="false")]
        selected = analyzer.select(rows, {"id": "selected", "file": "true"}, "extension")
        self.assertEqual(list(selected), [1])
        self.assertEqual(selected[1]["_file"], "true")

    def test_fewer_than_six_shared_seeds_are_rejected(self):
        for shared in (0, 1, 5):
            with self.subTest(shared=shared):
                before = dict.fromkeys(range(6))
                after = dict.fromkeys(list(range(shared)) + list(range(10, 16)))
                with self.assertRaisesRegex(ValueError, "at least six shared pairing seeds"):
                    analyzer.paired_seeds(before, after, "owned-test-pair")

    def test_valid_six_and_first_six_ordering(self):
        for count in (6, 8):
            with self.subTest(count=count):
                before = dict.fromkeys(reversed(range(count)))
                after = dict.fromkeys(range(count))
                self.assertEqual(analyzer.paired_seeds(before, after, "owned-test-pair"),
                                 list(range(6)))

    def test_manifest_loop_rejects_five_and_accepts_six(self):
        manifest = [{"id": "fsspec_metadata_discovery", "phase": "extension",
                     "before": {"id": "before"}, "after": {"id": "after"},
                     "intent": {"required_outcome": "success"},
                     "expected": "stable_conformant", "basis": "in-memory unit fixture"}]
        for shared in (5, 6):
            with self.subTest(shared=shared):
                rows = [dict(row(seed), id="before") for seed in range(6)]
                rows += [dict(row(seed), id="after")
                         for seed in list(range(shared)) + ([6] if shared == 5 else [])]
                args = analyzer.argparse.Namespace(out=MagicMock(), paper_dir=None,
                                                  initial_raw=None, manifest=MagicMock())
                args.manifest.read_text.return_value = json.dumps(manifest)
                with patch.object(analyzer.argparse.ArgumentParser, "parse_args", return_value=args), \
                     patch.object(analyzer, "load_sources", return_value={"extension": rows}), \
                     redirect_stdout(io.StringIO()):
                    if shared == 5:
                        with self.assertRaisesRegex(ValueError, "at least six shared pairing seeds"):
                            analyzer.main()
                    else:
                        analyzer.main()
                        summary = json.loads(args.out.__truediv__.return_value.write_text.call_args_list[0].args[0])
                        self.assertEqual(summary["pair_observations"], 6)

    def test_directional_control_keeps_before_after_order(self):
        before = analyzer.select([row(1)], {"id": "selected"}, "extension")[1]
        after = {**before, "outcome": "error"}
        intent = analyzer.AuditIntent(required_outcome="success")
        self.assertEqual(analyzer.compare_migration(before, after, intent)["category"], "regression")
        self.assertEqual(analyzer.compare_migration(after, before, intent)["category"], "repair")

    def test_observation_mutation_preserves_raw_record(self):
        rows = [row(1, arrivals=[{"id": 1}], arrival_stream_complete=True)]
        original = copy.deepcopy(rows)
        before = analyzer.select(rows, {"id": "selected"}, "extension")[1]
        after = analyzer.select(rows, {"id": "selected", "mutate": {
            "arrival_stream_complete": False}}, "extension")[1]
        intent = analyzer.AuditIntent(max_wire_attempts=2)
        self.assertEqual(analyzer.compare_migration(before, after, intent)["category"], "evidence_loss")
        self.assertEqual(rows, original)


if __name__ == "__main__":
    unittest.main()
