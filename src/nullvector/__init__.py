"""NullVector -- vectorless hierarchical RAG framework.

Processes PDFs and Markdown into auditable, searchable hierarchical trees
without vector embeddings.  All retrieval is structural (BM25-style ranking,
Jaccard similarity, tree traversal) with full spatial traceability back to
source bounding boxes.

Quick start::

    from nullvector import NullVectorClient

    client = NullVectorClient("./workspace")
    result = client.ingest("document.pdf")
    hits   = client.search("your query", document_id=result.document_id)

All domain types remain importable from ``nullvector.domain``.
"""

# ── Facade ────────────────────────────────────────────────────────────
from nullvector.client import ClientIngestResult, NullVectorClient

# ── Core request / result types (appear in client & service signatures) ──
# ── Pinned re-exports (verified by test_bootstrap_layout.py) ─────────
from nullvector.domain import (
    AcquisitionRequest,
    AcquisitionRunIndex,
    AcquisitionRunManifest,
    AcquisitionSettings,
    AnswerCitation,
    BatchItemFailure,
    BatchResult,
    CanonicalDocumentLedger,
    ContentSpan,
    ExtractionProvenance,
    NodeCard,
    NodeOwnedSpan,
    PageLedgerRow,
    ParseJobLifecycle,
    ParseJobState,
    QueryIntent,
    QueryPlan,
    RetrievalCorpus,
    RetrievalHit,
    SourceDocumentKind,
    TreeBuildManifest,
    TreeBuildRequest,
    TreeNodeVerificationResult,
    TreeSettings,
    TreeSynthesisView,
    TrustTier,
    VerificationResult,
)

# ── Errors ────────────────────────────────────────────────────────────
from nullvector.errors import (
    ClientValidationError,
    DocumentNotIndexedError,
    GatewayInvocationError,
    GatewayUnavailableError,
    IngestionError,
    NullVectorError,
    QueryError,
    RetrievalError,
    TreeBuildError,
)

# ── Batch orchestration ──────────────────────────────────────────────
from nullvector.ingest.acquisition_service import acquire_batch, async_acquire_batch

# ── Presets ───────────────────────────────────────────────────────────
from nullvector.presets import DocumentPreset, get_preset, list_presets
from nullvector.tree.service import async_build_tree_batch, build_tree_batch

__all__ = [
    # Core request / result types
    "AcquisitionRequest",
    # Pinned re-exports (test_bootstrap_layout.py)
    "AcquisitionRunIndex",
    "AcquisitionRunManifest",
    "AcquisitionSettings",
    "AnswerCitation",
    "BatchItemFailure",
    "BatchResult",
    "CanonicalDocumentLedger",
    # Facade
    "ClientIngestResult",
    # Errors
    "ClientValidationError",
    "ContentSpan",
    "DocumentNotIndexedError",
    # Presets
    "DocumentPreset",
    "ExtractionProvenance",
    "GatewayInvocationError",
    "GatewayUnavailableError",
    "IngestionError",
    "NodeCard",
    "NodeOwnedSpan",
    "NullVectorClient",
    "NullVectorError",
    "PageLedgerRow",
    "ParseJobLifecycle",
    "ParseJobState",
    "QueryError",
    "QueryIntent",
    "QueryPlan",
    "RetrievalCorpus",
    "RetrievalError",
    "RetrievalHit",
    "SourceDocumentKind",
    "TreeBuildError",
    "TreeBuildManifest",
    "TreeBuildRequest",
    "TreeNodeVerificationResult",
    "TreeSettings",
    "TreeSynthesisView",
    "TrustTier",
    "VerificationResult",
    # Batch orchestration
    "acquire_batch",
    "async_acquire_batch",
    "async_build_tree_batch",
    "build_tree_batch",
    "get_preset",
    "list_presets",
]
