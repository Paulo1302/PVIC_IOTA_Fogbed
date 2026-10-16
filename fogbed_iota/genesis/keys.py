"""Key helpers: bech32 ``iotaprivkey`` encoding, Ed25519 public keys and anemo Peer IDs.

Pure Python (no third-party dependency). In IOTA v1.33.1:
  * validator.yaml stores Ed25519 keys as ``iotaprivkey1...`` (bech32, data = flag || seed,
    flag 0x00 = Ed25519) under ``<key>: {value: ...}``;
  * the genesis config (``iota-localnet genesis --write-config``) stores the same keys as
    base64 (protocol/network: 32-byte seed; account: flag || seed; authority: BLS12-381 scalar);
  * an anemo ``PeerId`` is the lower-case hex of the validator's Ed25519 *network* public key
    (``p2p-config.seed-peers[].peer-id``).
All derivations are cross-checked against the official builder output in builder.py.
"""

from __future__ import annotations

import base64
import hashlib
import os
from typing import List, Optional

from .errors import CommitteeError

IOTA_PRIVKEY_HRP = "iotaprivkey"
ED25519_FLAG = 0x00

# ---------------------------------------------------------------------------
# bech32 (BIP-173)
# ---------------------------------------------------------------------------
_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def _polymod(values: List[int]) -> int:
    generator = [0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3]
    chk = 1
    for value in values:
        top = chk >> 25
        chk = (chk & 0x1FFFFFF) << 5 ^ value
        for i in range(5):
            chk ^= generator[i] if ((top >> i) & 1) else 0
    return chk


def _hrp_expand(hrp: str) -> List[int]:
    return [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp]


def _convertbits(data: bytes, frombits: int, tobits: int, pad: bool) -> List[int]:
    acc, bits, ret = 0, 0, []
    maxv = (1 << tobits) - 1
    for value in data:
        acc = (acc << frombits) | value
        bits += frombits
        while bits >= tobits:
            bits -= tobits
            ret.append((acc >> bits) & maxv)
    if pad and bits:
        ret.append((acc << (tobits - bits)) & maxv)
    elif not pad and (bits >= frombits or ((acc << (tobits - bits)) & maxv)):
        raise CommitteeError("invalid bech32 padding")
    return ret


def bech32_encode(hrp: str, data: bytes) -> str:
    values = _convertbits(data, 8, 5, True)
    checksum = _polymod(_hrp_expand(hrp) + values + [0] * 6) ^ 1
    checksum_values = [(checksum >> 5 * (5 - i)) & 31 for i in range(6)]
    return hrp + "1" + "".join(_CHARSET[v] for v in values + checksum_values)


def bech32_decode(text: str) -> "tuple[str, bytes]":
    pos = text.rfind("1")
    if pos < 1 or pos + 7 > len(text):
        raise CommitteeError(f"invalid bech32 string: {text[:16]}...")
    hrp, payload = text[:pos], text[pos + 1:]
    try:
        values = [_CHARSET.index(c) for c in payload]
    except ValueError as exc:
        raise CommitteeError("invalid bech32 character") from exc
    if _polymod(_hrp_expand(hrp) + values) != 1:
        raise CommitteeError("bech32 checksum mismatch")
    return hrp, bytes(_convertbits(bytes(values[:-6]), 5, 8, False))


def iota_privkey_from_seed(seed: bytes, flag: int = ED25519_FLAG) -> str:
    if len(seed) != 32:
        raise CommitteeError(f"Ed25519 seed must be 32 bytes, got {len(seed)}")
    return bech32_encode(IOTA_PRIVKEY_HRP, bytes([flag]) + seed)


def seed_from_iota_privkey(value: str) -> bytes:
    hrp, data = bech32_decode(value)
    if hrp != IOTA_PRIVKEY_HRP or len(data) != 33 or data[0] != ED25519_FLAG:
        raise CommitteeError("not an Ed25519 iotaprivkey")
    return data[1:]


# ---------------------------------------------------------------------------
# Ed25519 public key (RFC 8032, reference implementation, public domain)
# ---------------------------------------------------------------------------
_P = 2**255 - 19
_Q = 2**252 + 27742317777372353535851937790883648493
_D = -121665 * pow(121666, _P - 2, _P) % _P
_SQRT_M1 = pow(2, (_P - 1) // 4, _P)


def _recover_x(y: int, sign: int) -> int:
    x2 = (y * y - 1) * pow(_D * y * y + 1, _P - 2, _P) % _P
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P != 0:
        x = x * _SQRT_M1 % _P
    if (x * x - x2) % _P != 0:
        raise ValueError("invalid point")
    if x & 1 != sign:
        x = _P - x
    return x


def _point_add(a, b):
    big_a = (a[1] - a[0]) * (b[1] - b[0]) % _P
    big_b = (a[1] + a[0]) * (b[1] + b[0]) % _P
    big_c = 2 * a[3] * b[3] * _D % _P
    big_d = 2 * a[2] * b[2] % _P
    e, f, g, h = big_b - big_a, big_d - big_c, big_d + big_c, big_b + big_a
    return (e * f % _P, g * h % _P, f * g % _P, e * h % _P)


def _point_mul(scalar: int, point):
    result = (0, 1, 1, 0)
    while scalar > 0:
        if scalar & 1:
            result = _point_add(result, point)
        point = _point_add(point, point)
        scalar >>= 1
    return result


_GY = 4 * pow(5, _P - 2, _P) % _P
_GX = _recover_x(_GY, 0)
_G = (_GX, _GY, 1, _GX * _GY % _P)


def ed25519_public_key(seed: bytes) -> bytes:
    """Public key for a 32-byte Ed25519 seed (RFC 8032 section 5.1.5)."""
    if len(seed) != 32:
        raise CommitteeError(f"Ed25519 seed must be 32 bytes, got {len(seed)}")
    h = hashlib.sha512(seed).digest()
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    point = _point_mul(a, _G)
    zinv = pow(point[2], _P - 2, _P)
    x, y = point[0] * zinv % _P, point[1] * zinv % _P
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")


def peer_id_from_network_seed(seed: bytes) -> str:
    """anemo PeerId (hex of the Ed25519 network public key) for a network key seed."""
    return ed25519_public_key(seed).hex()


def new_seed(rng: Optional[object] = None) -> bytes:
    return os.urandom(32)


def b64_seed(value: str, expected_len: int = 32, label: str = "key") -> bytes:
    try:
        raw = base64.b64decode(value, validate=True)
    except Exception as exc:
        raise CommitteeError(f"{label} is not valid base64") from exc
    if len(raw) != expected_len:
        raise CommitteeError(f"{label}: expected {expected_len} bytes, got {len(raw)}")
    return raw
