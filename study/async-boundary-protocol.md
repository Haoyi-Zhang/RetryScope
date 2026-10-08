# Asynchronous operation-boundary protocol

Use HTTPX 0.28.1, CPython 3.13.5, the loopback responder, and real clocks. Compare:

1. read-inactivity timeout;
2. a next-attempt admission guard; and
3. `asyncio.timeout` around the cooperative GET/read/retry scope. Client close runs after that timeout context.

The matrix is 3 mechanisms × 4 scenarios × 2 time scales × 6 seeds. Scenarios are healthy response, progressing body, delayed headers, and 503 followed by delayed retry. Client construction occurs before the measured operation. No clock, transport, or retry implementation is patched. Check caller return and client cleanup separately; a timeout exception alone is not evidence that all work stopped.

The retained async cleanup score allows 20 ms beyond the operation budget. A passing local cleanup score does not mean the timeout context enforces arbitrary client-close code outside its scope.
