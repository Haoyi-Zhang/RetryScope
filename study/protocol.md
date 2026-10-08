# Policy, HTTP, and integration study protocol

This protocol defines the bounded local execution used to study effective retry and timeout behavior across layered Python clients. It is a purposive engineering study, not a prevalence survey, human annotation study, or production load test.

## Research boundary

Eligible cases use released Python SDK/HTTP libraries available in the environment, a public document/source/report establishing the mechanism under study, read-only GET/HEAD behavior, no credentials, and a bounded loopback replay. Excluded cases require live cloud services, writes, large downloads, private data, production endpoints, or unverified historical-version claims.

Boto3/botocore 1.43.18 is executed under pre-policy and opted-in 2026 policy states in fresh processes. This is a policy-state comparison within one installed release, not a comparison of two historical wheels. The independent old/new HTTP path uses pip 25.1.1's released vendored urllib3 1.26.20 and standalone urllib3 2.7.0, with path and source hashes retained. smart_open 7.6.1 and huggingface_hub 1.16.1 provide downstream integrations. Requests 2.32.5, HTTPX 0.28.1, and retrying 1.4.2 provide ordinary mechanisms.

## Scenarios and controls

Scenarios include immediate success; transient 503 then success; persistent 503; non-retryable 400; delayed headers; progressively delivered body bytes; one truncated body followed by success; and Retry-After delay. All traffic is loopback-only and capped at 16 requests per operation. Server arrival, body completion, client decision, payload, and operation completion are recorded separately with real monotonic clocks and native sleeps.

Declared intents cover total wire attempts, eligible retry causes, terminal outcome, successful payload identity, and a named time/cleanup boundary. Missing application intent yields observation or unknown, not a defect label. Known documented distinctions are calibration cases. No timing observation is removed as an outlier.

The retained evaluation uses 89 configurations and 12 seeded repetitions per configuration. Repetitions assess execution stability; they are not independent applications or deployments.
