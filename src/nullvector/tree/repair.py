"""Typed repair boundary for deterministic Phase 02 tree builds."""

from __future__ import annotations

from typing import Protocol

from nullvector.domain.models import RepairDecision, RepairRequest, RepairStatus


class RepairEngine(Protocol):
    """Protocol that Phase 03 will later satisfy with a real gateway-backed engine."""

    def evaluate(
        self,
        requests: tuple[RepairRequest, ...],
    ) -> tuple[RepairDecision, ...]:
        """Return auditable repair decisions for bounded, typed requests."""


class NoopRepairEngine:
    """Default deterministic Phase 02 repair engine."""

    def evaluate(
        self,
        requests: tuple[RepairRequest, ...],
    ) -> tuple[RepairDecision, ...]:
        if not requests:
            return ()
        return tuple(
            RepairDecision(
                subject_id=request.subject_id,
                status=RepairStatus.NOOP_APPLIED,
                repair_kind=request.repair_kind,
                request_id=request.request_id,
                message="Phase 02 default repair engine leaves deterministic output unchanged",
                details=request.details,
            )
            for request in requests
        )
