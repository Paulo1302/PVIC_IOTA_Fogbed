"""Runs the v1.33.1 genesis builder (``iota-localnet genesis``) either inside the pinned Docker
image (default, guarantees the same build as the nodes) or from a local ``docker/bins`` dir.

In v1.33.1 the ``genesis`` subcommand no longer exists on ``iota``; it lives in the separate
``iota-localnet`` binary shipped in the same release asset.
"""

from __future__ import annotations

import logging
import os
import shlex
import subprocess
from pathlib import Path
from typing import List, Optional, Sequence

from .errors import ToolError
from .release import REQUIRED_BINARIES, load_release, verify_binaries

logger = logging.getLogger("fogbed_iota.genesis.tools")

DEFAULT_IMAGE = os.getenv("IOTA_DOCKER_IMAGE", "iota-dev:latest")


class ToolRunner:
    """Executes ``iota-localnet`` with ``workdir`` as cwd; all path arguments must be relative."""

    def __init__(
        self,
        image: Optional[str] = DEFAULT_IMAGE,
        bins_dir: Optional[Path] = None,
        docker_bin: str = "docker",
        timeout: int = 600,
    ) -> None:
        self.image = image
        self.bins_dir = Path(bins_dir) if bins_dir else None
        self.docker_bin = docker_bin
        self.timeout = timeout
        self._verified = False

    # -- release gate -------------------------------------------------------
    def verify(self) -> None:
        """Fail fast unless the tool build is the pinned release."""
        if self._verified:
            return
        release = load_release()
        if self.bins_dir is not None:
            for line in verify_binaries(self.bins_dir, release):
                logger.info("local binary check: %s", line)
        else:
            self._verify_image(release)
        self._verified = True

    def _verify_image(self, release) -> None:
        res = self._docker(
            ["run", "--rm", "--entrypoint", "/usr/local/bin/iota-entrypoint.sh", self.image, "version"],
            what=f"version check of image {self.image}",
            hint=f"build it: docker build -f docker/Dockerfile.local -t {self.image} .",
        )
        for name in REQUIRED_BINARIES:
            if f"{name}: {release.version_string} OK" not in res:
                raise ToolError(
                    f"image {self.image} does not contain {name} {release.version_string}",
                    hint="rebuild the image from docker/Dockerfile.local with the v1.33.1 binaries",
                )
        logger.info("image %s is pinned to IOTA %s (%s)", self.image, release.tag, release.version_string)

    # -- execution ----------------------------------------------------------
    def _docker(self, args: Sequence[str], what: str, hint: Optional[str] = None) -> str:
        cmd = [self.docker_bin, *args]
        logger.debug("exec: %s", " ".join(shlex.quote(a) for a in cmd))
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ToolError(f"{what} failed to run: {exc}", hint=hint or "is Docker installed and running?") from exc
        out = (proc.stdout or "") + (proc.stderr or "")
        if proc.returncode != 0:
            tail = "\n".join(out.strip().splitlines()[-25:])
            raise ToolError(f"{what} failed (exit {proc.returncode}):\n{tail}", hint=hint)
        return out

    def run_localnet(self, args: Sequence[str], workdir: Path) -> str:
        """Run ``iota-localnet <args>`` with cwd/mount ``workdir``; returns combined output."""
        self.verify()
        workdir = Path(workdir).resolve()
        workdir.mkdir(parents=True, exist_ok=True)
        what = "iota-localnet " + " ".join(args[:2])
        if self.bins_dir is not None:
            cmd = [str((self.bins_dir / "iota-localnet").resolve()), *args]
            logger.debug("exec (local): %s [cwd=%s]", " ".join(shlex.quote(a) for a in cmd), workdir)
            try:
                proc = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True, timeout=self.timeout)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise ToolError(f"{what} failed to run: {exc}") from exc
            out = (proc.stdout or "") + (proc.stderr or "")
            if proc.returncode != 0:
                tail = "\n".join(out.strip().splitlines()[-25:])
                raise ToolError(f"{what} failed (exit {proc.returncode}):\n{tail}")
            return out
        # Run as the invoking user so artifacts on the host are not root-owned.
        user = f"{os.getuid()}:{os.getgid()}" if hasattr(os, "getuid") else "0:0"
        return self._docker(
            [
                "run", "--rm", "--user", user, "-e", "HOME=/tmp",
                "--entrypoint", "/usr/local/bin/iota-localnet",
                "-v", f"{workdir}:/work", "-w", "/work",
                self.image, *args,
            ],
            what=what,
        )

    def describe(self) -> List[str]:
        return [f"image={self.image}" if self.bins_dir is None else f"bins_dir={self.bins_dir}"]
