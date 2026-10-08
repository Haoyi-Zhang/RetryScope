# Synchronous operation-boundary protocol

Compare two pre-initialized boundaries for a blocking Requests operation:

1. a one-worker `ThreadPoolExecutor` observed through `Future.result(timeout=...)`, executor shutdown, and client close; and
2. a spawned, ready-signalled one-operation process that the parent can terminate and join on budget expiry.

The matrix is 2 mechanisms × 4 scenarios × 2 time scales × 6 seeds. The socket inactivity timeout is deliberately larger than the declared operation budget. Record setup separately, then check healthy-call preservation, timeout signal, completed cleanup, worker liveness, request count, and server quiescence. Process termination is a local isolation result with serialization and resource costs; it is not safe for arbitrary side-effecting work.
