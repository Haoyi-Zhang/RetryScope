# RetryScope artifact

RetryScope audits retry and timeout behavior across dependency changes against one explicit application-operation intent. It combines stack-specific client decision witnesses with a concurrency-safe operation/attempt identity protocol, independent loopback wire observations, completion evidence, and a paired migration classifier.

## Principal contribution

The causal witness protocol records an isolated admission snapshot before each wire action:

- a 128-bit logical-operation identifier;
- a 64-bit attempt identifier and ordinal;
- role: `initial`, `retry`, `constituent`, or `recovery`;
- policy owner and observed cause; and
- a parent attempt for retry/recovery edges.

The responder records the carried identifiers independently. The offline join accepts an edge only when client admission and wire arrival agree, then validates uniqueness, parent scope, order, acyclicity, one-to-one admission/arrival coverage, and evidence completeness. Missing or malformed evidence causes classification to abstain rather than infer ownership from timing.

## Retained study

| Phase | Configurations | Logical operations | Wire requests |
|---|---:|---:|---:|
| Policy, HTTP, and integration stacks | 89 | 1,068 | 1,704 |
| Identity, range recovery, and constituent reads | 67 | 402 | 858 |
| Asynchronous operation boundaries | 24 | 144 | 156 |
| Synchronous enforcement boundaries | 16 | 96 | 108 |
| Concurrent causal attribution | 32 analysis cells / 192 seeded batches | 720 | 2,160 |
| **Total** | **228** | **2,430** | **4,986** |

The separate paired analysis reuses 96 executed before/after trace pairs; it is not added to the operation total. The maximum retained requests in one operation is 13, below the protocol cap of 16.

Key retained findings are generated from the records, not hard-coded in the paper:

- client witnesses make all 1,056 requested retry-classification decisions in the 1,068-operation sequential matrix decidable; deleting those witnesses leaves 780 aggregate outcomes unknown;
- 36 successful, correctly framed operations return the wrong same-length object when identity checking is disabled;
- a naive adjacent-request rule raises 36/36 false alarms on healthy fsspec constituent reads, while role-aware auditing raises none;
- exact causal identifiers attribute all 720 concurrent operations and all 2,160 wire attempts; the sequential time-window join falls from 100% exact assignment at concurrency one to 1.8% at concurrency eight;
- all 360 predeclared missing, duplicate, malformed, unknown-attempt, missing-parent, and non-causal-parent mutations fail closed;
- outcome-only and count-only summaries match the declared category on 18/96 and 48/96 paired observations;
- cooperative async timeout and process isolation cover different execution boundaries; the package reports completion and cleanup rather than only timeout notification.

These are bounded local results, not estimates of production prevalence or outage reduction.

## Install and test

Python 3.11 or newer is required. Exact evaluated package versions are recorded in `requirements/locked.txt` and environment evidence in `evidence/`.

```bash
python -m pip install -e '.[test]'
python -m pytest -q
```

The current suite contains 234 tests. The retained study used its recorded source snapshots; new Windows validation uses the current implementation and is kept separately in `results/local-validation/`.

## Regenerate the analyses

```bash
python scripts/analyze_observed.py \
  --raw results/raw/observed \
  --out results/observed-derived

python scripts/analyze_extension.py \
  --raw results/raw/extension \
  --legacy-raw results/raw/evaluation \
  --out results/extension-derived

python scripts/analyze_async.py \
  --raw results/raw/async-boundary \
  --out results/async-derived

python scripts/analyze_sync_enforcement.py \
  --raw results/raw/sync-enforcement \
  --out results/sync-derived

PYTHONPATH=src python scripts/analyze_causal_witness.py \
  --raw results/raw/causal-witness/records.jsonl \
  --out results/causal-derived
PYTHONPATH=src python scripts/analyze_causal_robustness.py \
  --raw results/raw/causal-witness/records.jsonl \
  --out results/causal-derived
python scripts/plot_causal_witness.py \
  --cells results/causal-derived/cells.csv \
  --pdf results/causal-derived/causal-attribution.pdf \
  --svg results/causal-derived/causal-attribution.svg

python scripts/analyze_migrations.py \
  --initial-raw results/raw/observed \
  --manifest study/migration-pairs.json \
  --out results/migration-derived

python scripts/generate_paper.py --paper-dir ../paper
```

The last command copies every manuscript table and the three integrated data-derived vector figures from the retained derived results. It does not use the network or rerun the longer loopback studies.

The evaluated environment and manuscript-dependent self-check is:

```bash
python scripts/verify_all.py
```

This command checks the recorded library versions as well as a sibling `paper/` directory. It is not the portable repository CI command. Portable CI runs the current tests and does not claim to repeat every historical experiment.

## Execute the bounded studies

The raw records are retained because the full studies take longer than the deterministic reanalysis. To execute new loopback runs into separate directories, inspect the corresponding protocol first and provide a new output path:

```bash
python scripts/run_observed_study.py --out results/replay/observed
python scripts/extend_study.py --out results/replay/extension
python scripts/async_boundary_study.py --out results/replay/async-boundary
python scripts/sync_enforcement_study.py --out results/replay/sync-enforcement
PYTHONPATH=src python scripts/causal_witness_study.py \
  --output results/replay/causal-witness/records.jsonl
```

All responders bind to `127.0.0.1`; operations are GET/HEAD-only and bounded by the protocols.

## Repository map

- `src/retryscope/`: checker, paired classifier, causal witness ledger/join, fixtures, and CLIs.
- `tests/`: unit, corpus, malformed-evidence, migration-direction, and CLI tests.
- `study/`: study design, phase protocols, case definitions, and pair manifest.
- `results/raw/`: retained execution records and freeze metadata.
- `results/*-derived/`: tables, figures, summaries, and mutation/overhead analyses.
- `evidence/`: source/license snapshots, environment records, case ledger, trace schema, and 68-entry reference verification ledger.
- `examples/`: executable attempt-count and object-identity migration examples.

## Frozen source relocation

The extension and async records identify the exact `src/retryscope/audit.py` bytes used when they were executed. The live checker now includes paired and causal analysis. The executed source is retained unchanged as `evidence/source-snapshots/frozen-extension-audit.py`; `evidence/FROZEN-SOURCE-MAP.json` records its original path and digest. Raw freeze files are not rewritten.

The historical extension analysis uses that retained checker. Applying the current checker, which also requires an explicit policy owner, to the unchanged 402 extension records yields 174 pass and 228 unknown. Older records lack that owner field; it is not backfilled from an outcome or timestamp. The measured download outcomes and request counts are unaffected. New replay instrumentation records the owner at admission time.

## Scope

RetryScope is intended for bounded, safely replayable migration tests with a stated operation contract and trusted client instrumentation. It does not make non-idempotent work safe, provide a whole-service reliability score, infer an application requirement from a library default, or turn a timeout notification into proof that all work has stopped.
