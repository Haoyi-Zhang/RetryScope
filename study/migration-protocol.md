# Paired migration challenge protocol

`study/migration-pairs.json` declares 16 migration types before paired analysis. Fourteen types (84 seed-matched pairs) cover policy opt-in, attempt-count normalization, nested retry ownership, framing behavior, body recovery, digest enablement, metadata discovery, block-size change, and timeout scope. One reversed pair checks direction; one evidence-removal pair checks observability.

Each pair reuses already executed traces and the same frozen application intent. It is classified from before/after per-dimension audits as repair, regression, stable conformant, stable nonconformant, evidence gain, evidence loss, or inconclusive. Request-count, final-outcome, payload, and duration deltas are reported separately as structural changes.

The expected finite categories are protocol self-consistency checks, not labels from independent human annotators and not an estimate of accuracy over arbitrary dependency upgrades. Outcome-only and count-only summaries are included as common weak signals rather than research competitors.

For the delivered selection, 54 pair observations come from the source-bound
native policy matrix, 30 from the retained extension phase and 12 from the
retained asynchronous phase. These are 96 reused pairs, not 96 new executions.

Run from `artifact/`. First allocate a fresh external `COMPARE_ROOT` as shown in
the README; the analyzer creates its own new output subdirectory. Reanalyze the
delivered selection with:

```bash
python scripts/analyze_migrations.py \
  --initial-raw results/raw/native-policy \
  --manifest study/migration-pairs.json \
  --out "$COMPARE_ROOT/migration-derived"
```

`results/raw/observed` remains a historical input, not the current selected
policy matrix. Do not overwrite the retained `results/migration-derived`.
