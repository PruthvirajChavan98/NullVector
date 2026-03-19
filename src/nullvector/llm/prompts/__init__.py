"""Typed prompt builders for the Phase 03 LLM gateway."""

from nullvector.llm.prompts.decomposition import build_decomposition_messages
from nullvector.llm.prompts.description_selection import (
    DescriptionSelectionPromptResponse,
    build_description_selection_messages,
)
from nullvector.llm.prompts.document_description import (
    DocumentDescriptionPromptResponse,
    build_document_description_messages,
)
from nullvector.llm.prompts.metadata_selection import (
    MetadataSelectionPromptResponse,
    build_metadata_selection_messages,
)
from nullvector.llm.prompts.preference_tree_search import (
    PreferenceTreeSearchFrontierPromptResponse,
    build_preference_tree_search_frontier_messages,
)
from nullvector.llm.prompts.repair import RepairPromptResponse, build_repair_messages
from nullvector.llm.prompts.summarization import (
    SummarizationPromptResponse,
    build_summarization_messages,
)
from nullvector.llm.prompts.toc import build_toc_detection_messages
from nullvector.llm.prompts.toc_reconcile import build_toc_parse_messages
from nullvector.llm.prompts.tree_search import (
    TreeSearchFrontierPromptResponse,
    build_tree_search_frontier_messages,
)
from nullvector.llm.prompts.verification import (
    VerificationPromptResponse,
    build_verification_messages,
)

__all__ = [
    "DescriptionSelectionPromptResponse",
    "DocumentDescriptionPromptResponse",
    "MetadataSelectionPromptResponse",
    "PreferenceTreeSearchFrontierPromptResponse",
    "RepairPromptResponse",
    "SummarizationPromptResponse",
    "TreeSearchFrontierPromptResponse",
    "VerificationPromptResponse",
    "build_decomposition_messages",
    "build_description_selection_messages",
    "build_document_description_messages",
    "build_metadata_selection_messages",
    "build_preference_tree_search_frontier_messages",
    "build_repair_messages",
    "build_summarization_messages",
    "build_toc_detection_messages",
    "build_toc_parse_messages",
    "build_tree_search_frontier_messages",
    "build_verification_messages",
]
