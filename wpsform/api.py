"""Thin client for the WPS Forms (ksform) HTTP API.

Endpoints used:

    GET  /ksform/api/v3/config                service config, contains encrypt.aes_key
    GET  /ksform/api/v3/campaign/{shareId}    form schema, token, start/stop time
    GET  /ksform/api/v3/time                  authoritative server clock (ms)
    POST /ksform/api/v3/campaign/{shareId}    create one answer

Request/response bodies stay plaintext unless ``encrypt=True``, which mirrors the
web client (``x-encrypt-alg: aes-128-ofb`` + random ``x-encrypt-iv``).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

import requests

from . import crypto

BASE = "https://f-api.wps.cn/ksform/api/v3"
FORM_ORIGIN = "https://f.wps.cn"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


class ApiError(RuntimeError):
    """Transport failure or an unparsable reply."""


@dataclass(slots=True)
class Reply:
    status: int
    code: int | None
    message: str
    data: Any = None

    @property
    def ok(self) -> bool:
        return self.code == 0

    def __str__(self) -> str:
        code = "?" if self.code is None else self.code
        return f"HTTP {self.status} code={code} {self.message}".strip()


class Api:
    def __init__(
        self,
        cookie: str = "",
        *,
        encrypt: bool = False,
        timeout: float = 10.0,
        session: requests.Session | None = None,
    ) -> None:
        self.encrypt = encrypt
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "accept": "application/json, text/plain, */*",
                "accept-language": "zh-CN,zh;q=0.9",
                "content-type": "application/json; charset=UTF-8",
                "origin": FORM_ORIGIN,
                "referer": FORM_ORIGIN + "/",
                "user-agent": USER_AGENT,
            }
        )
        if cookie:
            self.session.cookies.set("wps_sid", cookie, domain=".wps.cn")
        self._aes_key: str | None = None

    # ------------------------------------------------------------ internals --
    def _aes(self) -> str:
        if self._aes_key is None:
            data = self._request("GET", "/config", encrypt=False).data or {}
            self._aes_key = data["encrypt"]["aes_key"]
        return self._aes_key

    def _request(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        *,
        encrypt: bool | None = None,
    ) -> Reply:
        enc = self.encrypt if encrypt is None else encrypt
        headers: dict[str, str] = {}
        kwargs: dict[str, Any] = {"timeout": self.timeout}
        if body is not None:
            if enc:
                ciphertext, iv = crypto.encrypt(json.dumps(body), self._aes())
                headers["x-encrypt-alg"] = "aes-128-ofb"
                headers["x-encrypt-iv"] = iv
                kwargs["data"] = ciphertext
            else:
                kwargs["data"] = json.dumps(body)
        resp = self.session.request(method, BASE + path, headers=headers, **kwargs)
        return self._parse(resp)

    def _parse(self, resp: requests.Response) -> Reply:
        text = resp.text
        iv = resp.headers.get("x-encrypt-iv")
        if iv:
            text = crypto.decrypt(text, iv, self._aes())
        try:
            payload = json.loads(text)
        except ValueError as exc:
            raise ApiError(f"non-JSON reply ({resp.status_code}): {text[:200]}") from exc
        return Reply(
            status=resp.status_code,
            code=payload.get("code"),
            message=str(payload.get("result") or payload.get("message") or ""),
            data=payload.get("data"),
        )

    # ------------------------------------------------------------------ api --
    def config(self) -> dict:
        return self._request("GET", "/config", encrypt=False).data or {}

    def campaign(self, share_id: str) -> dict:
        return self._request("GET", f"/campaign/{share_id}").data or {}

    def server_time_ms(self) -> int:
        reply = self._request("GET", "/time")
        if not reply.data or "time" not in reply.data:
            raise ApiError(f"unexpected /time reply: {reply}")
        return int(reply.data["time"])

    def _time_offset(self) -> int:
        """server_now - local_now, measured with a mid-flight correction."""
        started = int(time.time() * 1000)
        server = self.server_time_ms()
        finished = int(time.time() * 1000)
        return server - (started + finished) // 2

    def sync_clock(self) -> int:
        """Return and cache the server/local offset in milliseconds."""
        samples = [self._time_offset() for _ in range(3)]
        self._offset_ms = sorted(samples)[len(samples) // 2]
        return self._offset_ms

    @property
    def offset_ms(self) -> int:
        return getattr(self, "_offset_ms", 0)

    def server_now(self) -> int:
        return int(time.time() * 1000) + self.offset_ms

    def submit(self, share_id: str, payload: dict) -> Reply:
        return self._request("POST", f"/campaign/{share_id}", payload)