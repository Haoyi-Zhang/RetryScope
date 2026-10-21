# RetryScope trace and intent obligations

The audit consumes adapter-supplied JSON facts. It does not infer application
requirements, retry ownership or client-received causes from adjacent server
responses. The CLI validates syntax and basic types; trust in adapter truthfulness
remains outside the checker.

| Intent dimension | Required evidence | Decidable pass condition |
|---|---|---|
| total wire attempts | `arrivals[]`, unique positive ids, `arrival_stream_complete=true` | complete count is at most `max_wire_attempts` |
| terminal outcome | `outcome` in `success,error` | equals `required_outcome` |
| successful payload identity | `outcome`, string `payload`, `payload_complete=true` | on success, exact payload equals `expected_payload`; on error the success-conditional obligation is vacuous |
| retry classification | request `role`, `attribution_witness`, retry link and received `cause`; both completion flags | every retry cause is permitted by the intent |
| completed operation time | `<boundary>_elapsed_s`, `<boundary>_complete=true` | named boundary completes within budget plus tolerance |
| retry admission time | ordered `admissions_s`, `admissions_complete=true` | no later admission exceeds budget plus tolerance |

A witnessed violation has priority over unknown facts elsewhere. Otherwise any
required unknown dimension makes the aggregate unknown. `hard_deadline_guarantee`
is always false: the offline audit reports one finite observed trace.

The intent permissions `allow_body_recovery`, `allow_transport_retry`, and
`allow_integrity_retry` accept only Boolean `true` or `false` (default `false`),
not strings, numbers or null. JSON documents, event arrays and JSONL events all
reject duplicate object keys at every nesting level and non-finite numbers,
including numeric overflow. JSONL parse diagnostics include the physical line.

Classification checks each locally witnessed request independently of inventory
completeness. A retry/recovery requires a unique positive integer identity and
an unambiguous, witnessed parent chain with strictly decreasing integer ids,
ending at an initial/constituent request without a parent. Each retry/recovery
on that chain needs an explicit owner and a mapping-valued received cause.
Malformed unrelated rows add unknown evidence; they cannot erase a provable
violation. Duplicate identities (including rows with conflicting or malformed
owners), missing parents and ambiguous chains never select a first/last record.
The causal join likewise withholds attribution for duplicate client/wire
identities and conflicting ordinals. Count, payload, outcome and time remain
independent dimensions; this does not establish complete inventory or pass.

The paired migration report adds one stable intent fingerprint, before/after
audits, per-dimension transitions, evidence obligations, and a separate structural
delta. It distinguishes evidence loss from regression and stable conformance from
structural equality.
