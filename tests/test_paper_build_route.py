"""Owned partial-failure fixtures for the sibling manuscript build route."""
import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

BUILD = Path(__file__).resolve().parents[2] / 'paper/build.py'


@unittest.skipUnless(BUILD.is_file(), 'Requires the complete sibling-paper package')
class PaperBuildRouteTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.paper = self.base / 'paper'
        (self.paper / 'figures').mkdir(parents=True)
        (self.paper / 'figures/workflow.pdf').write_bytes(b'%PDF-retained-diagram')
        (self.paper / 'main.pdf').write_bytes(b'%PDF-retained-manuscript')
        (self.paper / 'main.tex').write_text('Owned build-route fixture')
        shutil.copyfile(BUILD, self.paper / 'build.py')
        self.renderer = self.base / 'artifact/plots/draw_workflow.py'
        self.renderer.parent.mkdir(parents=True)
        self.consumer = self.base / 'artifact/scripts/current_migration_receipt.py'
        self.consumer.parent.mkdir(parents=True)
        self.consumer.write_text(
            'import argparse\nfrom pathlib import Path\n'
            'p=argparse.ArgumentParser();p.add_argument("--paper-dir",type=Path);a=p.parse_args()\n'
            '(a.paper_dir/"generated").mkdir(exist_ok=True)\n'
            '(a.paper_dir/"generated/current-migration-rows.tex").write_text("owned row fixture")\n')
        spec = importlib.util.spec_from_file_location('owned_retry_builder', self.paper / 'build.py')
        self.build = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.build)

    def snapshot(self):
        return {p.relative_to(self.paper).as_posix(): p.read_bytes()
                for p in self.paper.rglob('*') if p.is_file()}

    def test_missing_engine_does_not_render_or_replace(self):
        before = self.snapshot()
        with patch.object(self.build.shutil, 'which', return_value=None), \
                patch.object(self.build.subprocess, 'run') as run:
            with self.assertRaises(SystemExit):
                self.build.main()
        run.assert_not_called()
        self.assertEqual(self.snapshot(), before)

    def test_partial_renderer_failure_keeps_original_assets(self):
        self.renderer.write_text(
            'import argparse\nfrom pathlib import Path\n'
            'p=argparse.ArgumentParser();p.add_argument("--output-dir",type=Path);a=p.parse_args()\n'
            '(a.output_dir/"workflow.pdf").write_bytes(b"owned partial output")\n'
            'raise RuntimeError("owned renderer failure")\n')
        before = self.snapshot()
        real_run = self.build.subprocess.run
        def captured(command, **kwargs):
            return real_run(command, capture_output=True, text=True, **kwargs)
        with patch.object(self.build.shutil, 'which', return_value='owned-unused-engine'), \
                patch.object(self.build.subprocess, 'run', side_effect=captured):
            with self.assertRaises(subprocess.CalledProcessError):
                self.build.main()
        self.assertEqual(self.snapshot(), before)

    def test_tex_failure_after_render_keeps_original_assets(self):
        self.renderer.write_text('# Renderer replaced with an owned fixture below.\n')
        before = self.snapshot()
        outputs = []
        def run(command, **kwargs):
            if command[0] == sys.executable:
                if '--paper-dir' in command:
                    output = Path(command[command.index('--paper-dir') + 1]) / 'generated'
                    output.mkdir(exist_ok=True)
                    (output / 'current-migration-rows.tex').write_text('owned row fixture')
                    return subprocess.CompletedProcess(command, 0)
                output = Path(command[command.index('--output-dir') + 1])
                outputs.append(output)
                (output / 'workflow.pdf').write_bytes(b'%PDF-owned-new-diagram')
                return subprocess.CompletedProcess(command, 0)
            raise subprocess.CalledProcessError(1, command)
        with patch.object(self.build.shutil, 'which', side_effect=lambda name: name), \
                patch.object(self.build.subprocess, 'run', side_effect=run):
            with self.assertRaises(subprocess.CalledProcessError):
                self.build.main()
        self.assertEqual(len(outputs), 1)
        self.assertNotEqual(outputs[0], self.paper / 'figures')
        self.assertFalse(outputs[0].exists())
        self.assertEqual(self.snapshot(), before)

    def test_invalid_receipt_keeps_original_assets(self):
        self.consumer.write_text('raise ValueError("owned rejected receipt fixture")\n')
        before = self.snapshot()
        real_run = self.build.subprocess.run
        def captured(command, **kwargs):
            return real_run(command, capture_output=True, text=True, **kwargs)
        with patch.object(self.build.shutil, 'which', return_value='owned-unused-engine'), \
                patch.object(self.build.subprocess, 'run', side_effect=captured):
            with self.assertRaises(subprocess.CalledProcessError):
                self.build.main()
        self.assertEqual(self.snapshot(), before)


if __name__ == '__main__':
    unittest.main()
