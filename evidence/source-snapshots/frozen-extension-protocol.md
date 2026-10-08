# Additive study, 2026-09-30

This protocol is written before the extension pilot, after inspecting the first
study and the installed Pooch/fsspec/smart_open implementation. It is not a blind
holdout from the earlier discovery process. Pilot: one run/cell. Evaluation: six
seeded orderings of the frozen same cells. Counts are stability repetitions, not
independent deployments or statistical evidence of issue prevalence.

67 cells: seven downloader configurations x seven small read scenarios; twelve
smart_open reads (three API read sizes x three interrupted byte positions plus a
healthy control each); six healthy fsspec reads (three sizes, with/without explicit
file size). All objects are 96 bytes. Range responses implement the requested
actual byte offsets, unlike the original start-of-body-only fixture. Interruption
is one local incomplete response, bounded and not a remote security probe.

Pooch's registry provides a source-backed object-identity requirement. Native
retry_if_failed=0/1 and a deliberately unchecked registry control are compared to
ordinary fully buffered identity-length and SHA-256 checks over the already
installed old/new Requests pairs. A checksum baseline is not a new algorithm.
No claim is made that Pooch promises selective exclusion of HTTP 400: its repeats
are contrasted with a separately stated local 503/body-recovery-only contract.
Record final-cache presence, cleanup, payload, actual wire counts, public callback
observations, and elapsed times including setup (not comparable to v1 hot-call
latencies). Pooch sleeps remain native. No patch of installed client code.

For smart_open, actual public get-object event hooks and ranges are recorded.
They do not directly observe the private body-error catch. Therefore retry-cause
classification abstains; full payload, byte offsets and request inventory remain
observable. For fsspec healthy reads, all requests are attributable to normal
metadata/range operation composition, using source and application boundaries;
this is not a general retry inference algorithm. Status adjacency is evaluated
as a deliberately naive baseline, not as an upstream-library behavior.

Content safety is conditional on successful completion; an error is not recovery.
Report outcomes and identity separately. Any incomplete trace stays incomplete.
Archive pilot failures and any amendments rather than silently replacing them.
Network package retrieval failed (DNS unavailable); exact historical wheels and
a pre-policy Boto3 binary remain unavailable, not filled by synthetic substitutes.
