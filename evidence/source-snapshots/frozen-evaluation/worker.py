"""Execute real libraries against a bounded responder. No library monkeypatches."""
from __future__ import annotations
import argparse
import json
import os
import random
import time
import sys
import signal
import importlib.metadata as md
from pathlib import Path
from typing import Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

# Must be set before SDK import, not just before client construction.
os.environ["AWS_EC2_METADATA_DISABLED"] = "true"
os.environ["AWS_CONFIG_FILE"] = os.devnull
os.environ["AWS_SHARED_CREDENTIALS_FILE"] = os.devnull
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_PROFILE", "AWS_DEFAULT_PROFILE", "AWS_MAX_ATTEMPTS", "AWS_RETRY_MODE", "HF_TOKEN", "HUGGING_FACE_HUB_TOKEN"):
    os.environ.pop(key, None)

from .responder import Responder, Reply
from .checker import Intent, check


def script(name: str, scale: float = 1.0) -> list[Reply]:
    if name == "success": return [Reply()]
    if name == "transient": return [Reply(status=503), Reply()]
    if name == "persistent": return [Reply(status=503)]
    if name == "denied": return [Reply(status=400)]
    if name == "slow_headers": return [Reply(header_delay=0.18 * scale)]
    if name == "trickle": return [Reply(chunk_delay=0.03 * scale)]
    if name == "truncated": return [Reply(truncate=True), Reply()]
    if name == "retry_after": return [Reply(status=503, retry_after="1"), Reply()]
    if name == "metadata": return [Reply(body=b'{"id":"local/model","sha":"abc","siblings":[]}')]
    raise ValueError(name)


def source_versions() -> dict:
    packages = ["boto3", "botocore", "requests", "urllib3", "httpx", "retrying", "smart_open", "huggingface_hub", "pip"]
    return {p: md.version(p) for p in packages}


def boto_client(url: str, config: dict):
    import boto3
    from botocore import UNSIGNED
    from botocore.config import Config
    from botocore import configprovider
    retries = dict(config.get("retries", {}))
    c = boto3.session.Session().client(
        "s3", endpoint_url=url, region_name="us-east-1",
        config=Config(signature_version=UNSIGNED, retries=retries,
                      read_timeout=config.get("read_timeout", 0.08),
                      connect_timeout=0.1, proxies={},
                      s3={"addressing_style": "path"}))
    state = {"effective_retries": c.meta.config.retries,
             "requested_flag": os.environ.get("AWS_NEW_RETRIES_2026"),
             "effective_flag": getattr(configprovider, "NEW_RETRIES_ENABLED", None)}
    return c, state


def execute(config: dict, url: str, start: float) -> dict:
    stack = config["stack"]
    mode = config["mode"]
    budget = config.get("budget", 0.1)
    read_timeout = config.get("read_timeout", 0.08)
    meta: dict = {}
    headers_time: list[float] = []
    if stack in ("boto", "smart_open"):
        if stack == "smart_open":
            import smart_open
        c, state = boto_client(url, config)
        meta.update(state)
        # Client construction is measured separately and excluded from operation latency.
        ready = time.monotonic()
        meta["setup_s"] = ready - start
        meta["operation_start_t"] = ready
        try:
            if stack == "smart_open":
                import smart_open
                with smart_open.open("s3://local-bucket/key", "rb", compression="disable", transport_params={"client": c}) as f:
                    headers_time.append(time.monotonic())
                    content = f.read()
                meta["payload"] = content.decode("ascii")
            else:
                response = c.get_object(Bucket="local-bucket", Key="key")
                headers_time.append(time.monotonic())
                meta["sdk_retry_attempts"] = response.get("ResponseMetadata", {}).get("RetryAttempts")
                with response["Body"] as body:
                    content = body.read() if mode != "headers_only" else b""
                meta["payload"] = content.decode("ascii")
            meta["outcome"] = "success"
        except Exception as exc:
            meta.update(outcome="error", exception=type(exc).__name__, error_message=str(exc)[:250])
        finally:
            c.close()
    elif stack in ("urllib3_old", "urllib3_new"):
        if stack == "urllib3_old":
            from pip._vendor import urllib3 as u
        else:
            import urllib3 as u
        retry = u.util.Retry(total=config.get("retry_total", 2), backoff_factor=config.get("backoff_factor", 0.02),
                             status_forcelist=[503], allowed_methods=["GET"], raise_on_status=False)
        timeout = u.util.Timeout(connect=0.1, read=read_timeout,
                               total=budget if mode == "total_timeout" else None)
        pool = u.PoolManager(retries=retry, timeout=timeout)
        meta.update(library_version=u.__version__, module_path=u.__file__)
        ready = time.monotonic()
        meta.update(setup_s=ready-start, operation_start_t=ready)
        try:
            resp = pool.request("GET", url+"/data", preload_content=False)
            headers_time.append(time.monotonic())
            chunks = []
            try:
                while True:
                    piece = resp.read(4)
                    if not piece: break
                    chunks.append(piece)
            finally:
                resp.close()
            meta.update(payload=b"".join(chunks).decode("ascii"), status=resp.status,
                        outcome="success" if resp.status < 400 else "error")
        except Exception as exc:
            meta.update(outcome="error", exception=type(exc).__name__, error_message=str(exc)[:250])
        finally: pool.clear()
    elif stack in ("requests", "requests_old"):
        if stack == "requests_old":
            from pip._vendor import requests
            from pip._vendor.requests.adapters import HTTPAdapter
            from pip._vendor.urllib3.util import Retry
        else:
            import requests
            from requests.adapters import HTTPAdapter
            from urllib3.util import Retry
        from retrying import Retrying
        meta["request_library_version"] = requests.__version__
        session = requests.Session()
        session.trust_env = False
        inner = config.get("retry_total", 0)
        session.mount("http://", HTTPAdapter(max_retries=Retry(total=inner, status_forcelist=[503],
                         allowed_methods=["GET"], backoff_factor=0.02, raise_on_status=False)))
        session.hooks["response"].append(lambda response, *a, **kw: headers_time.append(time.monotonic()))
        ready = time.monotonic()
        meta.update(setup_s=ready-start, operation_start_t=ready)
        def one():
            r = session.get(url+"/data", timeout=(0.1, read_timeout))
            r.raise_for_status()
            return r.content
        def eligible(exc):
            if mode == "outer_body_aware" and isinstance(exc, requests.exceptions.ChunkedEncodingError):
                return True
            return isinstance(exc, (requests.exceptions.Timeout, requests.exceptions.ConnectionError)) or (
                isinstance(exc, requests.exceptions.HTTPError) and exc.response is not None and exc.response.status_code in (503,))
        try:
            if mode in ("outer_broad", "outer_selective", "outer_body_aware", "stop_delay"):
                retry = Retrying(stop_max_attempt_number=config.get("outer_attempts", 2),
                                 stop_max_delay=round(budget*1000) if mode=="stop_delay" else None,
                                 wait_fixed=config.get("wait_ms", 20),
                                 retry_on_exception=(lambda exc: True) if mode=="outer_broad" else eligible)
                content = retry.call(one)
            elif mode == "admission":
                # Explicitly advisory: checks only between completed attempts.
                deadline = ready + budget
                for n in range(config.get("outer_attempts", 2)):
                    if n and time.monotonic() >= deadline:
                        raise TimeoutError("admission budget exhausted")
                    try:
                        content = one(); break
                    except Exception as exc:
                        if not eligible(exc) or n+1 == config.get("outer_attempts", 2): raise
                        delay = config.get("wait_ms", 20)/1000
                        if time.monotonic()+delay >= deadline:
                            raise TimeoutError("next retry would start outside budget") from exc
                        time.sleep(delay)
            elif mode == "future_timeout":
                # A standard context-managed wrapper. Shutdown really waits; we
                # do not conflate the timeout signal with operation termination.
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(one)
                    try:
                        content = future.result(timeout=budget)
                    except FutureTimeout:
                        meta["timeout_signal_s"] = time.monotonic()-ready
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
        _http.close_session()
        _http.set_client_factory(lambda: httpx.Client(trust_env=False, timeout=read_timeout,
                    event_hooks={"response": [lambda r: headers_time.append(time.monotonic())]}))
        _http.get_session()  # Construct the configured client outside operation timing.
        ready = time.monotonic()
        meta.update(setup_s=ready-start, operation_start_t=ready)
        try:
            if mode == "model_info":
                result = HfApi(endpoint=url, token=False).model_info("local/model", timeout=read_timeout)
                meta["payload"] = result.id
            else:
                resp = _http.http_backoff("GET", url+"/data", max_retries=config.get("retry_total", 2),
                        base_wait_time=0.02, max_wait_time=0.04, timeout=read_timeout)
                resp.raise_for_status()
                meta["payload"] = resp.content.decode("ascii")
            meta["outcome"] = "success"
        except Exception as exc:
            meta.update(outcome="error", exception=type(exc).__name__, error_message=str(exc)[:250])
        finally:
            _http.close_session()
    else:
        raise ValueError(stack)
    finish = time.monotonic()
    meta["operation_end_t"] = finish
    meta["elapsed_s"] = finish-meta["operation_start_t"]
    meta["headers_elapsed_s"] = (headers_time[0]-meta["operation_start_t"]) if headers_time else None
    return meta


class HarnessTimeout(BaseException):
    """Watchdog termination is not a library timeout measurement."""

def _watchdog(signum, frame):
    raise HarnessTimeout("30 second operation watchdog")

def run(config: dict, seed: int, phase: str) -> dict:
    random.seed(seed)
    with Responder(script(config["scenario"], config.get("scale", 1)), s3=config["stack"] in ("boto", "smart_open")) as server:
        record = {"id": config["id"], "config": config, "seed": seed, "phase": phase,
                  "versions": source_versions(), "read_timeout_s": config.get("read_timeout", 0.08)}
        try:
            signal.signal(signal.SIGALRM, _watchdog)
            signal.setitimer(signal.ITIMER_REAL, 30)
            record.update(execute(config, server.url, time.monotonic()))
            signal.setitimer(signal.ITIMER_REAL, 0)
            record["start_t"] = record["operation_start_t"]
            quiet = server.quiesce()
            record["quiescence_s"] = time.monotonic()-record["start_t"]
            record["trace_complete"] = quiet and not server.cap_exceeded
        except (Exception, HarnessTimeout) as exc:
            record.update(harness_error=repr(exc), trace_complete=False)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
        record["events"] = list(server.events)
        record["wire_attempts"] = server.count
        record["cap_exceeded"] = server.cap_exceeded
    intent = Intent(**config.get("intent", {}))
    record["check"] = check(record, intent)
    return record


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--phase", default="pilot")
    p.add_argument("--seeds", default="11")
    p.add_argument("--flag", choices=["true", "false"], default="true")
    p.add_argument("--ids", default="")
    a = p.parse_args()
    os.environ["AWS_NEW_RETRIES_2026"] = a.flag
    configs = json.loads(a.config.read_text())
    if a.ids:
        ids=set(a.ids.split(",")); configs=[c for c in configs if c["id"] in ids]
    configs=[c for c in configs if c.get("flag", "true")==a.flag]
    a.output.parent.mkdir(parents=True, exist_ok=True)
    # Refuse silent overwrite of scientific output.
    with a.output.open("x") as out:
        for seed in map(int, a.seeds.split(",")):
            order=list(configs); random.Random(seed+7919).shuffle(order)
            for config in order:
                record=run(config, seed, a.phase)
                out.write(json.dumps(record, sort_keys=True)+"\n"); out.flush()
                print(f"{a.phase} {seed} {config['id']} n={record['wire_attempts']} {record.get('outcome',record.get('harness_error'))} {record['check']['verdict']} t={record.get('elapsed_s',0):.3f}", flush=True)

if __name__ == "__main__": main()
