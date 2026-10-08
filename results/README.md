# Result corpus

## Principal raw records

- `raw/observed/`: 1,068 client-witnessed policy/HTTP/integration operations.
- `raw/extension/`: 402 object-identity, range-recovery, and constituent-read operations.
- `raw/async-boundary/`: 144 cooperative async boundary operations.
- `raw/sync-enforcement/`: 96 thread/process boundary operations.
- `raw/causal-witness/`: 720 concurrent logical operations in 192 seeded batches.

Auxiliary retained records in `raw/evaluation`, `raw/sensitivity`, `raw/challenge`, and `raw/import-state` document calibration, parameter checks, baseline challenges, and environment-state probes. They are not added to the paper's 2,430-operation principal total.

## Derived reports

- `observed-derived/`
- `extension-derived/`
- `async-derived/`
- `sync-derived/`
- `causal-derived/`
- `migration-derived/`
- `paper-data.json`
- `verification.json` after running `scripts/verify_all.py`

Every principal directory contains a machine-readable summary. Raw freeze metadata records the source/configuration identity used for execution. The analyzers verify record coverage, bounded request counts, and stored digests before generating tables or figures.
