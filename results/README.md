# Result corpus

## Principal raw records

- `raw/native-policy/`: 1,068 retained client-witnessed policy/HTTP/integration operations from the frozen captured generation. Replay that generation explicitly with `scripts/verify_selected_captured.py`; strict live-source verification with `scripts/verify_selected.py` is separate and rejects a source mismatch. Run these scripts from the artifact root.
- `raw/observed/`: separately retained historical policy observations, outside the principal operation total. The adopted migration analysis takes its 54 initial-phase pairs from `raw/native-policy/`, alongside 30 retained extension pairs and 12 retained asynchronous pairs.
- `raw/extension/`: 402 object-identity, range-recovery, and constituent-read operations.
- `raw/async-boundary/`: 144 cooperative async boundary operations.
- `raw/sync-enforcement/`: 96 thread/process boundary operations.
- `raw/causal-witness/`: 720 concurrent logical operations in 192 seeded batches.

Auxiliary retained records in `raw/evaluation`, `raw/sensitivity`, `raw/challenge`, and `raw/import-state` document calibration, parameter checks, baseline challenges, and environment-state probes. They are not added to the paper's 2,430-operation principal total.

`captured-causal-validation/` is a separate Windows execution of the 17 source
files preserved in its `source/` tree: 192 batches, 720 operations and 2,160 wire
requests. Its execution record and reanalysis identify those captured bytes.
The live causal driver later added campaign-parameter validation, so this record
does not certify a rerun of the entire live source tree. It is auxiliary
validation and is not added to the principal operation total.

## Derived reports

- `observed-derived/`
- `native-policy-derived/` (primary policy tables)
- `extension-derived/`
- `async-derived/`
- `sync-derived/`
- `causal-derived/`
- `migration-derived/`
- `paper-data.json`
- `verification.json` after running `scripts/verify_all.py`

Every principal directory contains a machine-readable summary. Raw freeze metadata records the source/configuration identity used for execution. The analyzers verify record coverage, bounded request counts, and stored digests before generating tables or figures.
