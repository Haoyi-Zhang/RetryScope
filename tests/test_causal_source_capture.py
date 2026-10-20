"""Captured-source execution must retain actual bytes and reject later changes."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('causal_capture',ROOT/'scripts/capture_causal_study.py')
capture=importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture)


class CausalSourceCaptureTests(unittest.TestCase):
    def test_snapshot_contains_driver_and_complete_local_module_inventory(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest=Path(tmp)/'source'
            identities=capture.capture_sources(ROOT,dest)
            self.assertIn('scripts/causal_witness_study.py',identities)
            self.assertIn('src/retryscope/ordinary.py',identities)
            self.assertEqual(len(identities),len(capture.source_files(ROOT)))
            capture.verify_capture(dest,identities)
            for relative in identities:
                self.assertEqual((dest/relative).read_bytes(),(ROOT/relative).read_bytes())

    def test_changed_captured_bytes_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest=Path(tmp)/'source'
            identities=capture.capture_sources(ROOT,dest)
            (dest/'src/retryscope/ordinary.py').write_text('changed')
            with self.assertRaises(ValueError):
                capture.verify_capture(dest,identities)

    def test_existing_snapshot_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest=Path(tmp)/'source'
            capture.capture_sources(ROOT,dest)
            with self.assertRaises(FileExistsError):
                capture.capture_sources(ROOT,dest)
