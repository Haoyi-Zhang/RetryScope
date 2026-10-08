# Identity, range-recovery, and constituent-request protocol

The extension contains 67 configurations and six seeded repetitions per configuration:

- seven downloader configurations over seven small response scenarios;
- interrupted and healthy smart_open reads over three caller read sizes and three interruption positions; and
- healthy fsspec reads over three block sizes, with and without explicit object size.

Objects are 96 bytes. Range responses honor actual requested offsets. Pooch's registry supplies a source-backed object-identity requirement. Native Pooch hash validation and retry settings are compared with a deliberately unchecked control and ordinary length-only or SHA-256 validation in the installed Requests paths. SHA-256 plus a narrow retry predicate is an ordinary baseline, not a new algorithm.

For smart_open, public get-object events and ranges support request inventory and payload checks but do not expose the private body-error catch. Retry-cause classification therefore abstains when the client decision is not witnessed. For healthy fsspec reads, request roles are derived from the explicit read plan and source-guided adapter; status adjacency is evaluated only as a deliberately weak baseline.

Record cache state, cleanup, returned payload, payload completeness, wire requests, ranges, client callbacks, and operation time including setup. Errors are not counted as successful recovery. Every operation remains bounded to 16 requests.
