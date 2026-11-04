"""AES-128-OFB helpers, byte-compatible with the WPS Forms web client.

The client only encrypts when the request carries ``x-encrypt-alg``; the key is
served in plain text by ``/ksform/api/v3/config`` as ``data.encrypt.aes_key``
(base64, 16 bytes).  The response is encrypted with a fresh IV returned in the
``x-encrypt-iv`` header.
"""

from __future__ import annotations

import base64
import os

try:  # pycryptodome is optional: plaintext mode does not need it
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad, unpad
except ImportError:  # pragma: no cover - exercised only on missing dependency
    AES = None


class CryptoUnavailable(RuntimeError):
    """pycryptodome is not installed."""


def _require_crypto() -> None:
    if AES is None:
        raise CryptoUnavailable("encryption requires pycryptodome: pip install pycryptodome")


def _key(raw_key_b64: str) -> bytes:
    key = base64.b64decode(raw_key_b64)
    if len(key) not in (16, 24, 32):
        raise ValueError(f"unexpected AES key length: {len(key)} bytes")
    return key


def encrypt(text: str, raw_key_b64: str) -> tuple[str, str]:
    """Return (base64 ciphertext, base64 iv)."""
    _require_crypto()
    iv = os.urandom(16)
    cipher = AES.new(_key(raw_key_b64), AES.MODE_OFB, iv)
    blob = cipher.encrypt(pad(text.encode(), AES.block_size))
    return (
        base64.b64encode(blob).decode(),
        base64.b64encode(iv).decode(),
    )


def decrypt(ciphertext_b64: str, iv_b64: str, raw_key_b64: str) -> str:
    _require_crypto()
    cipher = AES.new(_key(raw_key_b64), AES.MODE_OFB, base64.b64decode(iv_b64))
    plain = cipher.decrypt(base64.b64decode(ciphertext_b64))
    try:
        plain = unpad(plain, AES.block_size)
    except ValueError:
        pass  # OFB output is not always padded by the server
    return plain.decode("utf-8", errors="replace")