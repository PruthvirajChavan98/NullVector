"""Protocols for the parallel v2 acquisition runtime."""

from __future__ import annotations

from typing import Protocol

from strataforge.domain.models import AcquisitionRequest, CanonicalDocumentLedger


class AcquisitionProvider(Protocol):
    """Framework or user-owned provider that produces a canonical document ledger."""

    provider_identity: str

    def acquire(self, request: AcquisitionRequest) -> CanonicalDocumentLedger:
        """Acquire one source document into the canonical v2 ledger."""


class TranslationAdapter(Protocol):
    """User-owned adapter that translates external provider payloads into the ledger."""

    adapter_name: str

    def translate(
        self,
        payload: object,
        *,
        request: AcquisitionRequest,
    ) -> CanonicalDocumentLedger:
        """Translate an external provider payload into the canonical v2 ledger."""
