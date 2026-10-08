"""Evidence-complete rerun of the initial RetryScope matrix.

This runner preserves the original operation scenarios but adds client-side
witnesses at retry-owner and stream-failure boundaries.  It intentionally lives
beside the frozen execution worker so archived raw outputs remain reproducible.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
import json
import os
from pathlib import Path
import random
import signal
import time
from typing import Any, Mapping

# Environment must be fixed before SDK import.
os.environ["AWS_EC2_METADATA_DISABLED"] = "true"
os.environ["AWS_CONFIG_FILE"] = os.devnull
os.environ["AWS_SHARED_CREDENTIALS_FILE"] = os.devnull
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
for key in (
    "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
    "AWS_PROFILE", "AWS_DEFAULT_PROFILE", "AWS_MAX_ATTEMPTS", "AWS_RETRY_MODE",
    "HF_TOKEN", "HUGGING_FACE_HUB_TOKEN",
):
    os.environ.pop(key, None)

from .audit import AuditIntent, audit
from .checker import Intent, check
from .observation import (
    ObservedS3Client,
    RetryObserver,
    build_trace,
    exception_cause,
    make_observed_retry,
    status_cause,
)
from .responder import Responder
from .worker import HarnessTimeout, _watchdog, boto_client, script, source_versions


class _ObservedSleepModule:
    """Proxy a module's sleep call at a known retry-owner boundary.

    Both smart_open's reader recovery and Hugging Face Hub's HTTP backoff make
    their retry decision immediately before a module-local ``time.sleep``.
    Replacing only that module global avoids changing the process-wide clock and
    gives the trace an explicit retry-admission witness.
    """

    def __init__(self, base: Any, observer: RetryObserver, source: str):
        self._base = base
        self._observer = observer
        self._source = source

    def sleep(self, seconds: float) -> None:
        cause = None
        for event in reversed(self._observer.events):
            candidate = event.get("cause")
            if isinstance(candidate, Mapping):
                cause = dict(candidate)
                break
        if cause is None:
            cause = {"kind": "unknown"}
        self._observer.retry_start(cause, source=self._source, delay_s=float(seconds))
        self._base.sleep(seconds)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._base, name)


def audit_intent(config: Mapping[str, Any]) -> AuditIntent:
    legacy = Intent(**dict(config.get("intent", {}))).to_dict()
    legacy["expected_payload"] = legacy.pop("expected_payload_on_success")
    if legacy.get("time_scope") == "observation":
        legacy["time_scope"] = "operation"
    return AuditIntent(**legacy)


def _register_botocore_observer(client: Any, observer: RetryObserver) -> None:
    def on_needs_retry(response=None, caught_exception=None, attempts=None, **kwargs: Any) -> None:
        if caught_exception is not None:
            observer.error(caught_exception, source="botocore.needs-retry", attempt=attempts)
            return
        if isinstance(response, tuple) and response:
            http_response = response[0]
            observer.response(getattr(http_response, "status_code", None), source="botocore.needs-retry", attempt=attempts)
    client.meta.events.register("needs-retry.s3.GetObject", on_needs_retry, unique_id=f"retryscope-{id(observer)}")


def _request_exception_cause(exc: BaseException, requests_module: Any) -> dict[str, Any]:
    response = getattr(exc, "response", None)
    if response is not None:
        cause = status_cause(getattr(response, "status_code", None))
        if cause is not None:
            return cause
    return exception_cause(exc)


def execute(config: dict[str, Any], url: str, start: float) -> dict[str, Any]:
    stack = config["stack"]
    mode = config["mode"]
    budget = config.get("budget", 0.1)
    read_timeout = config.get("read_timeout", 0.08)
    observer = RetryObserver()
    meta: dict[str, Any] = {}
    headers_time: list[float] = []

    if stack in ("boto", "smart_open"):
        if stack == "smart_open":
            import smart_open
            import smart_open.s3
        client, state = boto_client(url, config)
        _register_botocore_observer(client, observer)
        meta.update(state)
        ready = time.monotonic()
        meta.update(setup_s=ready - start, operation_start_t=ready)
        try:
            if stack == "smart_open":
                observed_client = ObservedS3Client(client, observer)
                original_smart_time = smart_open.s3.time
                smart_open.s3.time = _ObservedSleepModule(
                    original_smart_time, observer, "smart_open.reader-recovery"
                )
                try:
                    with smart_open.open(
                        "s3://local-bucket/key", "rb", compression="disable",
                        transport_params={"client": observed_client},
                    ) as stream:
                        headers_time.append(time.monotonic())
                        content = stream.read()
                finally:
                    smart_open.s3.time = original_smart_time
                meta["payload"] = content.decode("ascii")
            else:
                response = client.get_object(Bucket="local-bucket", Key="key")
                headers_time.append(time.monotonic())
                meta["sdk_retry_attempts"] = response.get("ResponseMetadata", {}).get("RetryAttempts")
                body = response["Body"]
                try:
                    content = body.read() if mode != "headers_only" else b""
                except Exception as exc:
                    observer.add("body_error", source="botocore.streaming-body", cause=exception_cause(exc))
                    raise
                finally:
                    body.close()
                meta["payload"] = content.decode("ascii")
            meta["outcome"] = "success"
        except Exception as exc:
            meta.update(outcome="error", exception=type(exc).__name__, error_message=str(exc)[:250])
        finally:
            client.close()

    elif stack in ("urllib3_old", "urllib3_new"):
        if stack == "urllib3_old":
            from pip._vendor import urllib3 as urllib3_module
        else:
            import urllib3 as urllib3_module
        retry = make_observed_retry(
            urllib3_module.util.Retry,
            observer,
            source=f"{stack}.Retry.increment",
            total=config.get("retry_total", 2),
            backoff_factor=config.get("backoff_factor", 0.02),
            status_forcelist=[503],
            allowed_methods=["GET"],
            raise_on_status=False,
        )
        timeout = urllib3_module.util.Timeout(
            connect=0.1,
            read=read_timeout,
            total=budget if mode == "total_timeout" else None,
        )
        pool = urllib3_module.PoolManager(retries=retry, timeout=timeout)
        meta.update(library_version=urllib3_module.__version__, module_path=urllib3_module.__file__)
        ready = time.monotonic()
        meta.update(setup_s=ready - start, operation_start_t=ready)
        try:
            response = pool.request("GET", url + "/data", preload_content=False)
            headers_time.append(time.monotonic())
            chunks: list[bytes] = []
            try:
                while True:
                    piece = response.read(4)
                    if not piece:
                        break
                    chunks.append(piece)
            except Exception as exc:
                observer.add("body_error", source=f"{stack}.response.read", cause=exception_cause(exc))
                raise
            finally:
                response.close()
            meta.update(
                payload=b"".join(chunks).decode("ascii"),
                status=response.status,
                outcome="success" if response.status < 400 else "error",
            )
        except Exception as exc:
            meta.update(outcome="error", exception=type(exc).__name__, error_message=str(exc)[:250])
        finally:
            pool.clear()

    elif stack in ("requests", "requests_old"):
        if stack == "requests_old":
            from pip._vendor import requests as requests_module
            from pip._vendor.requests.adapters import HTTPAdapter
            from pip._vendor.urllib3.util import Retry as RetryClass
        else:
            import requests as requests_module
            from requests.adapters import HTTPAdapter
            from urllib3.util import Retry as RetryClass
        from retrying import Retrying

        meta["request_library_version"] = requests_module.__version__
        session = requests_module.Session()
        session.trust_env = False
        inner = config.get("retry_total", 0)
        inner_retry = make_observed_retry(
            RetryClass,
            observer,
            source=f"{stack}.HTTPAdapter.Retry",
            total=inner,
            status_forcelist=[503],
            allowed_methods=["GET"],
            backoff_factor=0.02,
            raise_on_status=False,
        )
        session.mount("http://", HTTPAdapter(max_retries=inner_retry))

        def response_hook(response, *args: Any, **kwargs: Any) -> None:
            headers_time.append(time.monotonic())
            observer.response(response.status_code, source=f"{stack}.response-hook")

        session.hooks["response"].append(response_hook)
        ready = time.monotonic()
        meta.update(setup_s=ready - start, operation_start_t=ready)

        def one() -> bytes:
            response = session.get(url + "/data", timeout=(0.1, read_timeout))
            response.raise_for_status()
            return response.content

        pending_outer: dict[str, Any] | None = None

        def eligible(exc: BaseException) -> bool:
            nonlocal pending_outer
            pending_outer = _request_exception_cause(exc, requests_module)
            if mode == "outer_body_aware" and isinstance(exc, requests_module.exceptions.ChunkedEncodingError):
                return True
            return isinstance(exc, (requests_module.exceptions.Timeout, requests_module.exceptions.ConnectionError)) or (
                isinstance(exc, requests_module.exceptions.HTTPError)
                and getattr(exc, "response", None) is not None
                and exc.response.status_code in (503,)
            )

        def before_attempt(attempt_number: int) -> None:
            nonlocal pending_outer
            if attempt_number > 1 and pending_outer is not None:
                observer.retry_start(pending_outer, source=f"retrying.{mode}", outer_attempt=attempt_number)
                pending_outer = None

        try:
            if mode in ("outer_broad", "outer_selective", "outer_body_aware", "stop_delay"):
                def broad(exc: BaseException) -> bool:
                    nonlocal pending_outer
                    pending_outer = _request_exception_cause(exc, requests_module)
                    return True
                retry = Retrying(
                    stop_max_attempt_number=config.get("outer_attempts", 2),
                    stop_max_delay=round(budget * 1000) if mode == "stop_delay" else None,
                    wait_fixed=config.get("wait_ms", 20),
                    retry_on_exception=broad if mode == "outer_broad" else eligible,
                    before_attempts=before_attempt,
                )
                content = retry.call(one)
            elif mode == "admission":
                deadline = ready + budget
                pending: dict[str, Any] | None = None
                for attempt in range(config.get("outer_attempts", 2)):
                    if attempt:
                        if pending is not None:
                            observer.retry_start(pending, source="requests.admission", outer_attempt=attempt + 1)
                            pending = None
                        if time.monotonic() >= deadline:
                            raise TimeoutError("admission budget exhausted")
                    try:
                        content = one()
                        break
                    except Exception as exc:
                        pending = _request_exception_cause(exc, requests_module)
                        if not eligible(exc) or attempt + 1 == config.get("outer_attempts", 2):
                            raise
                        delay = config.get("wait_ms", 20) / 1000
                        if time.monotonic() + delay >= deadline:
                            raise TimeoutError("next retry would start outside budget") from exc
                        time.sleep(delay)
            elif mode == "future_timeout":
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(one)
                    try:
                        content = future.result(timeout=budget)
                    except FutureTimeout:
                        meta["timeout_signal_s"] = time.monotonic() - ready
                        meta["cancel_return"] = future.cancel()
                        raise
            else:
                content = one()
            meta.update(payload=content.decode("ascii"), outcome="success")
        except Exception as exc:
            meta.update(outcome="error", exception=type(exc).__name__, error_message=str(exc)[:250])
        finally:
            session.close()

    elif stack == "huggingface":
        import httpx
        from huggingface_hub import HfApi
        from huggingface_hub.utils import _http

        class ObservedClient(httpx.Client):
            def request(self, *args: Any, **kwargs: Any):  # noqa: ANN201
                try:
                    response = super().request(*args, **kwargs)
                    observer.response(response.status_code, source="huggingface.httpx-client")
                    return response
                except Exception as exc:
                    observer.error(exc, source="huggingface.httpx-client")
                    raise

        _http.close_session()
        _http.set_client_factory(
            lambda: ObservedClient(
                trust_env=False,
                timeout=read_timeout,
                event_hooks={"response": [lambda response: headers_time.append(time.monotonic())]},
            )
        )
        _http.get_session()
        original_http_time = _http.time
        _http.time = _ObservedSleepModule(
            original_http_time, observer, "huggingface.http_backoff"
        )
        ready = time.monotonic()
        meta.update(setup_s=ready - start, operation_start_t=ready)
        try:
            if mode == "model_info":
                result = HfApi(endpoint=url, token=False).model_info("local/model", timeout=read_timeout)
                meta["payload"] = result.id
            else:
                response = _http.http_backoff(
                    "GET", url + "/data",
                    max_retries=config.get("retry_total", 2),
                    base_wait_time=0.02,
                    max_wait_time=0.04,
                    timeout=read_timeout,
                )
                response.raise_for_status()
                meta["payload"] = response.content.decode("ascii")
            meta["outcome"] = "success"
        except Exception as exc:
            meta.update(outcome="error", exception=type(exc).__name__, error_message=str(exc)[:250])
        finally:
            _http.time = original_http_time
            _http.close_session()
    else:
        raise ValueError(stack)

    finish = time.monotonic()
    meta["operation_end_t"] = finish
    meta["elapsed_s"] = finish - meta["operation_start_t"]
    meta["headers_elapsed_s"] = (headers_time[0] - meta["operation_start_t"]) if headers_time else None
    meta["client_events"] = observer.events
    return meta


def run(config: dict[str, Any], seed: int, phase: str) -> dict[str, Any]:
    random.seed(seed)
    with Responder(script(config["scenario"], config.get("scale", 1)), s3=config["stack"] in ("boto", "smart_open")) as server:
        record: dict[str, Any] = {
            "id": config["id"], "config": config, "seed": seed, "phase": phase,
            "versions": source_versions(), "read_timeout_s": config.get("read_timeout", 0.08),
        }
        try:
            signal.signal(signal.SIGALRM, _watchdog)
            signal.setitimer(signal.ITIMER_REAL, 30)
            record.update(execute(config, server.url, time.monotonic()))
            signal.setitimer(signal.ITIMER_REAL, 0)
            record["start_t"] = record["operation_start_t"]
            quiet = server.quiesce()
            record["quiescence_s"] = time.monotonic() - record["start_t"]
            record["trace_complete"] = quiet and not server.cap_exceeded
        except (Exception, HarnessTimeout) as exc:
            record.update(harness_error=repr(exc), trace_complete=False)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
        record["events"] = list(server.events)
        record["wire_attempts"] = server.count
        record["cap_exceeded"] = server.cap_exceeded
    record["legacy_check"] = check(record, Intent(**config.get("intent", {})))
    trace = build_trace(record)
    record["audit_trace"] = trace
    record["audit"] = audit(trace, audit_intent(config))
    return record


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--phase", default="observed-pilot")
    parser.add_argument("--seeds", default="11")
    parser.add_argument("--flag", choices=["true", "false"], default="true")
    parser.add_argument("--ids", default="")
    args = parser.parse_args()
    os.environ["AWS_NEW_RETRIES_2026"] = args.flag
    configs = json.loads(args.config.read_text())
    if args.ids:
        selected = set(args.ids.split(","))
        configs = [config for config in configs if config["id"] in selected]
    configs = [config for config in configs if config.get("flag", "true") == args.flag]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as output:
        for seed in map(int, args.seeds.split(",")):
            order = list(configs)
            random.Random(seed + 7919).shuffle(order)
            for config in order:
                record = run(config, seed, args.phase)
                output.write(json.dumps(record, sort_keys=True) + "\n")
                output.flush()
                print(
                    f"{args.phase} {seed} {config['id']} n={record['wire_attempts']} "
                    f"{record.get('outcome', record.get('harness_error'))} {record['audit']['verdict']} "
                    f"t={record.get('elapsed_s', 0):.3f}",
                    flush=True,
                )


if __name__ == "__main__":
    main()
