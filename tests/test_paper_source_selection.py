"""The manuscript must not combine equal-sized but different observation sets."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('paper_source_selection', ROOT/'scripts/generate_paper.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PaperSourceSelectionTests(unittest.TestCase):
    def fixtures(self):
        raw = {'false.jsonl': 'first-input', 'true.jsonl': 'second-input'}
        policy = {'analysis_mode': 'current', 'raw_sha256': raw.copy()}
        pairs = {'initial_raw_sha256': raw.copy(),
                 'phase_sources': {'initial': {'collection': 'current'}}}
        return policy, pairs

    def test_matching_collection_is_accepted(self):
        module.validate_policy_pair_sources(*self.fixtures())

    def test_same_counts_do_not_admit_different_input_bytes(self):
        policy, pairs = self.fixtures()
        policy['raw_sha256']['false.jsonl'] = 'historical-input'
        policy['records'] = pairs['records'] = 1068
        with self.assertRaises(ValueError):
            module.validate_policy_pair_sources(policy, pairs)

    def test_missing_policy_identity_is_rejected(self):
        policy, pairs = self.fixtures()
        del policy['raw_sha256']['true.jsonl']
        with self.assertRaises(ValueError):
            module.validate_policy_pair_sources(policy, pairs)

    def test_missing_pair_identity_is_rejected(self):
        policy, pairs = self.fixtures()
        pairs.pop('initial_raw_sha256')
        with self.assertRaises(ValueError):
            module.validate_policy_pair_sources(policy, pairs)

    def test_collection_mode_mismatch_is_rejected(self):
        policy, pairs = self.fixtures()
        policy['analysis_mode'] = 'historical'
        with self.assertRaises(ValueError):
            module.validate_policy_pair_sources(policy, pairs)

    def test_explicit_consistent_retained_collection_is_accepted(self):
        policy, pairs = self.fixtures()
        policy['analysis_mode'] = 'historical'
        pairs['phase_sources']['initial']['collection'] = 'retained'
        module.validate_policy_pair_sources(policy, pairs)
