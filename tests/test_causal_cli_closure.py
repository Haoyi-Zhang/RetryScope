"""Owned offline closure regressions; no client, server or network execution."""
from contextlib import redirect_stdout
import io
import json
import unittest
from unittest.mock import patch

from retryscope import causal_cli
from retryscope.audit import AuditIntent, audit


def streams(count=1):
    op = '1' * 32
    client, wire = [], []
    for i in range(1, count + 1):
        attempt = format(i, '016x')
        client.append({'kind': 'admission', 'operation_id': op,
                       'attempt_id': attempt, 'ordinal': i,
                       'role': 'initial' if i == 1 else 'constituent',
                       'owner': 'owned toy client', 'parent_attempt_id': None})
        wire.append({'kind': 'arrival', 'operation_id': op, 'attempt_id': attempt,
                     'ordinal': i, 'global_index': i, 'operation_index': i,
                     'witness_valid': True})
    return op, client, wire


class CausalCLIClosureTests(unittest.TestCase):
    def run_cli(self, count=1, closed=False):
        op, client, wire = streams(count)
        args = ['--client-events', 'owned-client.json', '--wire-events', 'owned-wire.json',
                '--operation-id', op] + (['--stream-complete'] if closed else [])
        output = io.StringIO()
        with patch.object(causal_cli, '_load_events', side_effect=[client, wire]), redirect_stdout(output):
            code = causal_cli.main(args)
        return code, json.loads(output.getvalue())

    def test_balanced_prefix_is_unknown_without_closure(self):
        code, trace = self.run_cli()
        self.assertEqual(code, 2)
        self.assertFalse(trace['arrival_stream_complete'])
        self.assertFalse(trace['causal_join_complete'])
        self.assertEqual(audit(trace, AuditIntent(max_wire_attempts=2))['verdict'], 'unknown')

    def test_explicit_trusted_closure_allows_pass(self):
        code, trace = self.run_cli(closed=True)
        self.assertEqual(code, 0)
        self.assertTrue(trace['causal_join_complete'])
        self.assertEqual(audit(trace, AuditIntent(max_wire_attempts=2))['verdict'], 'pass')

    def test_observed_over_cap_prefix_still_mismatches(self):
        code, trace = self.run_cli(count=2)
        self.assertEqual(code, 2)
        self.assertEqual(audit(trace, AuditIntent(max_wire_attempts=1))['verdict'], 'mismatch')


if __name__ == '__main__':
    unittest.main()
