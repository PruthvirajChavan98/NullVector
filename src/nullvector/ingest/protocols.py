"""Protocols for the parallel v2 acquisition runtime."""

from __future__ import annotations

from typing import Protocol

from nullvector.domain.ledger import AcquisitionRequest, CanonicalDocumentLedger


class AcquisitionProvider(Protocol):
    """Framework or user-owned provider that produces a canonical document ledger."""

    provider_identity: str

    def acquire(self, request: AcquisitionRequest) -> CanonicalDocumentLedger:
        """Acquire one source document into the canonical v2 ledger."""
