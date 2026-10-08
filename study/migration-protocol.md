# Paired migration challenge protocol

`study/migration-pairs.json` declares 16 migration types before paired analysis. Fourteen types (84 seed-matched pairs) cover policy opt-in, attempt-count normalization, nested retry ownership, framing behavior, body recovery, digest enablement, metadata discovery, block-size change, and timeout scope. One reversed pair checks direction; one evidence-removal pair checks observability.

Each pair reuses already executed traces and the same frozen application intent. It is classified from before/after per-dimension audits as repair, regression, stable conformant, stable nonconformant, evidence gain, evidence loss, or inconclusive. Request-count, final-outcome, payload, and duration deltas are reported separately as structural changes.

The expected finite categories are protocol self-consistency checks, not labels from independent human annotators and not an estimate of accuracy over arbitrary dependency upgrades. Outcome-only and count-only summaries are included as common weak signals rather than research competitors.

Reproduce with:

```bash
python scripts/analyze_migrations.py \
  --initial-raw results/raw/observed \
  --manifest study/migration-pairs.json \
  --out results/migration-derived
```
