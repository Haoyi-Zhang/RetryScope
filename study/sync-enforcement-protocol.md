# Synchronous operation-boundary protocol

Compare two pre-initialized boundaries for a blocking Requests operation:

1. a one-worker `ThreadPoolExecutor` observed through `Future.result(timeout=...)`, executor shutdown, and client close; and
2. a spawned, ready-signalled one-operation process that the parent can terminate and join on budget expiry.

The matrix is 2 mechanisms × 4 scenarios × 2 time scales × 6 seeds. The socket inactivity timeout is deliberately larger than the declared operation budget. Record setup separately, then check healthy-call preservation, timeout signal, completed cleanup, worker liveness, request count, and server quiescence. Process termination is a local isolation result with serialization and resource costs; it is not safe for arbitrary side-effecting work.

The synchronous cleanup criterion allows 40 ms beyond the budget, unlike the async study's 20 ms. On the retained 48 records per mechanism, process cleanup passes 48/48 with 40 ms and 47/48 with 20 ms; thread cleanup passes 12/48 under either threshold. This is sensitivity analysis of the same records, not a new run.
