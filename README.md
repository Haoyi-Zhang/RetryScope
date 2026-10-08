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
- exact causal identifiers attribute all 720 concurrent operations and all 2,160 wire attempts; the sequential time-window join falls from 100% exact assignment at concurrency one to 1.6% at concurrency eight (19/1,152 wire attempts);
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

Obtain the current suite size with `python -B -m pytest --collect-only -q -p no:cacheprovider`; the count changes when regressions are added. The retained study identifies its historical sources in freeze metadata, subject to the observed-worker limitation below. Tests of the current implementation do not validate the worker bytes used by an older run. New Windows study validation is kept separately in `results/local-validation/`.

## Regenerate the analyses

Run these commands from `artifact/` in a prepared environment. Allocate a fresh comparison root outside the project; each analyzer creates its own new subdirectory. Do not delete or reuse the retained raw or derived directories. The following Bash example uses an externally owned temporary directory:

```bash
COMPARE_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/retryscope-compare.XXXXXXXX")
export PYTHONPATH="$PWD/src"

python scripts/analyze_observed.py \
  --raw results/raw/observed \
  --out "$COMPARE_ROOT/observed-derived"

python scripts/analyze_extension.py \
  --raw results/raw/extension \
  --legacy-raw results/raw/evaluation \
  --out "$COMPARE_ROOT/extension-derived"

python scripts/analyze_async.py \
  --raw results/raw/async-boundary \
  --out "$COMPARE_ROOT/async-derived"

python scripts/analyze_sync_enforcement.py \
  --raw results/raw/sync-enforcement \
  --out "$COMPARE_ROOT/sync-derived"

python scripts/analyze_causal_witness.py \
  --raw results/raw/causal-witness/records.jsonl \
  --out "$COMPARE_ROOT/causal-derived"
python scripts/analyze_causal_robustness.py \
  --raw results/raw/causal-witness/records.jsonl \
  --out "$COMPARE_ROOT/causal-derived"
python scripts/plot_causal_witness.py \
  --cells "$COMPARE_ROOT/causal-derived/cells.csv" \
  --pdf "$COMPARE_ROOT/causal-derived/causal-attribution.pdf" \
  --svg "$COMPARE_ROOT/causal-derived/causal-attribution.svg"

python scripts/analyze_migrations.py \
  --initial-raw results/raw/observed \
  --manifest study/migration-pairs.json \
  --out "$COMPARE_ROOT/migration-derived"
```

On PowerShell, allocate the root with `$COMPARE_ROOT = Join-Path ([IO.Path]::GetTempPath()) ('retryscope-compare-' + [guid]::NewGuid().ToString('N'))` and `New-Item -ItemType Directory -Path $COMPARE_ROOT`. Set `$env:PYTHONPATH = Join-Path (Get-Location).Path 'src'`, and run the same analyzer commands on single lines, without Bash's trailing `\`.

Compare each new `summary.json` with the corresponding retained `results/*-derived/summary.json`. The extension's `offline_median_ms` and causal robustness timing fields are execution-dependent; compare the measured counts and classification invariants separately from fresh analyzer timings. The causal robustness and plotting steps intentionally add distinct files to the newly created causal directory. Reanalysis uses retained observations and does not execute the historical worker or repair missing source provenance.

For candidate paper inputs, use a disposable copy of the whole project outside the retained tree. Select the compared derived directories explicitly and place them at that copy's `artifact/results/*-derived/` paths, then run `python scripts/generate_paper.py --paper-dir ../paper` from the copy's `artifact/`. The generator reads those selected paths and writes that copy's manuscript inputs and `results/paper-data.json`; `--paper-dir` alone does not redirect all writes.

The evaluated-environment, manuscript-dependent self-check must likewise run from `artifact/` in a disposable project copy:

```bash
python scripts/verify_all.py --output "$COMPARE_ROOT/verification.json"
```

This command first requires every principal frozen source declaration to resolve, then checks recorded library versions, regenerates analyses, and writes inputs in a sibling `paper/` directory. With the presently unresolved observed worker it stops at source verification before regeneration. It is not the portable repository CI command. Portable CI runs the current tests, accepts pytest's successful exit status without a historical fixed count, and does not claim to repeat every historical experiment.

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

Check all entries in the observed, extension, asynchronous and synchronous freezes without writing outputs:

```bash
python -B scripts/verify_frozen_sources.py
```

Each entry must match either its current path or the exact preserved bytes identified by `evidence/FROZEN-SOURCE-MAP.json`. A missing or nonmatching source is reported with its declared digest and returns a nonzero exit status.

One component of the observed study remains unrecovered in this distribution: `results/raw/observed/freeze.json` declares `src/retryscope/observed_worker.py` with SHA-256 `49e22d18ac0d1204617bcefe646ad747f2014800f5ed95cf380b01a58c3d22b9`, while the delivered current worker has different bytes and no matching preserved snapshot was found. The other 16 principal freeze entries resolve. Consequently, the exact executed worker for the 1,068-operation observed phase cannot be reconstructed from the retained sources. The recorded observations, outcomes, request counts and freeze digests are preserved; their offline trace/label reanalysis is distinct from byte-exact reconstruction of the instrumentation. This source gap neither establishes a behavioral change nor validates the current worker against the historical run.

The extension and async records identify the exact `src/retryscope/audit.py` bytes used when they were executed. The live checker now includes paired and causal analysis. The executed source is retained unchanged as `evidence/source-snapshots/frozen-extension-audit.py`; `evidence/FROZEN-SOURCE-MAP.json` records its original path and digest. Raw freeze files are not rewritten.

The historical extension analysis uses that retained checker. Applying the current checker, which also requires an explicit policy owner, to the unchanged 402 extension records yields 174 pass and 228 unknown. Older records lack that owner field; it is not backfilled from an outcome or timestamp. The measured download outcomes and request counts are unaffected. New replay instrumentation records the owner at admission time.

## Scope

RetryScope is intended for bounded, safely replayable migration tests with a stated operation contract and trusted client instrumentation. It does not make non-idempotent work safe, provide a whole-service reliability score, infer an application requirement from a library default, or turn a timeout notification into proof that all work has stopped.
