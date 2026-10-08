# Supported timeout boundary comparison

Declared after the v1 timing findings and before this extension's execution. This
is a new ordinary-baseline challenge, not a holdout or a new cancellation method.
Use installed HTTPX 0.28.1, CPython 3.13.5, the unchanged loopback responder and real
clocks. Compare inactivity-only, a pre-sleep admission guard, and the documented
asyncio.timeout context around one sequential GET/read/retry operation. HTTPX
client construction is outside the operation; measured cleanup ends after its
context exits. No network phase is patched and no detached task is used.

Matrix: 3 modes x 4 scenarios (healthy, progressing body, delayed headers,
503 followed by a delayed retry) x 2 scales (1 and 1.5), six repetitions with
seeds 601..606. Budget 100ms x scale, read inactivity 80ms x scale, ten body bytes
30ms x scale apart, header/retry delay 180ms x scale. Inner retries disabled,
outer cap 2, server cap 16. No live DNS, TLS, pool-contention or blocking callback
experiment. Report every duration and complete/partial payload. A successful
local timeout observation is not a universal real-time bound. Check caller return
and cleanup separately; server handler cleanup is a different resource boundary.
