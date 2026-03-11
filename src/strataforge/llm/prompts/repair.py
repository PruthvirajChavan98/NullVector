"""Bounded repair prompts and structured response models."""

from __future__ import annotations

import json

from pydantic import PositiveInt, model_validator

from strataforge.domain.models import NonEmptyStr, RepairRequest, RepairStatus, StrataModel
from strataforge.llm.audit import json_safe
from strataforge.llm.types import LLMMessage, LLMRole

ALLOWED_REPAIR_STATUSES = {
    RepairStatus.REQUESTED_BUT_SKIPPED,
    RepairStatus.PROPOSAL_GENERATED,
    RepairStatus.PROPOSAL_REJECTED,
}


class RepairPromptResponse(StrataModel):
    """Typed structured response expected from a repair prompt."""

    request_id: NonEmptyStr
    status: RepairStatus
    message: NonEmptyStr
    proposed_title: NonEmptyStr | None = None
    resolved_level: PositiveInt | None = None

    @model_validator(mode="after")
    def validate_response(self) -> RepairPromptResponse:
        if self.status not in ALLOWED_REPAIR_STATUSES:
            msg = "repair prompt responses may only return skipped, generated, or rejected statuses"
            raise ValueError(msg)
        if self.status == RepairStatus.PROPOSAL_GENERATED and not (
            self.proposed_title is not None or self.resolved_level is not None
        ):
            msg = "proposal_generated responses must include a proposed_title or resolved_level"
            raise ValueError(msg)
        return self


def build_repair_messages(request: RepairRequest) -> tuple[LLMMessage, ...]:
    """Build grounded, bounded messages for a single repair request."""

    payload = json.dumps(json_safe(request), indent=2, sort_keys=True, ensure_ascii=True)
    system = LLMMessage(
        role=LLMRole.SYSTEM,
        content=(
            "You are assisting bounded hierarchy repair for StrataForge. "
            "Only reason about the single repair request provided. "
            "Never invent sections, page spans, provenance, or titles not "
            "supported by the request. "
            "If evidence is insufficient, return requested_but_skipped or proposal_rejected."
        ),
    )
    user = LLMMessage(
        role=LLMRole.USER,
        content=(
            "Return a structured repair decision for the request below.\n"
            "Allowed statuses: requested_but_skipped, proposal_generated, proposal_rejected.\n"
            "Only set proposed_title for title normalization. "
            "Only set resolved_level for adjacent level ambiguity or partial TOC repair.\n\n"
            f"Repair request:\n{payload}"
        ),
    )
    return (system, user)
