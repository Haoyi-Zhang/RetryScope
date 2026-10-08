# Concurrent causal-attribution protocol

## Question

Can client-generated operation/attempt identities preserve retry ownership and parent edges when logical operations, nested policies, constituent reads, and body recovery interleave?

## Matrix

Execute two real HTTP stacks (Requests/urllib3 and HTTPX), four operation structures, four concurrency levels (1, 2, 4, 8), and six seeds. The four structures are:

- one initial request followed by retry;
- nested retry ownership;
- planned constituent requests; and
- partial-body recovery.

This yields 192 seeded batches, 720 logical operations, and 2,160 bounded wire attempts. Each logical operation uses an append-only client admission ledger and an independently recorded responder arrival stream.

## Comparisons

- exact causal join on validated `(operation_id, attempt_id)`;
- the sequential time-window rule that assigns the latest eligible client event before an arrival; and
- adjacency, which labels every request after the first as a retry.

Measure exact attempt assignment, role accuracy, owner accuracy, and parent-edge precision/recall/F1. Audit each token-joined operation against its declared intent.

## Fail-closed mutations and cost

For 60 sampled traces per mutation class, delete a wire arrival, duplicate a wire arrival, invalidate witness headers, remove a parent admission, create a non-causal parent, or substitute an unknown attempt. A malformed trace passes only if the join incorrectly reports complete evidence; otherwise it is detected. Separately measure join time, serialized admission bytes, and witness-header bytes. These are local analysis/encoding costs, not production throughput measurements.
