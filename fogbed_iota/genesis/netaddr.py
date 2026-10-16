"""Multiaddr / socket-address helpers and validation for announced vs. bind addresses.

Announced (reachable by *other* nodes): genesis ``network_address`` / ``p2p_address`` /
``primary_address``, ``p2p-config.external-address`` and every seed-peer address. These must
carry the node's Fogbed virtual IP and never a loopback / unspecified address.

Bind (local listening sockets): ``network-address``, ``p2p-config.listen-address``,
``metrics-address`` ... where ``0.0.0.0`` is correct.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from typing import Optional

from .errors import ConfigValidationError

_MULTIADDR_RE = re.compile(
    r"^/ip4/(?P<ip>\d{1,3}(?:\.\d{1,3}){3})/(?P<proto>tcp|udp)/(?P<port>\d{1,5})(?:/(?P<suffix>http|quic))?$"
)
_SOCKET_RE = re.compile(r"^(?P<ip>\d{1,3}(?:\.\d{1,3}){3}):(?P<port>\d{1,5})$")


@dataclass(frozen=True)
class Multiaddr:
    ip: str
    proto: str
    port: int
    suffix: Optional[str]

    def __str__(self) -> str:
        tail = f"/{self.suffix}" if self.suffix else ""
        return f"/ip4/{self.ip}/{self.proto}/{self.port}{tail}"


def _check_port(port: int, what: str) -> int:
    if not 1 <= port <= 65535:
        raise ConfigValidationError(f"{what}: port {port} out of range 1-65535")
    return port


def parse_multiaddr(text: str, what: str = "address") -> Multiaddr:
    match = _MULTIADDR_RE.match(str(text))
    if not match:
        raise ConfigValidationError(
            f"{what}: '{text}' is not a valid /ip4/<ip>/(tcp|udp)/<port>[/http|/quic] multiaddr"
        )
    try:
        ipaddress.IPv4Address(match["ip"])
    except ValueError as exc:
        raise ConfigValidationError(f"{what}: invalid IPv4 '{match['ip']}'") from exc
    return Multiaddr(match["ip"], match["proto"], _check_port(int(match["port"]), what), match["suffix"])


def parse_socket(text: str, what: str = "address") -> "tuple[str, int]":
    match = _SOCKET_RE.match(str(text))
    if not match:
        raise ConfigValidationError(f"{what}: '{text}' is not <ipv4>:<port>")
    try:
        ipaddress.IPv4Address(match["ip"])
    except ValueError as exc:
        raise ConfigValidationError(f"{what}: invalid IPv4 '{match['ip']}'") from exc
    return match["ip"], _check_port(int(match["port"]), what)


def is_loopback_or_unspecified(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    return addr.is_loopback or addr.is_unspecified


def validate_virtual_ip(ip: str, subnet: Optional[str], what: str) -> str:
    try:
        addr = ipaddress.IPv4Address(ip)
    except ValueError as exc:
        raise ConfigValidationError(f"{what}: '{ip}' is not a valid IPv4 address") from exc
    if addr.is_loopback or addr.is_unspecified:
        raise ConfigValidationError(
            f"{what}: '{ip}' is loopback/unspecified and cannot be announced to other validators",
            hint="use the Fogbed virtual IP (10.0.0.x) of the container",
        )
    if subnet and addr not in ipaddress.IPv4Network(subnet):
        raise ConfigValidationError(
            f"{what}: '{ip}' is outside the Fogbed virtual subnet {subnet}",
            hint="pass subnet=None / --subnet '' only if your Fogbed topology uses another range",
        )
    return str(addr)


def validate_announced(text: str, expected_ip: str, proto: str, suffix: Optional[str], what: str) -> Multiaddr:
    """Announced multiaddr: must be exactly /ip4/<expected_ip>/<proto>/<port>[/suffix]."""
    addr = parse_multiaddr(text, what)
    if is_loopback_or_unspecified(addr.ip):
        raise ConfigValidationError(
            f"{what}: announced address '{text}' is loopback/unspecified",
            hint="announced addresses must use the validator's Fogbed virtual IP",
        )
    if addr.ip != expected_ip:
        raise ConfigValidationError(f"{what}: announced IP {addr.ip} != node virtual IP {expected_ip}")
    if addr.proto != proto or (suffix is not None and addr.suffix != suffix):
        want = f"/{proto}/<port>" + (f"/{suffix}" if suffix else "")
        raise ConfigValidationError(f"{what}: '{text}' must look like /ip4/{expected_ip}{want}")
    return addr


def validate_bind_all(text: str, what: str) -> "tuple[str, int]":
    ip, port = parse_socket(text, what)
    if ip != "0.0.0.0":
        raise ConfigValidationError(f"{what}: listen socket '{text}' should bind 0.0.0.0")
    return ip, port
