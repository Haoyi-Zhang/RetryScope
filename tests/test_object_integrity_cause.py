import importlib.util
from pathlib import Path


def test_integrity_failure_is_not_a_transport_body_error():
    path = Path(__file__).parents[1] / 'scripts' / 'extend_study.py'
    spec = importlib.util.spec_from_file_location('identity_study', path)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    case = {'id': 'requests_new_hash_corrupt_once', 'family': 'download',
            'mode': 'requests_new_hash', 'scenario': 'corrupt_once'}
    record = runner.run(case, 731)
    assert record['outcome'] == 'success'
    assert record['wire_attempts'] == 2
    assert record['arrivals'][1]['cause']['kind'] == 'content_mismatch'
    assert record['operations'][0]['exception'] == 'IntegrityMismatch'
    assert record['retry_audit']['verdict'] == 'pass'
