"""Multi-tier (Edge / Fog / Cloud) topology model for ``fogbed_iota``.

This module is intentionally **free of Fogbed/Mininet imports**: it only describes *what*
the experimenter wants (tiers, per-link ``delay``/``bw``/``loss`` and how tiers are chained)
and validates it up front, so that a bad topology fails in milliseconds instead of after
Docker containers and OVS switches have been created.

Mapping onto Fogbed (see ``docs/MULTITIER_IMPLEMENTATION_MAP.md``):

* one **tier** == one Fogbed ``VirtualInstance`` == one OVS switch;
* an **inter-tier link** == ``FogbedExperiment.add_link(dc_a, dc_b, **profile)`` (``TCLink``);
* the **access link** of a tier (host <-> tier switch) == ``Container.link_params``.

All hosts live in the single Mininet ``10.0.0.0/8`` L2 domain, so static IPs are preserved
across chained switches and no routing is involved. Because the switches run without STP the
tier graph **must be a tree**; :meth:`TopologySpec.validate` enforces it.
"""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union


class TopologyError(ValueError):
    """The requested topology is invalid (raised before anything is created)."""


class TopologyValidationError(RuntimeError):
    """A *running* topology failed its end-to-end verification."""


class Tier(str, Enum):
    """Canonical tier names (custom tier names are also accepted everywhere)."""

    EDGE = "edge"
    FOG = "fog"
    CLOUD = "cloud"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


TierRef = Union[str, Tier]


def tier_name(tier: Optional[TierRef]) -> Optional[str]:
    """Normalises ``Tier.EDGE`` / ``"edge"`` / ``None`` to a plain string (or ``None``)."""
    if tier is None:
        return None
    name = tier.value if isinstance(tier, Tier) else str(tier)
    name = name.strip()
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,31}", name):
        raise TopologyError(f"invalid tier name {tier!r}: use 1-32 chars [A-Za-z0-9_-], starting with a letter")
    return name


# ---------------------------------------------------------------------------
# Link profile
# ---------------------------------------------------------------------------
_TIME_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(us|ms|s)\s*$")
_TIME_TO_MS = {"us": 0.001, "ms": 1.0, "s": 1000.0}

#: Parameters understood by Mininet's ``TCLink`` that this library exposes.
LINK_PARAM_KEYS = ("delay", "bw", "loss", "jitter", "max_queue_size")

#: ``TCLink`` asserts ``0 <= bw <= 1000`` (Mbit/s); we additionally reject 0 (= "unlimited"
#: is expressed by *omitting* ``bw``).
MAX_BW_MBPS = 1000.0


def time_to_ms(value: str, what: str = "delay") -> float:
    m = _TIME_RE.match(str(value))
    if not m:
        raise TopologyError(f"invalid {what} {value!r}: expected a number plus us|ms|s (e.g. '20ms')")
    return float(m.group(1)) * _TIME_TO_MS[m.group(2)]


@dataclass(frozen=True)
class LinkProfile:
    """Heterogeneous link characteristics (all optional; ``None`` == not shaped).

    ``delay``/``jitter`` use Mininet notation (``"20ms"``); ``bw`` is Mbit/s; ``loss`` is a
    percentage in ``[0, 100]``.
    """

    delay: Optional[str] = None
    bw: Optional[float] = None
    loss: Optional[float] = None
    jitter: Optional[str] = None
    max_queue_size: Optional[int] = None

    def __post_init__(self) -> None:
        if self.delay is not None:
            time_to_ms(self.delay, "delay")
        if self.jitter is not None:
            time_to_ms(self.jitter, "jitter")
            if self.delay is None:
                raise TopologyError("jitter requires delay (netem needs a base delay)")
        if self.bw is not None and not (0 < float(self.bw) <= MAX_BW_MBPS):
            raise TopologyError(f"invalid bw {self.bw!r}: must be in (0, {MAX_BW_MBPS:g}] Mbit/s")
        if self.loss is not None and not (0 <= float(self.loss) <= 100):
            raise TopologyError(f"invalid loss {self.loss!r}: must be a percentage in [0, 100]")
        if self.max_queue_size is not None and int(self.max_queue_size) <= 0:
            raise TopologyError(f"invalid max_queue_size {self.max_queue_size!r}: must be > 0")

    # -- construction ------------------------------------------------------
    @classmethod
    def from_params(cls, params: Union["LinkProfile", Mapping[str, Any], None]) -> "LinkProfile":
        """Builds a profile from a ``dict`` of TCLink params (rejects unknown keys → typos)."""
        if params is None:
            return cls()
        if isinstance(params, LinkProfile):
            return params
        unknown = sorted(set(params) - set(LINK_PARAM_KEYS))
        if unknown:
            raise TopologyError(f"unsupported link parameter(s) {unknown}; supported: {list(LINK_PARAM_KEYS)}")
        return cls(**{k: params[k] for k in LINK_PARAM_KEYS if params.get(k) is not None})

    # -- views -------------------------------------------------------------
    def to_params(self) -> Dict[str, Any]:
        """``TCLink`` keyword arguments (only the parameters that are set)."""
        return {k: getattr(self, k) for k in LINK_PARAM_KEYS if getattr(self, k) is not None}

    def merged_over(self, base: "LinkProfile") -> "LinkProfile":
        """``self`` overrides ``base`` field-by-field."""
        merged = {**base.to_params(), **self.to_params()}
        return LinkProfile(**merged)

    @property
    def delay_ms(self) -> float:
        return time_to_ms(self.delay) if self.delay is not None else 0.0

    @property
    def is_shaped(self) -> bool:
        return bool(self.to_params())

    def describe(self) -> str:
        p = self.to_params()
        return ", ".join(f"{k}={v}" for k, v in p.items()) if p else "unshaped"


# ---------------------------------------------------------------------------
# Tiers and the tier graph
# ---------------------------------------------------------------------------
@dataclass
class TierSpec:
    name: str
    access_link: LinkProfile = field(default_factory=LinkProfile)
    resource_model: Any = None  # a ``fogbed.resources.protocols.ResourceModel`` (opaque here)


@dataclass(frozen=True)
class InterTierLink:
    a: str
    b: str
    profile: LinkProfile


@dataclass
class TopologySpec:
    """Tiers + the inter-tier links connecting their switches."""

    tiers: Dict[str, TierSpec] = field(default_factory=dict)
    links: List[InterTierLink] = field(default_factory=list)

    # -- building ----------------------------------------------------------
    def add_tier(
        self,
        name: TierRef,
        access_link: Union[LinkProfile, Mapping[str, Any], None] = None,
        resource_model: Any = None,
    ) -> TierSpec:
        n = tier_name(name)
        assert n is not None
        if n in self.tiers:
            raise TopologyError(f"tier {n!r} already declared")
        spec = TierSpec(n, LinkProfile.from_params(access_link), resource_model)
        self.tiers[n] = spec
        return spec

    def connect(
        self,
        a: TierRef,
        b: TierRef,
        profile: Union[LinkProfile, Mapping[str, Any], None] = None,
    ) -> InterTierLink:
        na, nb = tier_name(a), tier_name(b)
        assert na is not None and nb is not None
        link = InterTierLink(na, nb, LinkProfile.from_params(profile))
        self.links.append(link)
        return link

    # -- validation --------------------------------------------------------
    def validate(self) -> None:
        """Fails fast on: undeclared tiers, self links, cycles (no STP!), disconnected tiers."""
        for link in self.links:
            for end in (link.a, link.b):
                if end not in self.tiers:
                    raise TopologyError(
                        f"link {link.a}<->{link.b} references undeclared tier {end!r}; "
                        f"declared: {sorted(self.tiers)}"
                    )
            if link.a == link.b:
                raise TopologyError(f"link {link.a}<->{link.b} connects a tier to itself")

        parent = {t: t for t in self.tiers}

        def find(x: str) -> str:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for link in self.links:
            ra, rb = find(link.a), find(link.b)
            if ra == rb:
                raise TopologyError(
                    f"link {link.a}<->{link.b} closes a loop in the switch graph. The OVS switches run "
                    f"without STP, so loops cause broadcast storms: use a tree (e.g. edge-fog-cloud chain)."
                )
            parent[ra] = rb

        if len(self.tiers) > 1 and len({find(t) for t in self.tiers}) > 1:
            raise TopologyError(
                "tiers are not all connected: "
                + ", ".join(sorted({find(t) for t in self.tiers}))
                + " are separate islands (nodes in different islands could never talk)"
            )

    # -- queries -----------------------------------------------------------
    def path(self, src: TierRef, dst: TierRef) -> List[InterTierLink]:
        """Inter-tier links on the (unique, tree) path ``src → dst``; ``[]`` if same tier."""
        s, d = tier_name(src), tier_name(dst)
        if s not in self.tiers or d not in self.tiers:
            raise TopologyError(f"unknown tier in path query: {s!r} -> {d!r}")
        if s == d:
            return []
        adj: Dict[str, List[Tuple[str, InterTierLink]]] = {t: [] for t in self.tiers}
        for link in self.links:
            adj[link.a].append((link.b, link))
            adj[link.b].append((link.a, link))
        prev: Dict[str, Optional[Tuple[str, InterTierLink]]] = {s: None}
        queue = deque([s])
        while queue:
            cur = queue.popleft()
            if cur == d:
                break
            for nxt, link in adj[cur]:
                if nxt not in prev:
                    prev[nxt] = (cur, link)
                    queue.append(nxt)
        if d not in prev:
            raise TopologyError(f"no path between tiers {s!r} and {d!r}")
        out: List[InterTierLink] = []
        node: str = d
        while prev[node] is not None:
            parent_node, link = prev[node]  # type: ignore[misc]
            out.append(link)
            node = parent_node
        out.reverse()
        return out

    def expected_rtt_ms(
        self,
        src_tier: TierRef,
        dst_tier: TierRef,
        src_access: Optional[LinkProfile] = None,
        dst_access: Optional[LinkProfile] = None,
    ) -> float:
        """Expected ICMP RTT (ms) between two hosts, from the configured *delays* only.

        ``TCLink`` shapes both ends of a link, so a packet pays each traversed link's delay once
        per direction ⇒ ``RTT = 2 × Σ delay(links on path)``, including both access links.
        """
        s, d = tier_name(src_tier), tier_name(dst_tier)
        if s not in self.tiers or d not in self.tiers:
            raise TopologyError(f"unknown tier in RTT query: {s!r} -> {d!r}")
        one_way = (src_access or self.tiers[s].access_link).delay_ms  # type: ignore[index]
        one_way += (dst_access or self.tiers[d].access_link).delay_ms  # type: ignore[index]
        one_way += sum(link.profile.delay_ms for link in self.path(s, d))  # type: ignore[arg-type]
        return 2.0 * one_way

    def describe(self) -> Dict[str, Any]:
        return {
            "tiers": {n: t.access_link.to_params() for n, t in self.tiers.items()},
            "links": [{"a": l.a, "b": l.b, **l.profile.to_params()} for l in self.links],
        }


# ---------------------------------------------------------------------------
# 3-tier preset
# ---------------------------------------------------------------------------
#: Illustrative defaults (edge radio hop is the worst; WAN to the cloud is slow but fat).
#: They are *starting points* for experiments, not measurements of any real deployment.
DEFAULT_EDGE_FOG = LinkProfile(delay="20ms", bw=50, loss=1)
DEFAULT_FOG_CLOUD = LinkProfile(delay="50ms", bw=100, loss=0.1)


def three_tier_topology(
    edge_fog: Union[LinkProfile, Mapping[str, Any], None] = None,
    fog_cloud: Union[LinkProfile, Mapping[str, Any], None] = None,
    edge_access: Union[LinkProfile, Mapping[str, Any], None] = None,
    fog_access: Union[LinkProfile, Mapping[str, Any], None] = None,
    cloud_access: Union[LinkProfile, Mapping[str, Any], None] = None,
) -> TopologySpec:
    """Builds ``edge — fog — cloud`` (a chain: loop-free by construction)."""
    topo = TopologySpec()
    topo.add_tier(Tier.EDGE, edge_access)
    topo.add_tier(Tier.FOG, fog_access)
    topo.add_tier(Tier.CLOUD, cloud_access)
    topo.connect(Tier.EDGE, Tier.FOG, DEFAULT_EDGE_FOG if edge_fog is None else edge_fog)
    topo.connect(Tier.FOG, Tier.CLOUD, DEFAULT_FOG_CLOUD if fog_cloud is None else fog_cloud)
    topo.validate()
    return topo


__all__: Sequence[str] = [
    "DEFAULT_EDGE_FOG",
    "DEFAULT_FOG_CLOUD",
    "InterTierLink",
    "LINK_PARAM_KEYS",
    "LinkProfile",
    "Tier",
    "TierRef",
    "TierSpec",
    "TopologyError",
    "TopologySpec",
    "TopologyValidationError",
    "three_tier_topology",
    "tier_name",
    "time_to_ms",
]
