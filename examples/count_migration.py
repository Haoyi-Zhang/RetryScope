#!/usr/bin/env python3
"""Execute a bounded before/after count migration on unsigned loopback S3.

The two-wire operation contract is a local, explicit maintenance probe. The
example compares the same installed botocore release under two documented
configuration forms; it does not contact AWS and does not claim a field defect.
"""
from pathlib import Path
import argparse, json, os, sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
os.environ['AWS_NEW_RETRIES_2026'] = 'true'
# worker removes credential/proxy influences before any SDK import.
from retryscope.worker import run
from retryscope.audit import AuditIntent, from_legacy
from retryscope.migration import compare_migration


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='Optional new JSON output file')
    args = parser.parse_args()
    intent = AuditIntent(
        max_wire_attempts=2,
        required_outcome='error',
        provenance='researcher-authored two-wire persistent-failure probe',
    )
    # The execution worker retains the archived schema-1 intent shape so the
    # immutable study path stays reproducible; v3 comparison uses AuditIntent.
    common = dict(stack='boto', mode='native', scenario='persistent', flag='true', intent={'max_wire_attempts':2})
    before_raw = run(dict(common, id='migration_before', retries={'mode':'standard','max_attempts':2}), 401, 'example')
    after_raw = run(dict(common, id='migration_after', retries={'mode':'standard','total_max_attempts':2}), 401, 'example')
    if not all(r.get('trace_complete') for r in (before_raw, after_raw)):
        raise RuntimeError('Incomplete local replay; inspect output rather than claiming a result')
    before, after = from_legacy(before_raw), from_legacy(after_raw)
    result = compare_migration(before, after, intent, pair_id='count_migration_example')
    assert (before_raw['wire_attempts'], after_raw['wire_attempts']) == (3, 2)
    assert result['category'] == 'repair'
    payload = {
        'before_raw': before_raw,
        'after_raw': after_raw,
        'intent': intent.to_dict(),
        'comparison': result,
    }
    text = json.dumps(payload, indent=2, allow_nan=False) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x') as stream:
            stream.write(text)
    print(json.dumps({
        'before_wire_attempts': before_raw['wire_attempts'],
        'after_wire_attempts': after_raw['wire_attempts'],
        'category': result['category'],
        'after_verdict': result['after']['verdict'],
        'deadline_guarantee': False,
    }, indent=2))


if __name__ == '__main__':
    main()
