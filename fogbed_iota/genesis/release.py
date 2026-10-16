"""Pinned IOTA release (single source of truth: ``IOTA_RELEASE.json``).

The whole ecosystem treats the pinned release as a compatibility boundary: binaries, the
Docker image, persisted committee state and generated genesis artifacts are all stamped with
it and refuse to be combined with anything else.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

from .errors import ReleaseMismatchError

RELEASE_FILE = Path(__file__).with_name("IOTA_RELEASE.json")

#: Binaries that must come from the same release asset / build.
REQUIRED_BINARIES = ("iota", "iota-node", "iota-localnet")


@dataclass(frozen=True)
class IotaRelease:
    tag: str
    commit_sha: str
    version_string: str
    protocol_version: int
    binaries: Dict[str, str]
    asset_name: str
    asset_sha256: str
    asset_url: str
    os: str
    arch: str
    raw: Dict[str, Any]

    def stamp(self) -> Dict[str, Any]:
        """Compact release identity embedded in every persisted artifact."""
        return {
            "release_tag": self.tag,
            "commit_sha": self.commit_sha,
            "version_string": self.version_string,
            "protocol_version": self.protocol_version,
        }


@lru_cache(maxsize=1)
def load_release(path: Optional[str] = None) -> IotaRelease:
    file = Path(path) if path else RELEASE_FILE
    try:
        raw = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ReleaseMismatchError(
            f"cannot read pinned release manifest {file}: {exc}",
            hint="restore fogbed_iota/genesis/IOTA_RELEASE.json from version control",
        ) from exc
    return IotaRelease(
        tag=raw["release_tag"],
        commit_sha=raw["commit_sha"],
        version_string=raw["version_string"],
        protocol_version=int(raw["protocol_version"]),
        binaries=dict(raw["binaries"]),
        asset_name=raw["asset"]["name"],
        asset_sha256=raw["asset"]["sha256"],
        asset_url=raw["asset"]["url"],
        os=raw["target"]["os"],
        arch=raw["target"]["arch"],
        raw=raw,
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_binaries(
    bins_dir: Path,
    release: Optional[IotaRelease] = None,
    check_sha256: bool = True,
    run_version: bool = True,
) -> List[str]:
    """Check ``bins_dir`` against the pinned release; return human-readable report lines.

    Raises ReleaseMismatchError listing every problem found.
    """
    release = release or load_release()
    bins_dir = Path(bins_dir)
    problems: List[str] = []
    report: List[str] = []
    for name in REQUIRED_BINARIES:
        path = bins_dir / name
        if not path.is_file():
            problems.append(f"{path} missing")
            continue
        if check_sha256:
            actual = sha256_file(path)
            if actual != release.binaries[name]:
                problems.append(f"{name}: sha256 {actual} != pinned {release.binaries[name]}")
                continue
        if run_version:
            try:
                out = subprocess.run(
                    [str(path), "--version"], capture_output=True, text=True, timeout=30, check=True
                ).stdout.split()
                version = out[-1] if out else ""
            except (OSError, subprocess.SubprocessError) as exc:
                problems.append(f"{name}: cannot execute ({exc})")
                continue
            if version != release.version_string:
                problems.append(f"{name}: --version '{version}' != pinned '{release.version_string}'")
                continue
        report.append(f"{name}: OK ({release.version_string})")
    if problems:
        raise ReleaseMismatchError(
            "binaries in %s do not match IOTA %s:\n  - %s" % (bins_dir, release.tag, "\n  - ".join(problems)),
            hint="run ./docker/fetch_binaries.sh (or ./docker/build_from_source.sh) and rebuild the image",
        )
    return report


def ensure_same_release(found: Dict[str, Any], what: str, release: Optional[IotaRelease] = None) -> None:
    """Fail fast if a persisted artifact was produced by a different release."""
    release = release or load_release()
    for key, expected in release.stamp().items():
        if found.get(key) != expected:
            raise ReleaseMismatchError(
                f"{what} was produced for {key}={found.get(key)!r} but this code is pinned to {expected!r}",
                hint="regenerate the committee and genesis (never mix IOTA versions): "
                "use a fresh --artifacts-root or pass --force to `prepare`",
            )
