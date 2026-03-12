"""Typed multimodal gateway errors."""

from __future__ import annotations

from strataforge.llm.multimodal_gateway.types import (
    MultimodalGatewayAuditRecord,
    MultimodalGatewayFailure,
)


class MultimodalGatewayError(Exception):
    """Base class for multimodal gateway failures."""

    def __init__(
        self,
        failure: MultimodalGatewayFailure,
        *,
        audit_record: MultimodalGatewayAuditRecord,
        audit_path: str | None,
    ) -> None:
        super().__init__(failure.message)
        self.failure = failure
        self.audit_record = audit_record
        self.audit_path = audit_path
