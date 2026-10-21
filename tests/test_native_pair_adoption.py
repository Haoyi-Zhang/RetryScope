"""Captured-generation selection and explicit paired-phase accounting.

The collection's persisted 'current' label is not today's live source tree.
All four original controls run in an actually matching full captured copy.
"""
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('_native_pair_adoption', ROOT / 'scripts/analyze_migrations.py')
analyzer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analyzer)
import verify_selected_captured as captured

INPUT_ROOT = ROOT


class NativePairAdoption(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        replay, _ = cls.enterClassContext(captured.captured_artifact(INPUT_ROOT, temp_parent=INPUT_ROOT.parent))
        _, replay_analyzer, _, _ = cls.enterClassContext(captured.selected.helpers(replay))
        cls.enterClassContext(patch(__name__ + '.ROOT', replay))
        cls.enterClassContext(patch(__name__ + '.analyzer', replay_analyzer))

    def test_selected_native_matrix_revalidates_current_source(self):
        sources = analyzer.load_sources(ROOT / 'results/raw/native-policy')
        self.assertEqual(len(sources['initial']), 1068)
        self.assertTrue(all(row['analysis_mode'] == 'current' for row in sources['initial']))

    def test_partial_current_records_cannot_be_used_as_a_complete_matrix(self):
        row = {'id': 'boto_false_default', 'seed': 301, 'analysis_mode': 'current'}
        with patch.object(analyzer, 'read_jsonl', return_value=[row]):
            with self.assertRaisesRegex(SystemExit, 'incomplete/duplicate observed study'):
                analyzer.load_sources(ROOT / 'results/raw/native-policy')

    def test_generated_pairs_identify_their_phase_sources(self):
        summary = json.loads((ROOT / 'results/migration-derived/summary.json').read_text())
        self.assertEqual(summary['phase_sources'], {
            'initial': {'pair_observations': 54, 'collection': 'current'},
            'extension': {'pair_observations': 30, 'collection': 'retained'},
            'async': {'pair_observations': 12, 'collection': 'retained'}})
        self.assertEqual(sum(x['pair_observations'] for x in summary['phase_sources'].values()), 96)

    def test_paper_data_selects_current_policy_and_pair_sources(self):
        data = json.loads((ROOT / 'results/paper-data.json').read_text())
        self.assertEqual(data['policy_analysis_mode'], 'current')
        self.assertFalse(data['migration_pairs_use_retained_policy_records'])
        self.assertEqual(data['migration_phase_sources']['initial']['pair_observations'], 54)
        self.assertEqual(data['migration_phase_sources']['extension']['collection'], 'retained')


if __name__ == '__main__':
    unittest.main()
