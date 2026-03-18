"""Typed prompt builders for the Phase 03 LLM gateway."""

from nullvector.llm.prompts.decomposition import build_decomposition_messages
from nullvector.llm.prompts.document_description import (
    DocumentDescriptionPromptResponse,
    build_document_description_messages,
)
from nullvector.llm.prompts.repair import RepairPromptResponse, build_repair_messages
from nullvector.llm.prompts.summarization import (
    SummarizationPromptResponse,
    build_summarization_messages,
)
from nullvector.llm.prompts.toc import build_toc_detection_messages
from nullvector.llm.prompts.toc_reconcile import build_toc_parse_messages
from nullvector.llm.prompts.verification import (
    VerificationPromptResponse,
    build_verification_messages,
)

__all__ = [
    "DocumentDescriptionPromptResponse",
    "RepairPromptResponse",
    "SummarizationPromptResponse",
    "VerificationPromptResponse",
    "build_decomposition_messages",
    "build_document_description_messages",
    "build_repair_messages",
    "build_summarization_messages",
    "build_toc_detection_messages",
    "build_toc_parse_messages",
    "build_verification_messages",
]
