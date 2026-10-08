# Synchronous operation-boundary enforcement protocol

Declared after the client-evidence rerun and before executing this extension.
The purpose is to challenge the common `Future.result(timeout=...)` wrapper with
an ordinary isolation baseline for a blocking synchronous HTTP operation.  It is
not a new cancellation primitive and is not presented as a production benchmark.

Use CPython's multiprocessing process boundary and Requests against the unchanged
loopback responder.  Compare two pre-initialized mechanisms:

1. `thread_future`: a one-worker ThreadPoolExecutor.  Record the timeout signal,
   then measure through executor shutdown and client close.  A signalled future
   is not considered cleaned up while the worker continues.
2. `process_watchdog`: a spawned, ready-signalled one-operation worker process.
   Start the measured boundary only after imports and client construction.  On
   budget expiry, terminate the worker and join it; measure through process exit.

Matrix: 2 mechanisms x 4 scenarios (healthy response, progressing body, delayed
headers, 503 followed by a delayed application retry) x 2 scales (1 and 1.5) x
6 repetitions, seeds 701..706.  Budgets are 250ms x scale, body chunks arrive
60ms x scale apart, header delay is 300ms x scale and retry delay is 450ms x scale.  The Requests
socket inactivity timeout is deliberately larger than the operation budget so
it does not supply the tested total boundary.  All traffic is loopback-only and
capped at 16 requests per operation.

Report setup separately from the measured operation.  Check healthy-call
preservation, timeout signal, completed cleanup, child/thread liveness, wire
requests, and server quiescence.  Process termination is a Linux/CPython
isolation result with serialization and resource costs; it is not a hard
real-time guarantee, a recommendation for every call, or evidence about live
DNS, TLS, side effects, Windows process startup, or production throughput.
