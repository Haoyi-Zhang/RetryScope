"""Client-side retry observation and evidence-complete trace construction.

The helpers in this module do not infer retry cause from adjacent server replies.
They retain events emitted at the retry owner or at the failing stream, then align
those events with the next sequential loopback request.  Alignment is valid only
for the study's single-operation, non-concurrent fixture and is reported as such.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Any, Iterable, Mapping


def exception_cause(exc: BaseException) -> dict[str, Any]:
    """Classify an observed client exception at the narrow level used by the intent."""
    name = type(exc).__name__
    module = type(exc).__module__
    text = f"{module}.{name}".lower()
    body_tokens = (
        "incompleteread", "chunkedencoding", "protocolerror", "responseended",
        "contentdecoding", "remotedisconnected", "responsestreamingerror",
    )
    kind = "body_error" if any(token in text for token in body_tokens) else "transport_error"
    return {"kind": kind, "exception": name, "module": module}


def status_cause(status: Any) -> dict[str, Any] | None:
    if type(status) is int and 100 <= status <= 599:
        return {"kind": "status", "received_status": status}
    return None


@dataclass
class RetryObserver:
    """Append-only client event collector using the process monotonic clock."""

    events: list[dict[str, Any]] = field(default_factory=list)

    def add(self, kind: str, *, source: str, cause: Mapping[str, Any] | None = None, **extra: Any) -> None:
        event: dict[str, Any] = {"t": time.monotonic(), "kind": kind, "source": source}
        if cause is not None:
            event["cause"] = dict(cause)
        event.update(extra)
        self.events.append(event)

    def response(self, status: Any, *, source: str, **extra: Any) -> None:
        cause = status_cause(status)
        if cause is not None:
            self.add("attempt_result", source=source, cause=cause, **extra)

    def error(self, exc: BaseException, *, source: str, **extra: Any) -> None:
        self.add("attempt_result", source=source, cause=exception_cause(exc), **extra)

    def retry_start(self, cause: Mapping[str, Any], *, source: str, **extra: Any) -> None:
        self.add("retry_start", source=source, cause=cause, **extra)


def make_observed_retry(base_cls: type, observer: RetryObserver, *, source: str, **kwargs: Any):
    """Construct a urllib3 Retry subclass that records causes of scheduled retries.

    ``Retry.increment`` is the retry owner's decision point.  We record an event
    only when the base method returns a new Retry object; an exhausted final
    attempt that raises is not labelled as a retry because no subsequent request
    has yet been admitted.
    """

    class ObservedRetry(base_cls):  # type: ignore[misc, valid-type]
        def new(self, **kw: Any):  # noqa: ANN201 - mirrors third-party API
            obj = super().new(**kw)
            obj._retryscope_observer = getattr(self, "_retryscope_observer", observer)
            obj._retryscope_source = getattr(self, "_retryscope_source", source)
            return obj

        def increment(self, method=None, url=None, response=None, error=None, *args: Any, **kw: Any):  # noqa: ANN001, ANN201
            if response is not None:
                cause = status_cause(getattr(response, "status", None)) or {"kind": "unknown"}
            elif error is not None:
                cause = exception_cause(error)
            else:
                cause = {"kind": "unknown"}
            obj = super().increment(method, url, response, error, *args, **kw)
            obs = getattr(self, "_retryscope_observer", observer)
            src = getattr(self, "_retryscope_source", source)
            obs.add("retry_start", source=src, cause=cause, method=method, url=url)
            obj._retryscope_observer = obs
            obj._retryscope_source = src
            return obj

    obj = ObservedRetry(**kwargs)
    obj._retryscope_observer = observer
    obj._retryscope_source = source
    return obj


class ObservedBody:
    """Transparent streaming-body proxy that witnesses read failures."""

    def __init__(self, body: Any, observer: RetryObserver, source: str):
        self._body = body
        self._observer = observer
        self._source = source

    def read(self, *args: Any, **kwargs: Any):  # noqa: ANN201
        try:
            return self._body.read(*args, **kwargs)
        except Exception as exc:
            self._observer.add("body_error", source=self._source, cause=exception_cause(exc))
            raise

    def __enter__(self):
        self._body.__enter__()
        return self

    def __exit__(self, *args: Any):
        return self._body.__exit__(*args)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._body, name)


class ObservedS3Client:
    """Public client-injection wrapper used by smart_open's transport_params."""

    def __init__(self, client: Any, observer: RetryObserver, source: str = "smart_open.body"):
        self._client = client
        self._observer = observer
        self._source = source

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        response = self._client.get_object(**kwargs)
        if "Body" in response:
            response = dict(response)
            response["Body"] = ObservedBody(response["Body"], self._observer, self._source)
        return response

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


def _candidate_events(events: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for event in events:
        cause = event.get("cause")
        if event.get("kind") not in {"retry_start", "attempt_result", "body_error"}:
            continue
        if not isinstance(cause, Mapping):
            continue
        out.append(dict(event))
    return sorted(out, key=lambda row: float(row.get("t", -1)))


def build_trace(record: Mapping[str, Any]) -> dict[str, Any]:
    """Build an audit trace from independently observed client and server facts.

    The matching rule uses the latest witnessed client cause between two
    consecutive arrivals.  It is deliberately limited to this study's one
    sequential operation with no concurrent requests.
    """
    events = record.get("events")
    server_arrivals = []
    if isinstance(events, list):
        server_arrivals = [dict(e) for e in events if isinstance(e, Mapping) and e.get("kind") == "arrival"]
    server_arrivals.sort(key=lambda row: float(row.get("t", -1)))
    client_events = _candidate_events(record.get("client_events", []) if isinstance(record.get("client_events"), list) else [])

    arrivals: list[dict[str, Any]] = []
    complete_attribution = True
    used: set[int] = set()
    for index, event in enumerate(server_arrivals):
        request_id = event.get("index")
        if index == 0:
            arrivals.append({
                "id": request_id,
                "t": event.get("t"),
                "role": "initial",
                "owner": "operation",
                "attribution_witness": "operation entry in a single-operation fixture",
            })
            continue
        previous_t = float(server_arrivals[index - 1].get("t", float("-inf")))
        current_t = float(event.get("t", float("inf")))
        candidates = [
            (i, row) for i, row in enumerate(client_events)
            if i not in used and previous_t <= float(row.get("t", float("-inf"))) <= current_t
        ]
        if candidates:
            # A retry-owner decision is stronger than a stream-failure witness,
            # which in turn is stronger than a generic attempt result.  Time is
            # used only within the same evidence class.  This prevents a later
            # response hook from displacing an explicit retry-admission event.
            rank = {"attempt_result": 1, "body_error": 2, "retry_start": 3}
            i, witness = max(
                candidates,
                key=lambda pair: (rank.get(str(pair[1].get("kind")), 0), float(pair[1].get("t", -1))),
            )
            used.add(i)
            arrivals.append({
                "id": request_id,
                "t": event.get("t"),
                "role": "retry",
                "retry_of": server_arrivals[index - 1].get("index"),
                "owner": witness.get("source"),
                "cause": dict(witness.get("cause", {})),
                "attribution_witness": f"client-side {witness.get('kind')} event",
            })
        else:
            complete_attribution = False
            arrivals.append({"id": request_id, "t": event.get("t"), "role": "unknown"})

    mode = record.get("config", {}).get("mode") if isinstance(record.get("config"), Mapping) else None
    outcome = record.get("outcome")
    trace_complete = record.get("trace_complete") is True
    payload_complete = outcome == "success" and mode != "headers_only" and isinstance(record.get("payload"), str)
    return {
        "schema": 3,
        "arrivals": arrivals,
        "arrival_stream_complete": trace_complete,
        "retry_attribution_complete": trace_complete and complete_attribution,
        "outcome": outcome,
        "payload": record.get("payload"),
        "payload_complete": payload_complete,
        "headers_elapsed_s": record.get("headers_elapsed_s"),
        "headers_complete": record.get("headers_elapsed_s") is not None,
        "body_elapsed_s": record.get("elapsed_s"),
        "body_complete": trace_complete,
        "cleanup_elapsed_s": record.get("elapsed_s"),
        "cleanup_complete": trace_complete,
        "observation_scope": "single sequential loopback operation; client causes aligned to the next arrival",
    }
