"""Server-clock alignment and the submit-until-accepted loop."""

from __future__ import annotations

import threading
import time
from typing import Callable

from .answers import build_payload
from .api import Api, Reply
from .schema import Form

SUCCESS = 0
NOT_STARTED = 13018

FATAL = {
    10002: "login required - export wps_sid from a browser into WPS_SID",
    13015: "form closed, or this account already answered",
    11001: "quota exhausted / submission rejected",
}

Log = Callable[[str], None]


def wait_until(api: Api, target_ms: int, log: Log = print) -> None:
    """Block until the *server* clock reaches ``target_ms``."""
    offset = api.sync_clock()
    delta = target_ms - api.server_now()
    if delta <= 0:
        log(f"server clock offset {offset / 1000:+.3f}s, target already reached")
        return
    log(f"server clock offset {offset / 1000:+.3f}s, target in {delta / 1000:.2f}s")
    target_local = target_ms - offset
    while True:
        left = target_local - int(time.time() * 1000)
        if left <= 120:
            return
        time.sleep(min(left / 1000 - 0.1, 30.0))


def attempt_once(api: Api, form: Form, values: dict, started: float) -> Reply:
    payload = build_payload(form, values, consume_time=int(time.time() - started) or 1)
    return api.submit(form.share_id, payload)


def run(
    api: Api,
    form: Form,
    values: dict,
    *,
    workers: int = 1,
    gap: float = 0.10,
    not_started_gap: float = 0.05,
    max_attempts: int = 0,
    log: Log = print,
) -> Reply | None:
    """Submit until success, a fatal code, or ``max_attempts`` (0 = unlimited)."""
    started = time.time()
    stop = threading.Event()
    result: list[Reply] = []
    attempts = 0
    lock = threading.Lock()

    def worker() -> None:
        nonlocal attempts
        while not stop.is_set():
            with lock:
                if max_attempts and attempts >= max_attempts:
                    stop.set()
                    return
                attempts += 1
                index = attempts
            t0 = time.time()
            try:
                reply = attempt_once(api, form, values, started)
            except Exception as exc:  # noqa: BLE001 - keep the loop alive on transport errors
                log(f"[{index}] request failed: {exc}")
                stop.wait(gap if not stop.is_set() else 0)
                continue
            cost = (time.time() - t0) * 1000
            log(f"[{index}] {reply} ({cost:.0f} ms)")

            if reply.code == SUCCESS:
                result.append(reply)
                stop.set()
                return
            if reply.code in FATAL:
                log(f"stop: {FATAL[reply.code]}")
                stop.set()
                return
            stop.wait(not_started_gap if reply.code == NOT_STARTED else gap)

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(max(1, workers))]
    for thread in threads:
        thread.start()
    try:
        for thread in threads:
            while thread.is_alive():
                thread.join(0.2)
    except KeyboardInterrupt:
        stop.set()
        raise

    if not result:
        return None
    return result[0]