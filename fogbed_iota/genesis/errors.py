"""Errors raised by the two-step genesis pipeline.

Every error carries an actionable ``hint`` so failures can be diagnosed from the log alone.
"""

from __future__ import annotations

from typing import Optional


class GenesisError(Exception):
    """Base class: message + optional remediation hint."""

    def __init__(self, message: str, hint: Optional[str] = None) -> None:
        self.message = message
        self.hint = hint
        super().__init__(message if not hint else f"{message}\n  -> {hint}")


class ReleaseMismatchError(GenesisError):
    """Binaries / image / state do not match the pinned IOTA release."""


class CommitteeError(GenesisError):
    """Step 1 (committee preparation) failed or persisted state is inconsistent."""


class ConfigValidationError(GenesisError):
    """A generated node configuration is invalid for IOTA v1.33.1."""


class ToolError(GenesisError):
    """An IOTA tool (iota-localnet, docker) failed."""


class NodeStartError(GenesisError):
    """A node failed to start or become ready."""


class VerificationError(GenesisError):
    """Post-start verification (genesis consistency, committee, P2P) failed."""
