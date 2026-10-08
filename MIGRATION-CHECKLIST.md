# Client-witnessed retry and timeout migration checklist

1. **Name the complete application operation.** State whether it ends at
   headers, a complete validated body, or completed cleanup. Keep next-attempt
   admission separate from an operation deadline.
2. **Freeze one intent for both sides.** Record the source of each requirement:
   public contract, application test, registered digest, or explicit local
   release rule. Leave unspecified dimensions unspecified.
3. **Pin the effective runtime state.** Record runtime, package/vendoring,
   import-time flags, retry mode, and policy state. A toggle in one binary is
   not a binary upgrade.
4. **Instrument the layer that owns the decision.** Record client retry events
   at the SDK/HTTP/wrapper hook, then align them with later wire arrivals.
   Server response plans and request adjacency are not cause witnesses.
5. **Declare evidence obligations before deciding.** Count requires a complete
   request inventory; classification needs owner and cause; identity needs a
   complete returned-object witness; time needs a named completion boundary.
6. **Audit before and after independently.** Missing evidence is `unknown`, not
   pass. A witnessed wrong digest or over-cap prefix remains a mismatch even if
   another dimension is incomplete.
7. **Classify the transition.** Distinguish repair, regression, stable
   conformant, stable nonconformant, evidence gain/loss, and inconclusive.
   Preserve per-dimension transitions.
8. **Report structural change separately.** Request count, terminal outcome,
   elapsed time, and payload digest can change without changing conformance.
   Healthy HEAD/range constituents are not retries merely because they are
   adjacent.
9. **Challenge the oracle.** Include normal success, eligible transient
   recovery, persistent failure, non-retryable response, truncation,
   same-length corruption, healthy ranged reads, progressing bodies, delayed
   headers, and retry delay.
10. **Prefer the smallest supported intervention.** Use a documented total-
    attempt option, one retry owner, complete-body/digest validation, a narrow
    retry predicate, or a cooperative timeout context before proposing a new
    algorithm.
11. **Separate safe failure from recovery.** Correct success, wrong success,
    and terminal error are distinct. Payload safety on error is vacuous; every
    additional request has observable cost.
12. **Measure the boundary actually promised.** Record timeout notification,
    operation exit, and client cleanup separately. A running thread Future is
    not cancelled by notification. A process boundary can enforce a local
    read-only fixture but adds startup cost and can be unsafe around shared
    mutable state, IPC, child processes, or external side effects.
13. **Retain the release decision.** Keep the unchanged intent, both traces,
    client events, evidence report, transition category, structural delta,
    unavailable cases, and exact configuration/code change. RetryScope does not
    file upstream issues or issue a deployment verdict automatically.
