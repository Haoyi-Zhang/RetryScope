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

The paired migration report adds one stable intent fingerprint, before/after
audits, per-dimension transitions, evidence obligations, and a separate structural
delta. It distinguishes evidence loss from regression and stable conformance from
structural equality.
