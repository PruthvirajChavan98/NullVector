# Workspace Diff

Generated on 2026-03-13T16:03:22+05:30 from `/home/pruthvi/projects/NullVector`.

Respects `.diffignore` for additional diff exclusions.

Includes tracked modifications plus untracked files rendered as `/dev/null` diffs.

```diff
diff --git a/AGENTS.md b/AGENTS.md
index cb93a0c..be65aff 100644
--- a/AGENTS.md
+++ b/AGENTS.md
@@ -58,3 +58,43 @@ Every substantive response must state:
 - Blockers:
 - Residual risks:
 
+
+## Mandatory raw diff input
+
+For every major change, Codex must include a raw diff excerpt derived from the actual repository diff, filtered to ignore paths matched by:
+
+- `.diffignore`
+
+The `.diffignore` file is a repo-root control file for change-log diff filtering.
+
+Rules for `.diffignore`:
+- fixed path: `.diffignore`
+- one pattern per line
+- blank lines are ignored
+- lines starting with `#` are comments
+- patterns must be interpreted using gitignore-style path matching relative to repo root
+
+If `.diffignore` is present, any file matching it must be excluded from raw diff capture in `CHANGE_DIFF.md`.
+
+If `.diffignore` is absent, raw diff capture must use the full repository diff.
+
+## Change-diff requirements
+
+For every major change, Codex must append a new dated entry to `CHANGE_DIFF.md` containing:
+1. phase / task name
+2. summary of what changed
+3. affected files
+4. user-visible or contract-visible impact
+5. a concise diff-style summary of the essential changes
+6. a raw diff section generated from the actual repo diff, excluding files matched by `.diffignore`
+7. required migration, rollback, or re-run steps, if any
+
+## Raw diff rules
+
+- Use the fixed path `CHANGE_DIFF.md`
+- The raw diff must be taken from the real repository state, not hand-written pseudo-diff
+- The raw diff must exclude files matched by `.diffignore`
+- Use fenced `diff` blocks
+- Include only the highest-signal hunks, but they must remain verbatim excerpts from the real diff
+- Do not include generated files, lockfile churn, notebook output noise, or vendor artifacts if they are ignored by `.diffignore`
+- If a major change occurred and the filtered raw diff was not added, the task is incomplete
diff --git a/src/nullvector/__init__.py b/src/nullvector/__init__.py
index 4e3d760..b32e35c 100644
--- a/src/nullvector/__init__.py
+++ b/src/nullvector/__init__.py
@@ -7,6 +7,7 @@ from nullvector.domain import (
     AcquisitionRunManifest,
     AcquisitionSettings,
     AnchorSource,
+    AnswerCitation,
     BoundingBox,
     CanonicalDocumentLedger,
     CanonicalPage,
@@ -59,10 +60,17 @@ from nullvector.domain import (
     ParserSettings,
     ParseRunIndex,
     ParseRunManifest,
+    QueryPlan,
     RepairDecision,
     RepairKind,
     RepairRequest,
     RepairStatus,
+    RetrievalCorpus,
+    RetrievalEvidence,
+    RetrievalHit,
+    RetrievalManifest,
+    RetrievalModality,
+    RetrievalUnitType,
     SemanticUsage,
     SourceMetadata,
     SourceTrack,
@@ -110,6 +118,7 @@ __all__ = [
     "AcquisitionRunManifest",
     "AcquisitionSettings",
     "AnchorSource",
+    "AnswerCitation",
     "BoundingBox",
     "CanonicalDocumentLedger",
     "CanonicalPage",
@@ -162,10 +171,17 @@ __all__ = [
     "ParseRunIndex",
     "ParseRunManifest",
     "ParserSettings",
+    "QueryPlan",
     "RepairDecision",
     "RepairKind",
     "RepairRequest",
     "RepairStatus",
+    "RetrievalCorpus",
+    "RetrievalEvidence",
+    "RetrievalHit",
+    "RetrievalManifest",
+    "RetrievalModality",
+    "RetrievalUnitType",
     "SemanticUsage",
     "SourceMetadata",
     "SourceTrack",
diff --git a/src/nullvector/domain/__init__.py b/src/nullvector/domain/__init__.py
index d8534b7..83423bc 100644
--- a/src/nullvector/domain/__init__.py
+++ b/src/nullvector/domain/__init__.py
@@ -56,6 +56,16 @@ from nullvector.domain.ledger import (
     UnresolvedRegion,
     VisualArtifact,
 )
+from nullvector.domain.retrieval import (
+    AnswerCitation,
+    QueryPlan,
+    RetrievalCorpus,
+    RetrievalEvidence,
+    RetrievalHit,
+    RetrievalManifest,
+    RetrievalModality,
+    RetrievalUnitType,
+)
 from nullvector.domain.tree import (
     AnchorSource,
     DecompositionBoundary,
@@ -118,6 +128,7 @@ __all__ = [
     "AcquisitionRunManifest",
     "AcquisitionSettings",
     "AnchorSource",
+    "AnswerCitation",
     "BoundingBox",
     "CanonicalDocumentLedger",
     "CanonicalPage",
@@ -170,10 +181,17 @@ __all__ = [
     "ParseRunIndex",
     "ParseRunManifest",
     "ParserSettings",
+    "QueryPlan",
     "RepairDecision",
     "RepairKind",
     "RepairRequest",
     "RepairStatus",
+    "RetrievalCorpus",
+    "RetrievalEvidence",
+    "RetrievalHit",
+    "RetrievalManifest",
+    "RetrievalModality",
+    "RetrievalUnitType",
     "SemanticUsage",
     "SourceMetadata",
     "SourceTrack",
diff --git a/src/nullvector/domain/models.py b/src/nullvector/domain/models.py
index b34631e..7dad457 100644
--- a/src/nullvector/domain/models.py
+++ b/src/nullvector/domain/models.py
@@ -61,6 +61,16 @@ from nullvector.domain.ledger import (
     UnresolvedRegion,
     VisualArtifact,
 )
+from nullvector.domain.retrieval import (
+    AnswerCitation,
+    QueryPlan,
+    RetrievalCorpus,
+    RetrievalEvidence,
+    RetrievalHit,
+    RetrievalManifest,
+    RetrievalModality,
+    RetrievalUnitType,
+)
 from nullvector.domain.tree import (
     AnchorSource,
     DecompositionBoundary,
@@ -125,6 +135,7 @@ __all__ = [
     "AcquisitionRunManifest",
     "AcquisitionSettings",
     "AnchorSource",
+    "AnswerCitation",
     "BoundingBox",
     "CanonicalDocumentLedger",
     "CanonicalPage",
@@ -179,10 +190,17 @@ __all__ = [
     "ParseRunIndex",
     "ParseRunManifest",
     "ParserSettings",
+    "QueryPlan",
     "RepairDecision",
     "RepairKind",
     "RepairRequest",
     "RepairStatus",
+    "RetrievalCorpus",
+    "RetrievalEvidence",
+    "RetrievalHit",
+    "RetrievalManifest",
+    "RetrievalModality",
+    "RetrievalUnitType",
     "ScalarValue",
     "SemanticUsage",
     "Sha256Hex",
diff --git a/src/nullvector/domain/tree.py b/src/nullvector/domain/tree.py
index 615a6a0..af305b6 100644
--- a/src/nullvector/domain/tree.py
+++ b/src/nullvector/domain/tree.py
@@ -5,7 +5,14 @@ from __future__ import annotations
 from enum import StrEnum
 from typing import Self
 
-from pydantic import Field, NonNegativeInt, PositiveFloat, PositiveInt, model_validator
+from pydantic import (
+    Field,
+    NonNegativeInt,
+    PositiveFloat,
+    PositiveInt,
+    field_validator,
+    model_validator,
+)
 
 from nullvector.domain.common import (
     BoundingBox,
@@ -384,6 +391,16 @@ class HierarchyNode(StrataModel):
     confidence: float = 0.0
     verification_match_tier: TitleMatchTier = TitleMatchTier.NONE
 
+    @field_validator("path", "owned_spans", "source_anchors", mode="before")
+    @classmethod
+    def _coerce_sequence_fields(
+        cls,
+        value: object,
+    ) -> object:
+        if isinstance(value, list):
+            return tuple(value)
+        return value
+
     @model_validator(mode="after")
     def validate_hierarchy_node(self) -> Self:
         if not self.path:
@@ -461,6 +478,16 @@ class NodeCard(StrataModel):
     summary_token_count: NonNegativeInt | None = None
     source_anchors: tuple[PageSourceAnchor, ...] = Field(default_factory=tuple)
 
+    @field_validator("path", "owned_spans", "keywords", "source_anchors", mode="before")
+    @classmethod
+    def _coerce_sequence_fields(
+        cls,
+        value: object,
+    ) -> object:
+        if isinstance(value, list):
+            return tuple(value)
+        return value
+
     @model_validator(mode="after")
     def validate_path_and_anchors(self) -> Self:
         if not self.path:
@@ -506,6 +533,16 @@ class NodeSummary(StrataModel):
     gateway_audit_path: NonEmptyStr | None = None
     gateway_usage: SemanticUsage | None = None
 
+    @field_validator("keywords", mode="before")
+    @classmethod
+    def _coerce_keywords(
+        cls,
+        value: object,
+    ) -> object:
+        if isinstance(value, list):
+            return tuple(value)
+        return value
+
 
 class DecompositionReport(StrataModel):
     """Persistable audit report for large-node decomposition."""
@@ -618,6 +655,16 @@ class TreeNodeVerificationResult(StrataModel):
     covered_page_span: PageSpan | None = None
     notes: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)
 
+    @field_validator("issues", "notes", mode="before")
+    @classmethod
+    def _coerce_result_sequences(
+        cls,
+        value: object,
+    ) -> object:
+        if isinstance(value, list):
+            return tuple(value)
+        return value
+
     @model_validator(mode="after")
     def validate_consistency(self) -> Self:
         has_error = any(issue.severity == VerificationSeverity.ERROR for issue in self.issues)
@@ -641,6 +688,22 @@ class VerificationReport(StrataModel):
     unassigned_spans: tuple[UnassignedPageSpan, ...] = Field(default_factory=tuple)
     notes: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)
 
+    @field_validator(
+        "node_results",
+        "document_issues",
+        "unassigned_spans",
+        "notes",
+        mode="before",
+    )
+    @classmethod
+    def _coerce_report_sequences(
+        cls,
+        value: object,
+    ) -> object:
+        if isinstance(value, list):
+            return tuple(value)
+        return value
+
     @model_validator(mode="after")
     def validate_report(self) -> Self:
         if (
@@ -665,6 +728,16 @@ class VerificationResult(StrataModel):
     covered_page_span: PageSpan | None = None
     notes: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)
 
+    @field_validator("issues", "notes", mode="before")
+    @classmethod
+    def _coerce_result_sequences(
+        cls,
+        value: object,
+    ) -> object:
+        if isinstance(value, list):
+            return tuple(value)
+        return value
+
     @model_validator(mode="after")
     def validate_consistency(self) -> Self:
         has_error = any(issue.severity == VerificationSeverity.ERROR for issue in self.issues)
diff --git a/src/nullvector/llm/__init__.py b/src/nullvector/llm/__init__.py
index fafad02..5b881ff 100644
--- a/src/nullvector/llm/__init__.py
+++ b/src/nullvector/llm/__init__.py
@@ -14,6 +14,7 @@ from nullvector.llm.errors import (
     GatewayValidationError,
 )
 from nullvector.llm.multimodal_gateway import (
+    LiteLLMMultimodalAdapter,
     MultimodalFailureCategory,
     MultimodalGatewayConfig,
     MultimodalGatewayError,
@@ -80,6 +81,7 @@ __all__ = [
     "GatewayValidationError",
     "LLMMessage",
     "LLMRole",
+    "LiteLLMMultimodalAdapter",
     "LiteLLMProviderConfig",
     "LiteLLMSDKAdapter",
     "MultimodalFailureCategory",
diff --git a/src/nullvector/llm/multimodal_gateway/__init__.py b/src/nullvector/llm/multimodal_gateway/__init__.py
index 0a9b64c..e80791e 100644
--- a/src/nullvector/llm/multimodal_gateway/__init__.py
+++ b/src/nullvector/llm/multimodal_gateway/__init__.py
@@ -6,6 +6,7 @@ from nullvector.llm.multimodal_gateway.protocols import (
     StructuredMultimodalGateway,
 )
 from nullvector.llm.multimodal_gateway.providers import (
+    LiteLLMMultimodalAdapter,
     NoopMultimodalProviderAdapter,
     NoopMultimodalResponse,
 )
@@ -28,6 +29,7 @@ from nullvector.llm.multimodal_gateway.types import (
 )
 
 __all__ = [
+    "LiteLLMMultimodalAdapter",
     "MultimodalAssuranceMode",
     "MultimodalFailureCategory",
     "MultimodalGatewayAuditRecord",
diff --git a/src/nullvector/llm/multimodal_gateway/providers/__init__.py b/src/nullvector/llm/multimodal_gateway/providers/__init__.py
index e16658c..1aa642d 100644
--- a/src/nullvector/llm/multimodal_gateway/providers/__init__.py
+++ b/src/nullvector/llm/multimodal_gateway/providers/__init__.py
@@ -1,11 +1,15 @@
 """Provider adapters for the attachment-only multimodal gateway."""
 
+from nullvector.llm.multimodal_gateway.providers.litellm_sdk import (
+    LiteLLMMultimodalAdapter,
+)
 from nullvector.llm.multimodal_gateway.providers.noop import (
     NoopMultimodalProviderAdapter,
     NoopMultimodalResponse,
 )
 
 __all__ = [
+    "LiteLLMMultimodalAdapter",
     "NoopMultimodalProviderAdapter",
     "NoopMultimodalResponse",
 ]
diff --git a/src/nullvector/llm/multimodal_gateway/service.py b/src/nullvector/llm/multimodal_gateway/service.py
index 3c3f479..ef8b6a2 100644
--- a/src/nullvector/llm/multimodal_gateway/service.py
+++ b/src/nullvector/llm/multimodal_gateway/service.py
@@ -18,6 +18,9 @@ from nullvector.llm.multimodal_gateway.protocols import (
     MultimodalProviderAdapter,
     StructuredMultimodalGateway,
 )
+from nullvector.llm.multimodal_gateway.providers.litellm_sdk import (
+    LiteLLMMultimodalAdapter,
+)
 from nullvector.llm.multimodal_gateway.providers.noop import NoopMultimodalProviderAdapter
 from nullvector.llm.multimodal_gateway.types import (
     JSONValue,
@@ -74,6 +77,8 @@ def _validate_region_inputs(request: MultimodalGatewayRequest[T]) -> None:
 
 
 def _default_provider_adapter(config: MultimodalGatewayConfig) -> MultimodalProviderAdapter:
+    if config.provider.provider == "litellm_multimodal":
+        return LiteLLMMultimodalAdapter()
     return NoopMultimodalProviderAdapter({})
 
 
diff --git a/.diffignore b/.diffignore
new file mode 100644
index 0000000..555c707
--- /dev/null
+++ b/.diffignore
@@ -0,0 +1,7 @@
+# Extra paths to omit from generated workspace diff artifacts.
+# Syntax is gitignore-like for the current generator.
+
+workspace-diff.md
+notebooks/
+src/files_dump_src_*.txt
+notebooks
diff --git a/CHANGE_DIFF.md b/CHANGE_DIFF.md
new file mode 100644
index 0000000..2ce76b8
--- /dev/null
+++ b/CHANGE_DIFF.md
@@ -0,0 +1,57 @@
+# Change Diff Log
+
+## 2026-03-13 - Retrieval Subsystem and Multimodal Visual QA
+
+Phase / task: First-class retrieval subsystem built from acquisition plus tree artifacts, with deterministic planning, vectorless ranking, QA synthesis, and a production multimodal adapter path.
+
+Summary of what changed:
+- Added typed retrieval domain contracts for evidence units, corpora, manifests, query plans, hits, citations, and QA responses.
+- Added retrieval corpus construction from acquisition artifacts and optional tree artifacts, including page text, tables, visuals, unresolved visuals, node text rebuilt from owned spans, node summaries, and unassigned spans.
+- Added deterministic query planning, in-memory indexing, lexical ranking, retrieval orchestration, cached visual enrichment lookup, and QA synthesis with honest visual-failure behavior.
+- Added a LiteLLM-backed multimodal provider adapter and hardened persisted tree artifact loading for tuple/list round-trips.
+- Updated the progress notebook and acceptance tests to exercise the new retrieval path.
+
+Affected files:
+- `src/nullvector/domain/retrieval.py`
+- `src/nullvector/domain/__init__.py`
+- `src/nullvector/domain/models.py`
+- `src/nullvector/domain/tree.py`
+- `src/nullvector/__init__.py`
+- `src/nullvector/retrieval/`
+- `src/nullvector/llm/multimodal_gateway/providers/litellm_sdk.py`
+- `src/nullvector/llm/multimodal_gateway/providers/__init__.py`
+- `src/nullvector/llm/multimodal_gateway/service.py`
+- `src/nullvector/llm/multimodal_gateway/__init__.py`
+- `src/nullvector/llm/__init__.py`
+- `tests/retrieval/`
+- `tests/llm/test_multimodal_litellm_adapter.py`
+- `notebooks/progress.ipynb`
+
+User-visible or contract-visible impact:
+- Page-scoped visual questions now filter to the requested page and modality before ranking.
+- QA no longer relies on `NodeCard` summaries as the only retrieval surface.
+- Visual answers either come from grounded cached enrichment or return an explicit "interpretation unavailable" message instead of drifting to unrelated text.
+- Retrieval artifacts now exist as their own persisted corpus and manifest, separate from tree structure artifacts.
+
+Diff highlights:
+```diff
+- QA and retrieval behavior centered on committed node cards and summaries.
++ Retrieval now builds a corpus from acquisition + tree artifacts with explicit evidence units.
+
+- Page-0 image questions could widen into unrelated summaries on other pages.
++ Query planning adds hard page/modality constraints and conservative widening rules.
+
+- Visual descriptions had no first-class retrieval representation.
++ Visual and unresolved-visual units carry modality, authoritativeness, interpretive state, and region references.
+
+- Persisted JSON list/tuple round-trips could fail strict artifact loading.
++ Artifact-facing tree models now coerce persisted lists into tuples at load boundaries.
+
+- Multimodal enrichment had only a noop provider path.
++ LiteLLM-backed multimodal adapter now maps provider responses into the typed gateway surface.
+```
+
+Migration, rollback, or re-run steps:
+- Re-run acquisition and tree generation as needed, then build a retrieval corpus with `RetrievalCorpusBuilder().build(...)`.
+- Load the persisted corpus via `load_retrieval_corpus(...)` and answer through `RetrievalQAService(...).answer(...)`.
+- If rolling back, remove retrieval-manifest/corpus consumers and fall back to pre-retrieval tree-only workflows.
diff --git a/src/nullvector/domain/retrieval.py b/src/nullvector/domain/retrieval.py
new file mode 100644
index 0000000..a5bbb13
--- /dev/null
+++ b/src/nullvector/domain/retrieval.py
@@ -0,0 +1,120 @@
+"""Typed retrieval corpus, planning, and answer-citation contracts."""
+
+from __future__ import annotations
+
+from enum import StrEnum
+
+from pydantic import Field, NonNegativeInt
+
+from nullvector.domain.common import ContentSpan, NonEmptyStr, PageSpan, StrataModel
+from nullvector.domain.events import TrustTier
+from nullvector.domain.tree import VisualRegionReference
+
+
+class RetrievalUnitType(StrEnum):
+    """Normalized retrieval evidence families."""
+
+    PAGE_TEXT = "page_text"
+    NODE_TEXT = "node_text"
+    NODE_SUMMARY = "node_summary"
+    TABLE = "table"
+    VISUAL = "visual"
+    UNRESOLVED_VISUAL = "unresolved_visual"
+    UNASSIGNED_SPAN = "unassigned_span"
+
+
+class RetrievalModality(StrEnum):
+    """Top-level modality used for planning and filtering."""
+
+    TEXT = "text"
+    TABLE = "table"
+    VISUAL = "visual"
+    MIXED = "mixed"
+
+
+class RetrievalEvidence(StrataModel):
+    """Single typed evidence unit available to retrieval and QA."""
+
+    unit_id: NonEmptyStr
+    document_id: NonEmptyStr
+    unit_type: RetrievalUnitType
+    modality: RetrievalModality
+    page_span: PageSpan
+    content_span: ContentSpan | None = None
+    node_id: NonEmptyStr | None = None
+    title: NonEmptyStr | None = None
+    text: str | None = None
+    keywords: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)
+    trust_tier: TrustTier | None = None
+    authoritative: bool = False
+    interpretive: bool = False
+    source_anchors: tuple[dict[str, object], ...] = Field(default_factory=tuple)
+    visual_region: VisualRegionReference | None = None
+    asset_path: NonEmptyStr | None = None
+    page_render_path: NonEmptyStr | None = None
+    metadata: dict[str, object] = Field(default_factory=dict)
+
+
+class RetrievalCorpus(StrataModel):
+    """Document-scoped retrieval corpus persisted as an artifact."""
+
+    document_id: NonEmptyStr
+    units: tuple[RetrievalEvidence, ...] = Field(default_factory=tuple)
+
+
+class RetrievalManifest(StrataModel):
+    """Manifest for a persisted retrieval corpus artifact set."""
+
+    document_id: NonEmptyStr
+    artifact_root: NonEmptyStr
+    corpus_path: NonEmptyStr
+    stats_path: NonEmptyStr
+    unit_count: NonNegativeInt
+
+
+class QueryPlan(StrataModel):
+    """Deterministic retrieval plan derived from one raw query."""
+
+    raw_query: NonEmptyStr
+    normalized_query: NonEmptyStr
+    page_filter: PageSpan | None = None
+    unit_types: tuple[RetrievalUnitType, ...] = Field(default_factory=tuple)
+    modality_filters: tuple[RetrievalModality, ...] = Field(default_factory=tuple)
+    title_like_phrases: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)
+    quoted_phrases: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)
+    structural_query: bool = False
+    visual_query: bool = False
+    table_query: bool = False
+    requires_multimodal: bool = False
+
+
+class RetrievalHit(StrataModel):
+    """Scored retrieval match with deterministic scoring details."""
+
+    unit: RetrievalEvidence
+    score: float
+    score_breakdown: dict[str, float] = Field(default_factory=dict)
+    matched_terms: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)
+
+
+class AnswerCitation(StrataModel):
+    """Grounded citation returned alongside QA answers."""
+
+    document_id: NonEmptyStr
+    unit_id: NonEmptyStr
+    page_span: PageSpan
+    node_id: NonEmptyStr | None = None
+    quote: str | None = None
+    asset_path: NonEmptyStr | None = None
+
+
+__all__ = [
+    "AnswerCitation",
+    "QueryPlan",
+    "RetrievalCorpus",
+    "RetrievalEvidence",
+    "RetrievalHit",
+    "RetrievalManifest",
+    "RetrievalModality",
+    "RetrievalUnitType",
+]
diff --git a/src/nullvector/llm/multimodal_gateway/providers/litellm_sdk.py b/src/nullvector/llm/multimodal_gateway/providers/litellm_sdk.py
new file mode 100644
index 0000000..f5c8e30
--- /dev/null
+++ b/src/nullvector/llm/multimodal_gateway/providers/litellm_sdk.py
@@ -0,0 +1,308 @@
+"""LiteLLM-backed multimodal adapter for attachment-only enrichment."""
+
+from __future__ import annotations
+
+import base64
+import json
+import mimetypes
+import os
+from collections.abc import Callable
+from pathlib import Path
+from typing import Any, cast
+
+from nullvector.llm.audit import json_safe
+from nullvector.llm.multimodal_gateway.types import (
+    MultimodalAssuranceMode,
+    MultimodalFailureCategory,
+    MultimodalGatewayConfig,
+    MultimodalUsage,
+    ProviderInvocationFailure,
+    ProviderInvocationRequest,
+    ProviderInvocationResult,
+    ProviderInvocationSuccess,
+    RegionImageInput,
+)
+
+
+def _extract_response_json(value: Any) -> dict[str, Any]:
+    if hasattr(value, "model_dump") and callable(value.model_dump):
+        return cast(dict[str, Any], value.model_dump())
+    if isinstance(value, dict):
+        return cast(dict[str, Any], value)
+    if hasattr(value, "__dict__"):
+        return cast(dict[str, Any], vars(value))
+    return {"raw": str(value)}
+
+
+def _guess_media_type(region: RegionImageInput) -> str:
+    if region.media_type is not None:
+        return region.media_type
+    guessed, _ = mimetypes.guess_type(region.image_path)
+    return guessed or "image/png"
+
+
+def _image_data_url(region: RegionImageInput) -> str:
+    path = Path(region.image_path)
+    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
+    return f"data:{_guess_media_type(region)};base64,{encoded}"
+
+
+def _extract_usage(payload: dict[str, Any]) -> MultimodalUsage | None:
+    usage = payload.get("usage")
+    if not isinstance(usage, dict):
+        return None
+    input_tokens = usage.get("input_tokens") or usage.get("prompt_tokens") or 0
+    output_tokens = usage.get("output_tokens") or usage.get("completion_tokens") or 0
+    total_tokens = usage.get("total_tokens") or (input_tokens + output_tokens)
+    if not all(isinstance(value, int) for value in (input_tokens, output_tokens, total_tokens)):
+        return None
+    return MultimodalUsage(
+        input_tokens=input_tokens,
+        output_tokens=output_tokens,
+        total_tokens=total_tokens,
+    )
+
+
+def _extract_structured_output(payload: dict[str, Any]) -> dict[str, Any] | None:
+    choices = payload.get("choices")
+    if not isinstance(choices, list) or not choices:
+        return None
+    first_choice = choices[0]
+    if not isinstance(first_choice, dict):
+        return None
+    message = first_choice.get("message")
+    if not isinstance(message, dict):
+        return None
+    parsed = message.get("parsed")
+    if isinstance(parsed, dict):
+        return cast(dict[str, Any], parsed)
+    content = message.get("content")
+    if isinstance(content, str) and content.strip():
+        return cast(dict[str, Any], json.loads(content))
+    if isinstance(content, list):
+        for item in content:
+            if not isinstance(item, dict):
+                continue
+            text = item.get("text")
+            if isinstance(text, str) and text.strip():
+                return cast(dict[str, Any], json.loads(text))
+    return None
+
+
+def _normalize_exception(
+    exc: Exception,
+    *,
+    provider_name: str,
+    model_name: str,
+) -> ProviderInvocationFailure:
+    message = str(exc).strip() or exc.__class__.__name__
+    status_code = getattr(exc, "status_code", None)
+    exc_name = exc.__class__.__name__.casefold()
+    message_key = message.casefold()
+
+    category = MultimodalFailureCategory.UNKNOWN_PROVIDER_FAILURE
+    if status_code == 400 and ("image" in message_key or "attachment" in message_key):
+        category = MultimodalFailureCategory.INVALID_ATTACHMENT
+    elif "timeout" in exc_name or "timeout" in message_key:
+        category = MultimodalFailureCategory.TIMEOUT
+    elif status_code in (401, 403) or "auth" in exc_name or "permission" in message_key:
+        category = MultimodalFailureCategory.AUTH_FAILURE
+    elif "connection" in exc_name or "network" in exc_name or "apierror" in exc_name:
+        category = MultimodalFailureCategory.NETWORK_FAILURE
+    elif "unsupported" in message_key or "not implemented" in message_key:
+        category = MultimodalFailureCategory.UNSUPPORTED_CAPABILITY
+    elif "schema" in message_key or "validation" in message_key or "json" in message_key:
+        category = MultimodalFailureCategory.VALIDATION_FAILURE
+
+    return ProviderInvocationFailure(
+        provider_name=provider_name,
+        model_name=model_name,
+        assurance_mode=MultimodalAssuranceMode.ATTACHMENT_ONLY,
+        category=category,
+        message=message,
+        status_code=status_code if isinstance(status_code, int) else None,
+        raw_response_payload=json_safe(getattr(exc, "body", None)),
+    )
+
+
+class LiteLLMMultimodalAdapter:
+    """LiteLLM adapter that sends prompt plus persisted images to a vision-capable model."""
+
+    provider_name = "litellm_multimodal"
+
+    def __init__(
+        self,
+        *,
+        completion_callable: Callable[..., Any] | None = None,
+        supports_vision_callable: Callable[..., bool] | None = None,
+        supports_response_schema_callable: Callable[..., bool] | None = None,
+    ) -> None:
+        self._completion_callable = completion_callable
+        self._supports_vision_callable = supports_vision_callable
+        self._supports_response_schema_callable = supports_response_schema_callable
+
+    def _default_completion_callable(self) -> Callable[..., Any]:
+        if self._completion_callable is not None:
+            return self._completion_callable
+        from litellm import completion
+
+        return cast(Callable[..., Any], completion)
+
+    def _supports_vision(self, *, model_name: str, custom_llm_provider: str | None) -> bool:
+        if self._supports_vision_callable is not None:
+            return bool(
+                self._supports_vision_callable(
+                    model_name,
+                    custom_llm_provider=custom_llm_provider,
+                )
+            )
+        from litellm import supports_vision
+
+        return bool(
+            supports_vision(
+                model_name,
+                custom_llm_provider=custom_llm_provider,
+            )
+        )
+
+    def _supports_response_schema(
+        self,
+        *,
+        model_name: str,
+        custom_llm_provider: str | None,
+    ) -> bool:
+        if self._supports_response_schema_callable is not None:
+            return bool(
+                self._supports_response_schema_callable(
+                    model_name,
+                    custom_llm_provider=custom_llm_provider,
+                )
+            )
+        from litellm import supports_response_schema
+
+        return bool(
+            supports_response_schema(
+                model_name,
+                custom_llm_provider=custom_llm_provider,
+            )
+        )
+
+    def invoke(
+        self,
+        request: ProviderInvocationRequest,
+        config: MultimodalGatewayConfig,
+    ) -> ProviderInvocationResult:
+        if config.provider.provider != self.provider_name:
+            return ProviderInvocationResult(
+                failure=ProviderInvocationFailure(
+                    provider_name=self.provider_name,
+                    model_name=request.model_name,
+                    assurance_mode=MultimodalAssuranceMode.ATTACHMENT_ONLY,
+                    category=MultimodalFailureCategory.UNSUPPORTED_CAPABILITY,
+                    message="LiteLLM multimodal adapter requires provider='litellm_multimodal'",
+                )
+        )
+
+        custom_llm_provider = config.provider.extra_body.get("custom_llm_provider")
+        provider_name = str(custom_llm_provider) if isinstance(custom_llm_provider, str) else None
+        if not self._supports_vision(
+            model_name=request.model_name,
+            custom_llm_provider=provider_name,
+        ):
+            return ProviderInvocationResult(
+                failure=ProviderInvocationFailure(
+                    provider_name=self.provider_name,
+                    model_name=request.model_name,
+                    assurance_mode=MultimodalAssuranceMode.ATTACHMENT_ONLY,
+                    category=MultimodalFailureCategory.UNSUPPORTED_CAPABILITY,
+                    message="configured LiteLLM model does not advertise vision support",
+                )
+            )
+        if not self._supports_response_schema(
+            model_name=request.model_name,
+            custom_llm_provider=provider_name,
+        ):
+            return ProviderInvocationResult(
+                failure=ProviderInvocationFailure(
+                    provider_name=self.provider_name,
+                    model_name=request.model_name,
+                    assurance_mode=MultimodalAssuranceMode.ATTACHMENT_ONLY,
+                    category=MultimodalFailureCategory.UNSUPPORTED_CAPABILITY,
+                    message="configured LiteLLM model does not advertise response_schema support",
+                )
+            )
+
+        messages: list[dict[str, object]] = [
+            {
+                "role": "user",
+                "content": [
+                    {"type": "text", "text": request.prompt},
+                    *(
+                        {
+                            "type": "image_url",
+                            "image_url": {"url": _image_data_url(region)},
+                        }
+                        for region in request.regions
+                    ),
+                ],
+            }
+        ]
+        call_kwargs: dict[str, Any] = {
+            "model": request.model_name,
+            "messages": messages,
+            "response_format": {
+                "type": "json_schema",
+                "json_schema": {
+                    "name": request.response_model_name,
+                    "schema": request.response_schema,
+                    "strict": True,
+                },
+            },
+        }
+        api_key_env_var = config.provider.api_key_env_var
+        if api_key_env_var is not None:
+            api_key = os.getenv(api_key_env_var)
+            if api_key is not None:
+                call_kwargs["api_key"] = api_key
+        call_kwargs.update(config.provider.extra_body)
+
+        try:
+            response = self._default_completion_callable()(
+                timeout=config.timeout_seconds,
+                **call_kwargs,
+            )
+        except Exception as exc:  # pragma: no cover - exercised with mocked callables
+            return ProviderInvocationResult(
+                failure=_normalize_exception(
+                    exc,
+                    provider_name=self.provider_name,
+                    model_name=request.model_name,
+                )
+            )
+
+        payload = _extract_response_json(response)
+        try:
+            structured_output = _extract_structured_output(payload)
+        except Exception as exc:
+            return ProviderInvocationResult(
+                failure=_normalize_exception(
+                    exc,
+                    provider_name=self.provider_name,
+                    model_name=request.model_name,
+                )
+            )
+
+        return ProviderInvocationResult(
+            success=ProviderInvocationSuccess(
+                provider_name=self.provider_name,
+                model_name=request.model_name,
+                assurance_mode=MultimodalAssuranceMode.ATTACHMENT_ONLY,
+                raw_response_payload=json_safe(payload),
+                structured_output_json=structured_output,
+                usage=_extract_usage(payload),
+                status_code=200,
+            )
+        )
+
+
+__all__ = ["LiteLLMMultimodalAdapter"]
diff --git a/src/nullvector/retrieval/__init__.py b/src/nullvector/retrieval/__init__.py
new file mode 100644
index 0000000..0160f7d
--- /dev/null
+++ b/src/nullvector/retrieval/__init__.py
@@ -0,0 +1,27 @@
+"""Retrieval corpus building, planning, ranking, and QA exports."""
+
+from nullvector.retrieval.build import RetrievalCorpusBuilder
+from nullvector.retrieval.enrichment import (
+    VisualAttachmentIndex,
+    augment_corpus_with_attachments,
+)
+from nullvector.retrieval.index import InMemoryRetrievalIndex
+from nullvector.retrieval.load import load_retrieval_corpus, load_retrieval_manifest
+from nullvector.retrieval.planner import QueryPlanner
+from nullvector.retrieval.qa import QAResponse, RetrievalQAService
+from nullvector.retrieval.rank import RetrievalRanker
+from nullvector.retrieval.service import RetrievalService
+
+__all__ = [
+    "InMemoryRetrievalIndex",
+    "QAResponse",
+    "QueryPlanner",
+    "RetrievalCorpusBuilder",
+    "RetrievalQAService",
+    "RetrievalRanker",
+    "RetrievalService",
+    "VisualAttachmentIndex",
+    "augment_corpus_with_attachments",
+    "load_retrieval_corpus",
+    "load_retrieval_manifest",
+]
diff --git a/src/nullvector/retrieval/build.py b/src/nullvector/retrieval/build.py
new file mode 100644
index 0000000..78a4a07
--- /dev/null
+++ b/src/nullvector/retrieval/build.py
@@ -0,0 +1,626 @@
+"""Build retrieval corpora from acquisition and tree artifacts."""
+
+from __future__ import annotations
+
+import hashlib
+import json
+from collections import Counter
+from pathlib import Path
+from typing import Any, cast
+
+from pydantic import BaseModel
+
+from nullvector.domain.common import PageSourceAnchor
+from nullvector.domain.events import ContentAuthoritativeness, SourceTrack, TrustTier
+from nullvector.domain.ledger import (
+    CanonicalDocumentLedger,
+    CanonicalTextPage,
+    CanonicalTextSubstrate,
+    TableArtifact,
+    UnresolvedRegion,
+    VisualArtifact,
+)
+from nullvector.domain.models import AcquisitionRunManifest, ContentSpan, PageSpan
+from nullvector.domain.retrieval import (
+    RetrievalCorpus,
+    RetrievalEvidence,
+    RetrievalManifest,
+    RetrievalModality,
+    RetrievalUnitType,
+)
+from nullvector.domain.tree import (
+    HierarchyNode,
+    NodeCard,
+    NodeSummary,
+    TreeBuildManifest,
+    UnassignedPageSpan,
+    VerificationReport,
+    VisualRegionReference,
+)
+from nullvector.runtime_validation import validate_canonical_text_substrate_contract
+
+
+def _json_safe(value: Any) -> Any:
+    if isinstance(value, BaseModel):
+        return value.model_dump(mode="json")
+    if isinstance(value, dict):
+        return {str(key): _json_safe(item) for key, item in value.items()}
+    if isinstance(value, list | tuple):
+        return [_json_safe(item) for item in value]
+    if isinstance(value, str | int | float | bool) or value is None:
+        return value
+    return str(value)
+
+
+def _read_json(path: Path) -> Any:
+    return json.loads(path.read_text(encoding="utf-8"))
+
+
+def _write_json(path: Path, payload: Any) -> str:
+    path.parent.mkdir(parents=True, exist_ok=True)
+    path.write_text(
+        json.dumps(_json_safe(payload), indent=2, sort_keys=True, ensure_ascii=True),
+        encoding="utf-8",
+    )
+    return str(path)
+
+
+def _resolve_artifact_path(root: Path, stored_path: str) -> Path:
+    path = Path(stored_path)
+    if path.is_absolute():
+        return path
+    return root / path
+
+
+def _unique_non_empty(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
+    ordered: list[str] = []
+    seen: set[str] = set()
+    for value in values:
+        normalized = " ".join(value.split()).strip()
+        if not normalized or normalized in seen:
+            continue
+        seen.add(normalized)
+        ordered.append(normalized)
+    return tuple(ordered)
+
+
+def _source_anchor_payloads(
+    anchors: tuple[PageSourceAnchor, ...],
+) -> tuple[dict[str, object], ...]:
+    return tuple(cast(dict[str, object], anchor.model_dump(mode="json")) for anchor in anchors)
+
+
+def _trust_tier_for_source(
+    *,
+    source_track: SourceTrack,
+    authoritativeness: ContentAuthoritativeness,
+    confidence: float | None,
+) -> TrustTier:
+    if source_track is SourceTrack.NATIVE:
+        if authoritativeness is ContentAuthoritativeness.AUTHORITATIVE:
+            return TrustTier.NATIVE_EXACT
+        return TrustTier.NATIVE_LAYOUT_BACKED
+    if source_track is SourceTrack.EXTERNAL_OCR:
+        if confidence is not None and confidence >= 0.9:
+            return TrustTier.EXTERNAL_OCR_HIGH
+        if confidence is not None and confidence >= 0.75:
+            return TrustTier.EXTERNAL_OCR_MEDIUM
+        return TrustTier.EXTERNAL_OCR_LOW
+    return TrustTier.VISUAL_INTERPRETIVE
+
+
+def _content_span_for_page(page: CanonicalTextPage) -> ContentSpan:
+    return ContentSpan(
+        start_page=page.page_index,
+        start_offset=0,
+        end_page=page.page_index,
+        end_offset=len(page.text),
+    )
+
+
+def _merge_content_spans(spans: tuple[ContentSpan, ...]) -> ContentSpan | None:
+    if not spans:
+        return None
+    ordered = sorted(
+        spans,
+        key=lambda span: (
+            span.start_page,
+            span.start_offset,
+            span.end_page,
+            span.end_offset,
+        ),
+    )
+    first = ordered[0]
+    last = ordered[-1]
+    return ContentSpan(
+        start_page=first.start_page,
+        start_offset=first.start_offset,
+        end_page=last.end_page,
+        end_offset=last.end_offset,
+    )
+
+
+def _text_for_content_span(
+    *,
+    pages_by_index: dict[int, CanonicalTextPage],
+    span: ContentSpan,
+) -> str:
+    parts: list[str] = []
+    for page_index in range(span.start_page, span.end_page + 1):
+        page = pages_by_index.get(page_index)
+        if page is None:
+            continue
+        start_offset = 0
+        end_offset = len(page.text)
+        if page_index == span.start_page:
+            start_offset = min(span.start_offset, len(page.text))
+        if page_index == span.end_page:
+            end_offset = min(span.end_offset, len(page.text))
+        if start_offset >= end_offset:
+            continue
+        parts.append(page.text[start_offset:end_offset])
+    return "\n".join(part for part in parts if part).strip()
+
+
+def _text_for_page_span(
+    *,
+    pages_by_index: dict[int, CanonicalTextPage],
+    page_span: PageSpan,
+) -> str:
+    parts = [
+        pages_by_index[page_index].text
+        for page_index in range(page_span.start_page, page_span.end_page + 1)
+        if page_index in pages_by_index and pages_by_index[page_index].text
+    ]
+    return "\n".join(parts).strip()
+
+
+def _default_retrieval_root(
+    *,
+    acquisition_manifest_path: Path,
+    acquisition_manifest: AcquisitionRunManifest,
+    tree_manifest: TreeBuildManifest | None,
+) -> Path:
+    retrieval_run_id = (
+        tree_manifest.tree_run_id
+        if tree_manifest is not None
+        else acquisition_manifest.acquisition_run_id
+    )
+    return acquisition_manifest_path.parent / "retrieval" / retrieval_run_id
+
+
+def _load_acquisition_manifest(path: Path) -> AcquisitionRunManifest:
+    return AcquisitionRunManifest.model_validate_json(path.read_text(encoding="utf-8"))
+
+
+def _load_tree_manifest(path: Path | None) -> TreeBuildManifest | None:
+    if path is None:
+        return None
+    return TreeBuildManifest.model_validate_json(path.read_text(encoding="utf-8"))
+
+
+def _load_ledger(
+    acquisition_manifest_path: Path,
+    acquisition_manifest: AcquisitionRunManifest,
+) -> CanonicalDocumentLedger:
+    ledger_path = _resolve_artifact_path(
+        Path(acquisition_manifest.artifact_root),
+        acquisition_manifest.ledger_path,
+    )
+    if not ledger_path.exists():
+        ledger_path = _resolve_artifact_path(
+            acquisition_manifest_path.parent,
+            acquisition_manifest.ledger_path,
+        )
+    return CanonicalDocumentLedger.model_validate_json(ledger_path.read_text(encoding="utf-8"))
+
+
+def _load_text_substrate(
+    acquisition_manifest_path: Path,
+    acquisition_manifest: AcquisitionRunManifest,
+) -> CanonicalTextSubstrate:
+    substrate_path = validate_canonical_text_substrate_contract(
+        acquisition_root=acquisition_manifest_path.parent,
+        manifest=acquisition_manifest,
+    )
+    return CanonicalTextSubstrate.model_validate_json(substrate_path.read_text(encoding="utf-8"))
+
+
+def _load_committed_nodes(tree_manifest: TreeBuildManifest | None) -> tuple[HierarchyNode, ...]:
+    if tree_manifest is None:
+        return ()
+    payload = cast(list[dict[str, Any]], _read_json(Path(tree_manifest.committed_hierarchy_path)))
+    return tuple(HierarchyNode.model_validate_json(json.dumps(item)) for item in payload)
+
+
+def _load_node_cards(tree_manifest: TreeBuildManifest | None) -> tuple[NodeCard, ...]:
+    if tree_manifest is None:
+        return ()
+    payload = cast(list[dict[str, Any]], _read_json(Path(tree_manifest.node_cards_path)))
+    return tuple(NodeCard.model_validate_json(json.dumps(item)) for item in payload)
+
+
+def _load_node_summaries(tree_manifest: TreeBuildManifest | None) -> tuple[NodeSummary, ...]:
+    if tree_manifest is None or tree_manifest.node_summaries_path is None:
+        return ()
+    payload = cast(list[dict[str, Any]], _read_json(Path(tree_manifest.node_summaries_path)))
+    return tuple(NodeSummary.model_validate_json(json.dumps(item)) for item in payload)
+
+
+def _load_verification_report(tree_manifest: TreeBuildManifest | None) -> VerificationReport | None:
+    if tree_manifest is None:
+        return None
+    return VerificationReport.model_validate_json(
+        Path(tree_manifest.verification_report_path).read_text(encoding="utf-8")
+    )
+
+
+def _load_unassigned_spans(
+    tree_manifest: TreeBuildManifest | None,
+) -> tuple[UnassignedPageSpan, ...]:
+    if tree_manifest is None:
+        return ()
+    payload = cast(list[dict[str, Any]], _read_json(Path(tree_manifest.unassigned_spans_path)))
+    return tuple(UnassignedPageSpan.model_validate_json(json.dumps(item)) for item in payload)
+
+
+def _build_page_units(
+    text_substrate: CanonicalTextSubstrate,
+) -> tuple[RetrievalEvidence, ...]:
+    units: list[RetrievalEvidence] = []
+    for page in sorted(text_substrate.pages, key=lambda item: item.page_index):
+        page_label = page.page_label or str(page.page_index + 1)
+        units.append(
+            RetrievalEvidence(
+                unit_id=f"page-text-{page.page_index:06d}",
+                document_id=text_substrate.document_id,
+                unit_type=RetrievalUnitType.PAGE_TEXT,
+                modality=RetrievalModality.TEXT,
+                page_span=PageSpan(start_page=page.page_index, end_page=page.page_index),
+                content_span=_content_span_for_page(page),
+                title=f"Page {page_label}",
+                text=page.text,
+                trust_tier=TrustTier.NATIVE_EXACT,
+                authoritative=True,
+                interpretive=False,
+                metadata={"page_label": page.page_label or page_label},
+            )
+        )
+    return tuple(units)
+
+
+def _build_table_units(
+    ledger: CanonicalDocumentLedger,
+) -> tuple[RetrievalEvidence, ...]:
+    units: list[RetrievalEvidence] = []
+    for page in ledger.pages:
+        for block in page.blocks:
+            if not isinstance(block, TableArtifact):
+                continue
+            text = block.markdown_projection or "\n".join(" | ".join(row) for row in block.rows)
+            units.append(
+                RetrievalEvidence(
+                    unit_id=block.table_id,
+                    document_id=ledger.document_id,
+                    unit_type=RetrievalUnitType.TABLE,
+                    modality=RetrievalModality.TABLE,
+                    page_span=PageSpan(start_page=page.page_index, end_page=page.page_index),
+                    title=f"Table {block.table_id}",
+                    text=text,
+                    trust_tier=_trust_tier_for_source(
+                        source_track=block.provenance.source_track,
+                        authoritativeness=block.provenance.content_authoritativeness,
+                        confidence=block.provenance.confidence,
+                    ),
+                    authoritative=True,
+                    interpretive=False,
+                    metadata={
+                        "bbox": block.bbox.model_dump(mode="json"),
+                        "row_count": len(block.rows),
+                    },
+                )
+            )
+    return tuple(units)
+
+
+def _visual_reference_from_block(
+    *,
+    document_id: str,
+    page_index: int,
+    visual_id: str,
+    bbox: Any,
+    image_ref: str | None,
+    asset_path: str | None,
+    page_render_path: str | None,
+    render_dpi: int | None,
+) -> VisualRegionReference:
+    return VisualRegionReference(
+        document_id=document_id,
+        page_index=page_index,
+        region_id=visual_id,
+        bbox=bbox,
+        image_ref=image_ref,
+        asset_path=asset_path,
+        page_render_path=page_render_path,
+        render_dpi=render_dpi,
+    )
+
+
+def _build_visual_units(
+    ledger: CanonicalDocumentLedger,
+) -> tuple[RetrievalEvidence, ...]:
+    units: list[RetrievalEvidence] = []
+    for page in ledger.pages:
+        for block in page.blocks:
+            if isinstance(block, VisualArtifact):
+                units.append(
+                    RetrievalEvidence(
+                        unit_id=block.visual_id,
+                        document_id=ledger.document_id,
+                        unit_type=RetrievalUnitType.VISUAL,
+                        modality=RetrievalModality.VISUAL,
+                        page_span=PageSpan(start_page=page.page_index, end_page=page.page_index),
+                        title=block.kind_hint,
+                        trust_tier=_trust_tier_for_source(
+                            source_track=block.provenance.source_track,
+                            authoritativeness=block.provenance.content_authoritativeness,
+                            confidence=block.provenance.confidence,
+                        ),
+                        authoritative=False,
+                        interpretive=False,
+                        visual_region=_visual_reference_from_block(
+                            document_id=ledger.document_id,
+                            page_index=page.page_index,
+                            visual_id=block.visual_id,
+                            bbox=block.bbox,
+                            image_ref=block.image_ref,
+                            asset_path=block.asset_path,
+                            page_render_path=block.page_render_path,
+                            render_dpi=block.render_dpi,
+                        ),
+                        asset_path=block.asset_path,
+                        page_render_path=block.page_render_path,
+                        metadata={
+                            "kind_hint": block.kind_hint,
+                            "bbox": block.bbox.model_dump(mode="json"),
+                            "needs_enrichment": block.needs_enrichment,
+                        },
+                    )
+                )
+            elif isinstance(block, UnresolvedRegion):
+                units.append(
+                    RetrievalEvidence(
+                        unit_id=block.region_id,
+                        document_id=ledger.document_id,
+                        unit_type=RetrievalUnitType.UNRESOLVED_VISUAL,
+                        modality=RetrievalModality.VISUAL,
+                        page_span=PageSpan(start_page=page.page_index, end_page=page.page_index),
+                        title=block.reason_code,
+                        trust_tier=_trust_tier_for_source(
+                            source_track=block.provenance.source_track,
+                            authoritativeness=block.provenance.content_authoritativeness,
+                            confidence=block.provenance.confidence,
+                        ),
+                        authoritative=False,
+                        interpretive=False,
+                        visual_region=_visual_reference_from_block(
+                            document_id=ledger.document_id,
+                            page_index=page.page_index,
+                            visual_id=block.region_id,
+                            bbox=block.bbox,
+                            image_ref=None,
+                            asset_path=block.asset_path,
+                            page_render_path=block.page_render_path,
+                            render_dpi=block.render_dpi,
+                        ),
+                        asset_path=block.asset_path,
+                        page_render_path=block.page_render_path,
+                        metadata={
+                            "bbox": block.bbox.model_dump(mode="json"),
+                            "reason_code": block.reason_code,
+                            "recommended_fallback": block.recommended_fallback,
+                            "severity": block.severity.value,
+                        },
+                    )
+                )
+    return tuple(units)
+
+
+def _build_node_text_units(
+    committed_nodes: tuple[HierarchyNode, ...],
+    text_substrate: CanonicalTextSubstrate,
+) -> tuple[RetrievalEvidence, ...]:
+    pages_by_index = {page.page_index: page for page in text_substrate.pages}
+    units: list[RetrievalEvidence] = []
+    for node in committed_nodes:
+        spans = tuple(owned_span.span for owned_span in node.owned_spans)
+        text_parts = [
+            _text_for_content_span(pages_by_index=pages_by_index, span=span)
+            for span in spans
+        ]
+        text = "\n".join(part for part in text_parts if part).strip() or None
+        units.append(
+            RetrievalEvidence(
+                unit_id=f"node-text-{node.node_id}",
+                document_id=node.document_id,
+                unit_type=RetrievalUnitType.NODE_TEXT,
+                modality=RetrievalModality.TEXT,
+                page_span=node.page_span,
+                content_span=_merge_content_spans(spans),
+                node_id=node.node_id,
+                title=node.title,
+                text=text,
+                keywords=_unique_non_empty(list(node.path)),
+                trust_tier=TrustTier.NATIVE_EXACT,
+                authoritative=True,
+                interpretive=False,
+                source_anchors=_source_anchor_payloads(node.source_anchors),
+                metadata={
+                    "level": node.level,
+                    "path": list(node.path),
+                    "verified": True,
+                    "owned_span_count": len(node.owned_spans),
+                },
+            )
+        )
+    return tuple(units)
+
+
+def _build_node_summary_units(
+    node_cards: tuple[NodeCard, ...],
+    node_summaries: tuple[NodeSummary, ...],
+) -> tuple[RetrievalEvidence, ...]:
+    cards_by_id = {node_card.node_id: node_card for node_card in node_cards}
+    units: list[RetrievalEvidence] = []
+    for summary in node_summaries:
+        node_card = cards_by_id.get(summary.node_id)
+        if node_card is None:
+            continue
+        spans = tuple(owned_span.span for owned_span in node_card.owned_spans)
+        units.append(
+            RetrievalEvidence(
+                unit_id=f"node-summary-{summary.node_id}",
+                document_id=node_card.document_id,
+                unit_type=RetrievalUnitType.NODE_SUMMARY,
+                modality=RetrievalModality.TEXT,
+                page_span=node_card.page_span,
+                content_span=_merge_content_spans(spans),
+                node_id=node_card.node_id,
+                title=node_card.title,
+                text=summary.summary,
+                keywords=summary.keywords,
+                authoritative=False,
+                interpretive=True,
+                source_anchors=_source_anchor_payloads(node_card.source_anchors),
+                metadata={
+                    "summary_method": summary.summary_method.value,
+                    "token_count": summary.token_count,
+                    "estimated_token_count": summary.estimated_token_count,
+                    "exact_token_count": summary.exact_token_count,
+                    "gateway_audit_path": summary.gateway_audit_path,
+                },
+            )
+        )
+    return tuple(units)
+
+
+def _build_unassigned_units(
+    *,
+    document_id: str,
+    text_substrate: CanonicalTextSubstrate,
+    unassigned_spans: tuple[UnassignedPageSpan, ...],
+) -> tuple[RetrievalEvidence, ...]:
+    pages_by_index = {page.page_index: page for page in text_substrate.pages}
+    units: list[RetrievalEvidence] = []
+    for index, span in enumerate(unassigned_spans):
+        units.append(
+            RetrievalEvidence(
+                unit_id=f"unassigned-span-{index:04d}",
+                document_id=document_id,
+                unit_type=RetrievalUnitType.UNASSIGNED_SPAN,
+                modality=RetrievalModality.TEXT,
+                page_span=span.page_span,
+                title=f"Unassigned span {span.page_span.start_page}-{span.page_span.end_page}",
+                text=_text_for_page_span(
+                    pages_by_index=pages_by_index,
+                    page_span=span.page_span,
+                )
+                or None,
+                keywords=(span.reason,),
+                trust_tier=TrustTier.NATIVE_EXACT,
+                authoritative=True,
+                interpretive=False,
+                metadata={"reason": span.reason},
+            )
+        )
+    return tuple(units)
+
+
+class RetrievalCorpusBuilder:
+    """Build and persist a retrieval corpus from acquisition and optional tree artifacts."""
+
+    def build(
+        self,
+        *,
+        acquisition_manifest_path: str,
+        tree_manifest_path: str | None = None,
+        artifact_root: str | None = None,
+    ) -> RetrievalManifest:
+        acquisition_manifest_file = Path(acquisition_manifest_path).resolve()
+        acquisition_manifest = _load_acquisition_manifest(acquisition_manifest_file)
+        tree_manifest = _load_tree_manifest(
+            Path(tree_manifest_path).resolve() if tree_manifest_path is not None else None
+        )
+        ledger = _load_ledger(acquisition_manifest_file, acquisition_manifest)
+        text_substrate = _load_text_substrate(acquisition_manifest_file, acquisition_manifest)
+        committed_nodes = _load_committed_nodes(tree_manifest)
+        node_cards = _load_node_cards(tree_manifest)
+        node_summaries = _load_node_summaries(tree_manifest)
+        verification_report = _load_verification_report(tree_manifest)
+        unassigned_spans = _load_unassigned_spans(tree_manifest)
+
+        units = (
+            *_build_page_units(text_substrate),
+            *_build_table_units(ledger),
+            *_build_visual_units(ledger),
+            *_build_node_text_units(committed_nodes, text_substrate),
+            *_build_node_summary_units(node_cards, node_summaries),
+            *_build_unassigned_units(
+                document_id=acquisition_manifest.document_id,
+                text_substrate=text_substrate,
+                unassigned_spans=unassigned_spans,
+            ),
+        )
+        corpus = RetrievalCorpus(
+            document_id=acquisition_manifest.document_id,
+            units=tuple(units),
+        )
+
+        retrieval_root = (
+            Path(artifact_root).resolve()
+            if artifact_root is not None
+            else _default_retrieval_root(
+                acquisition_manifest_path=acquisition_manifest_file,
+                acquisition_manifest=acquisition_manifest,
+                tree_manifest=tree_manifest,
+            )
+        )
+        corpus_path = _write_json(retrieval_root / "corpus.json", corpus)
+        counts_by_type = Counter(unit.unit_type.value for unit in corpus.units)
+        counts_by_modality = Counter(unit.modality.value for unit in corpus.units)
+        stats_path = _write_json(
+            retrieval_root / "stats.json",
+            {
+                "document_id": corpus.document_id,
+                "unit_count": len(corpus.units),
+                "counts_by_type": dict(sorted(counts_by_type.items())),
+                "counts_by_modality": dict(sorted(counts_by_modality.items())),
+                "tree_artifacts_loaded": tree_manifest is not None,
+                "verification_status": (
+                    verification_report.status.value if verification_report is not None else None
+                ),
+                "has_node_summaries": bool(node_summaries),
+                "has_unassigned_spans": bool(unassigned_spans),
+                "corpus_sha256": hashlib.sha256(
+                    json.dumps(
+                        _json_safe(corpus),
+                        sort_keys=True,
+                        ensure_ascii=True,
+                    ).encode("utf-8")
+                ).hexdigest(),
+            },
+        )
+        manifest = RetrievalManifest(
+            document_id=corpus.document_id,
+            artifact_root=str(retrieval_root),
+            corpus_path=corpus_path,
+            stats_path=stats_path,
+            unit_count=len(corpus.units),
+        )
+        _write_json(retrieval_root / "manifest.json", manifest)
+        return manifest
+
+
+__all__ = [
+    "RetrievalCorpusBuilder",
+]
diff --git a/src/nullvector/retrieval/enrichment.py b/src/nullvector/retrieval/enrichment.py
new file mode 100644
index 0000000..0ddb3c5
--- /dev/null
+++ b/src/nullvector/retrieval/enrichment.py
@@ -0,0 +1,67 @@
+"""Cached visual enrichment helpers for retrieval units."""
+
+from __future__ import annotations
+
+from nullvector.domain.retrieval import RetrievalCorpus, RetrievalEvidence, RetrievalUnitType
+from nullvector.domain.tree import VisualEnrichmentAttachment
+
+
+class VisualAttachmentIndex:
+    """Fast region-id lookup over cached visual enrichment attachments."""
+
+    def __init__(self, attachments: tuple[VisualEnrichmentAttachment, ...]) -> None:
+        self._attachments_by_region = {
+            attachment.region_id: attachment for attachment in attachments
+        }
+
+    def get_for_region(self, region_id: str) -> VisualEnrichmentAttachment | None:
+        return self._attachments_by_region.get(region_id)
+
+    def augment_unit(self, unit: RetrievalEvidence) -> RetrievalEvidence:
+        if unit.unit_type not in {
+            RetrievalUnitType.VISUAL,
+            RetrievalUnitType.UNRESOLVED_VISUAL,
+        }:
+            return unit
+        if unit.visual_region is None:
+            return unit
+        attachment = self.get_for_region(unit.visual_region.region_id)
+        if attachment is None:
+            return unit
+        keywords = tuple(label for label in attachment.insight.labels if label)
+        metadata = dict(unit.metadata)
+        metadata.update(
+            {
+                "attachment_id": attachment.attachment_id,
+                "attachment_audit_path": attachment.audit_path,
+                "attachment_attributes": dict(attachment.insight.attributes),
+                "attachment_confidence": attachment.confidence,
+            }
+        )
+        return unit.model_copy(
+            update={
+                "text": attachment.insight.summary,
+                "keywords": keywords or unit.keywords,
+                "interpretive": True,
+                "metadata": metadata,
+            }
+        )
+
+
+def augment_corpus_with_attachments(
+    *,
+    corpus: RetrievalCorpus,
+    attachments: tuple[VisualEnrichmentAttachment, ...],
+) -> RetrievalCorpus:
+    """Return a corpus copy with cached visual attachments folded into visual units."""
+
+    index = VisualAttachmentIndex(attachments)
+    return corpus.model_copy(
+        update={"units": tuple(index.augment_unit(unit) for unit in corpus.units)}
+    )
+
+
+__all__ = [
+    "VisualAttachmentIndex",
+    "augment_corpus_with_attachments",
+]
diff --git a/src/nullvector/retrieval/index.py b/src/nullvector/retrieval/index.py
new file mode 100644
index 0000000..005cb08
--- /dev/null
+++ b/src/nullvector/retrieval/index.py
@@ -0,0 +1,109 @@
+"""Vectorless in-memory retrieval index."""
+
+from __future__ import annotations
+
+import string
+from collections import defaultdict
+
+from nullvector.domain.models import PageSpan
+from nullvector.domain.retrieval import QueryPlan, RetrievalCorpus, RetrievalEvidence
+
+_PUNCTUATION_TABLE = str.maketrans({character: " " for character in string.punctuation})
+
+
+def _normalize_text(value: str) -> str:
+    return " ".join(value.casefold().translate(_PUNCTUATION_TABLE).split())
+
+
+def _tokenize(value: str) -> tuple[str, ...]:
+    normalized = _normalize_text(value)
+    return tuple(token for token in normalized.split() if token)
+
+
+def _intersects(left: PageSpan, right: PageSpan) -> bool:
+    return not (left.end_page < right.start_page or right.end_page < left.start_page)
+
+
+class InMemoryRetrievalIndex:
+    """Simple postings-based index over one retrieval corpus."""
+
+    def __init__(self, corpus: RetrievalCorpus) -> None:
+        self._corpus = corpus
+        self._token_postings: dict[str, tuple[str, ...]] = {}
+        self._title_postings: dict[str, tuple[str, ...]] = {}
+        self._keyword_postings: dict[str, tuple[str, ...]] = {}
+        self._page_number_lookup: dict[int, tuple[str, ...]] = {}
+        self._node_id_lookup: dict[str, tuple[str, ...]] = {}
+        self._units_by_id = {unit.unit_id: unit for unit in corpus.units}
+        self._build_indexes()
+
+    @property
+    def corpus(self) -> RetrievalCorpus:
+        return self._corpus
+
+    def filter_units(self, plan: QueryPlan) -> tuple[RetrievalEvidence, ...]:
+        candidates = self._corpus.units
+        if plan.page_filter is not None:
+            page_filter = plan.page_filter
+            candidates = tuple(
+                unit
+                for unit in candidates
+                if _intersects(unit.page_span, page_filter)
+            )
+        if plan.unit_types:
+            allowed_types = set(plan.unit_types)
+            candidates = tuple(unit for unit in candidates if unit.unit_type in allowed_types)
+        if plan.modality_filters:
+            allowed_modalities = set(plan.modality_filters)
+            candidates = tuple(unit for unit in candidates if unit.modality in allowed_modalities)
+        return candidates
+
+    def postings(self, token: str) -> tuple[str, ...]:
+        return self._token_postings.get(_normalize_text(token), ())
+
+    def _build_indexes(self) -> None:
+        token_postings: dict[str, set[str]] = defaultdict(set)
+        title_postings: dict[str, set[str]] = defaultdict(set)
+        keyword_postings: dict[str, set[str]] = defaultdict(set)
+        page_number_lookup: dict[int, set[str]] = defaultdict(set)
+        node_id_lookup: dict[str, set[str]] = defaultdict(set)
+
+        for unit in self._corpus.units:
+            for page_index in range(unit.page_span.start_page, unit.page_span.end_page + 1):
+                page_number_lookup[page_index].add(unit.unit_id)
+            if unit.node_id is not None:
+                node_id_lookup[unit.node_id].add(unit.unit_id)
+
+            token_source = " ".join(
+                part
+                for part in (unit.title or "", unit.text or "", " ".join(unit.keywords))
+                if part
+            )
+            for token in _tokenize(token_source):
+                token_postings[token].add(unit.unit_id)
+            if unit.title is not None:
+                for token in _tokenize(unit.title):
+                    title_postings[token].add(unit.unit_id)
+            for keyword in unit.keywords:
+                for token in _tokenize(keyword):
+                    keyword_postings[token].add(unit.unit_id)
+
+        self._token_postings = {
+            token: tuple(sorted(unit_ids)) for token, unit_ids in token_postings.items()
+        }
+        self._title_postings = {
+            token: tuple(sorted(unit_ids)) for token, unit_ids in title_postings.items()
+        }
+        self._keyword_postings = {
+            token: tuple(sorted(unit_ids)) for token, unit_ids in keyword_postings.items()
+        }
+        self._page_number_lookup = {
+            page_index: tuple(sorted(unit_ids))
+            for page_index, unit_ids in page_number_lookup.items()
+        }
+        self._node_id_lookup = {
+            node_id: tuple(sorted(unit_ids)) for node_id, unit_ids in node_id_lookup.items()
+        }
+
+
+__all__ = ["InMemoryRetrievalIndex"]
diff --git a/src/nullvector/retrieval/load.py b/src/nullvector/retrieval/load.py
new file mode 100644
index 0000000..eb12030
--- /dev/null
+++ b/src/nullvector/retrieval/load.py
@@ -0,0 +1,27 @@
+"""Artifact loaders for retrieval manifests and corpora."""
+
+from __future__ import annotations
+
+from pathlib import Path
+
+from nullvector.domain.retrieval import RetrievalCorpus, RetrievalManifest
+
+
+def load_retrieval_manifest(path: str | Path) -> RetrievalManifest:
+    """Load a persisted retrieval manifest from JSON."""
+
+    manifest_path = Path(path)
+    return RetrievalManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
+
+
+def load_retrieval_corpus(path: str | Path) -> RetrievalCorpus:
+    """Load a persisted retrieval corpus from JSON."""
+
+    corpus_path = Path(path)
+    return RetrievalCorpus.model_validate_json(corpus_path.read_text(encoding="utf-8"))
+
+
+__all__ = [
+    "load_retrieval_corpus",
+    "load_retrieval_manifest",
+]
diff --git a/src/nullvector/retrieval/planner.py b/src/nullvector/retrieval/planner.py
new file mode 100644
index 0000000..0a798d1
--- /dev/null
+++ b/src/nullvector/retrieval/planner.py
@@ -0,0 +1,128 @@
+"""Deterministic query planning for retrieval."""
+
+from __future__ import annotations
+
+import re
+import string
+
+from nullvector.domain.models import PageSpan
+from nullvector.domain.retrieval import (
+    QueryPlan,
+    RetrievalModality,
+    RetrievalUnitType,
+)
+
+_QUOTED_PATTERN = re.compile(r"['\"]([^'\"]+)['\"]")
+_PAGE_NUMBER_PATTERN = re.compile(r"\bpage\s+(?P<number>\d+)\b")
+_STRUCTURAL_PATTERN = re.compile(r"\b(?:section|chapter|appendix|heading)\s+[a-z0-9][a-z0-9 .:-]*")
+_PUNCTUATION_TABLE = str.maketrans({character: " " for character in string.punctuation})
+_VISUAL_TERMS = ("image", "photo", "figure", "diagram", "chart", "illustration")
+_TABLE_TERMS = ("table", "tabular")
+
+
+def _collapse_whitespace(value: str) -> str:
+    return " ".join(value.split()).strip()
+
+
+def _normalize_phrase(value: str) -> str:
+    return _collapse_whitespace(value.casefold().translate(_PUNCTUATION_TABLE))
+
+
+def _dedupe(values: list[str]) -> tuple[str, ...]:
+    ordered: list[str] = []
+    seen: set[str] = set()
+    for value in values:
+        normalized = _collapse_whitespace(value)
+        if not normalized or normalized in seen:
+            continue
+        seen.add(normalized)
+        ordered.append(normalized)
+    return tuple(ordered)
+
+
+def _quoted_phrases(query: str) -> tuple[str, ...]:
+    return _dedupe([_normalize_phrase(match.group(1)) for match in _QUOTED_PATTERN.finditer(query)])
+
+
+def _page_filter(normalized_query: str) -> PageSpan | None:
+    if "first page" in normalized_query:
+        return PageSpan(start_page=0, end_page=0)
+
+    page_match = _PAGE_NUMBER_PATTERN.search(normalized_query)
+    if page_match is None:
+        return None
+
+    page_number = int(page_match.group("number"))
+    page_index = 0 if page_number <= 1 else page_number - 1
+    return PageSpan(start_page=page_index, end_page=page_index)
+
+
+def _title_like_phrases(
+    *,
+    normalized_query: str,
+    quoted_phrases: tuple[str, ...],
+) -> tuple[str, ...]:
+    phrases = list(quoted_phrases)
+    phrases.extend(
+        _normalize_phrase(match.group(0))
+        for match in _STRUCTURAL_PATTERN.finditer(normalized_query)
+    )
+    return _dedupe(phrases)
+
+
+class QueryPlanner:
+    """Deterministic planner that extracts page, modality, and structural intent."""
+
+    def plan(self, query: str) -> QueryPlan:
+        normalized_query = _normalize_phrase(query)
+        quoted_phrases = _quoted_phrases(query)
+        title_like_phrases = _title_like_phrases(
+            normalized_query=normalized_query,
+            quoted_phrases=quoted_phrases,
+        )
+        visual_query = any(term in normalized_query.split() for term in _VISUAL_TERMS)
+        table_query = any(term in normalized_query.split() for term in _TABLE_TERMS)
+        structural_query = bool(
+            title_like_phrases
+            or quoted_phrases
+            or any(
+                term in normalized_query
+                for term in ("section", "chapter", "appendix", "heading")
+            )
+        )
+
+        unit_types: tuple[RetrievalUnitType, ...] = ()
+        modality_filters: tuple[RetrievalModality, ...] = ()
+        if visual_query:
+            unit_types = (
+                RetrievalUnitType.VISUAL,
+                RetrievalUnitType.UNRESOLVED_VISUAL,
+            )
+            modality_filters = (RetrievalModality.VISUAL,)
+        elif table_query:
+            unit_types = (RetrievalUnitType.TABLE,)
+            modality_filters = (RetrievalModality.TABLE,)
+        elif structural_query:
+            unit_types = (
+                RetrievalUnitType.NODE_TEXT,
+                RetrievalUnitType.NODE_SUMMARY,
+                RetrievalUnitType.UNASSIGNED_SPAN,
+                RetrievalUnitType.PAGE_TEXT,
+            )
+
+        return QueryPlan(
+            raw_query=query,
+            normalized_query=normalized_query,
+            page_filter=_page_filter(normalized_query),
+            unit_types=unit_types,
+            modality_filters=modality_filters,
+            title_like_phrases=title_like_phrases,
+            quoted_phrases=quoted_phrases,
+            structural_query=structural_query,
+            visual_query=visual_query,
+            table_query=table_query,
+            requires_multimodal=visual_query,
+        )
+
+
+__all__ = ["QueryPlanner"]
diff --git a/src/nullvector/retrieval/qa.py b/src/nullvector/retrieval/qa.py
new file mode 100644
index 0000000..583262d
--- /dev/null
+++ b/src/nullvector/retrieval/qa.py
@@ -0,0 +1,198 @@
+"""Answer synthesis over retrieval hits."""
+
+from __future__ import annotations
+
+import hashlib
+import string
+
+from nullvector.domain.common import NonEmptyStr, StrataModel
+from nullvector.domain.retrieval import (
+    AnswerCitation,
+    RetrievalCorpus,
+    RetrievalHit,
+    RetrievalUnitType,
+)
+from nullvector.domain.tree import VisualEnrichmentRequest
+from nullvector.retrieval.service import RetrievalService
+
+_PUNCTUATION_TABLE = str.maketrans({character: " " for character in string.punctuation})
+
+
+def _normalize_text(value: str) -> str:
+    return " ".join(value.casefold().translate(_PUNCTUATION_TABLE).split())
+
+
+def _excerpt_for_hit(hit: RetrievalHit, query: str) -> str | None:
+    text = hit.unit.text
+    if text is None or not text.strip():
+        return None
+    normalized_query_terms = tuple(term for term in _normalize_text(query).split() if term)
+    best_line = ""
+    best_score = -1
+    for line in text.splitlines():
+        stripped = line.strip()
+        if not stripped:
+            continue
+        line_terms = set(_normalize_text(stripped).split())
+        score = len(set(normalized_query_terms) & line_terms)
+        if score > best_score:
+            best_line = stripped
+            best_score = score
+    excerpt = best_line or text.strip().splitlines()[0]
+    return excerpt[:280]
+
+
+class QAResponse(StrataModel):
+    """Grounded answer payload returned by retrieval QA."""
+
+    answer: NonEmptyStr
+    citations: tuple[AnswerCitation, ...] = ()
+    retrieval_hits: tuple[RetrievalHit, ...] = ()
+    answer_mode: NonEmptyStr
+
+
+class RetrievalQAService:
+    """Synthesize grounded answers from retrieval hits."""
+
+    def __init__(
+        self,
+        retrieval_service: RetrievalService,
+        multimodal_service: object | None = None,
+    ) -> None:
+        self._retrieval_service = retrieval_service
+        self._multimodal_service = multimodal_service
+
+    def answer(
+        self,
+        *,
+        corpus: RetrievalCorpus,
+        query: str,
+        limit: int = 5,
+    ) -> QAResponse:
+        plan = self._retrieval_service.plan(corpus=corpus, query=query)
+        hits = self._retrieval_service.search(corpus=corpus, query=query, limit=limit)
+        if not hits:
+            return QAResponse(
+                answer="No grounded evidence was found in the current corpus.",
+                citations=(),
+                retrieval_hits=(),
+                answer_mode="no_hits",
+            )
+
+        if plan.visual_query:
+            visual_hits = tuple(
+                hit
+                for hit in hits
+                if hit.unit.unit_type in {
+                    RetrievalUnitType.VISUAL,
+                    RetrievalUnitType.UNRESOLVED_VISUAL,
+                }
+            )
+            if not visual_hits:
+                return QAResponse(
+                    answer="No visual evidence was found for the requested scope.",
+                    citations=(),
+                    retrieval_hits=hits,
+                    answer_mode="visual_no_hits",
+                )
+            top_visual = visual_hits[0]
+            if top_visual.unit.text and top_visual.unit.interpretive:
+                return QAResponse(
+                    answer=top_visual.unit.text,
+                    citations=(self._citation_for_hit(top_visual, query=query),),
+                    retrieval_hits=hits,
+                    answer_mode="cached_visual_attachment",
+                )
+            if self._multimodal_service is not None and top_visual.unit.visual_region is not None:
+                enriched = self._enrich_visual_hit(hit=top_visual, query=query)
+                if enriched is not None:
+                    return enriched
+            page_index = top_visual.unit.page_span.start_page
+            return QAResponse(
+                answer=(
+                    f"Page {page_index} contains visual evidence, but no grounded visual "
+                    "interpretation is available in the current corpus."
+                ),
+                citations=(self._citation_for_hit(top_visual, query=query),),
+                retrieval_hits=hits,
+                answer_mode="visual_interpretation_unavailable",
+            )
+
+        authoritative_hits = tuple(
+            hit
+            for hit in hits
+            if hit.unit.authoritative
+            and hit.unit.unit_type
+            in {
+                RetrievalUnitType.PAGE_TEXT,
+                RetrievalUnitType.NODE_TEXT,
+                RetrievalUnitType.TABLE,
+                RetrievalUnitType.UNASSIGNED_SPAN,
+            }
+        )
+        chosen_hit = authoritative_hits[0] if authoritative_hits else hits[0]
+        answer = (
+            _excerpt_for_hit(chosen_hit, query)
+            or chosen_hit.unit.title
+            or "Grounded evidence was found, but no answerable text excerpt is available."
+        )
+        citations_source = authoritative_hits[:3] if authoritative_hits else hits[:1]
+        return QAResponse(
+            answer=answer,
+            citations=tuple(self._citation_for_hit(hit, query=query) for hit in citations_source),
+            retrieval_hits=hits,
+            answer_mode="authoritative_text"
+            if authoritative_hits
+            else "interpretive_fallback",
+        )
+
+    def _citation_for_hit(self, hit: RetrievalHit, *, query: str) -> AnswerCitation:
+        return AnswerCitation(
+            document_id=hit.unit.document_id,
+            unit_id=hit.unit.unit_id,
+            page_span=hit.unit.page_span,
+            node_id=hit.unit.node_id,
+            quote=_excerpt_for_hit(hit, query),
+            asset_path=hit.unit.asset_path,
+        )
+
+    def _enrich_visual_hit(self, *, hit: RetrievalHit, query: str) -> QAResponse | None:
+        if self._multimodal_service is None or hit.unit.visual_region is None:
+            return None
+        enrich = getattr(self._multimodal_service, "enrich", None)
+        if not callable(enrich):
+            return None
+        request_id = hashlib.sha256(f"{hit.unit.unit_id}|{query}".encode()).hexdigest()[:24]
+        attachment = enrich(
+            VisualEnrichmentRequest(
+                request_id=request_id,
+                region=hit.unit.visual_region,
+                prompt=(
+                    "Answer the user's question strictly from the provided visual evidence. "
+                    f"Question: {query}"
+                ),
+                node_id=hit.unit.node_id,
+                metadata={"query": query},
+            )
+        )
+        return QAResponse(
+            answer=attachment.insight.summary,
+            citations=(
+                AnswerCitation(
+                    document_id=hit.unit.document_id,
+                    unit_id=hit.unit.unit_id,
+                    page_span=hit.unit.page_span,
+                    node_id=hit.unit.node_id,
+                    quote=attachment.insight.summary,
+                    asset_path=hit.unit.asset_path or hit.unit.page_render_path,
+                ),
+            ),
+            retrieval_hits=(hit,),
+            answer_mode="live_multimodal_enrichment",
+        )
+
+
+__all__ = [
+    "QAResponse",
+    "RetrievalQAService",
+]
diff --git a/src/nullvector/retrieval/rank.py b/src/nullvector/retrieval/rank.py
new file mode 100644
index 0000000..4ec95ef
--- /dev/null
+++ b/src/nullvector/retrieval/rank.py
@@ -0,0 +1,199 @@
+"""Deterministic ranking for retrieval candidates."""
+
+from __future__ import annotations
+
+import string
+
+from nullvector.domain.models import PageSpan
+from nullvector.domain.retrieval import (
+    QueryPlan,
+    RetrievalEvidence,
+    RetrievalHit,
+    RetrievalUnitType,
+)
+
+_PUNCTUATION_TABLE = str.maketrans({character: " " for character in string.punctuation})
+_STOPWORDS = {
+    "a",
+    "about",
+    "an",
+    "the",
+    "is",
+    "of",
+    "on",
+    "what",
+    "which",
+    "who",
+    "where",
+    "when",
+    "why",
+}
+
+
+def _normalize_text(value: str) -> str:
+    return " ".join(value.casefold().translate(_PUNCTUATION_TABLE).split())
+
+
+def _tokenize(value: str) -> tuple[str, ...]:
+    normalized = _normalize_text(value)
+    return tuple(token for token in normalized.split() if token and token not in _STOPWORDS)
+
+
+def _intersects(left: PageSpan, right: PageSpan) -> bool:
+    return not (left.end_page < right.start_page or right.end_page < left.start_page)
+
+
+def _contains_phrase(candidate: RetrievalEvidence, phrase: str) -> bool:
+    haystacks = [candidate.title or "", candidate.text or ""]
+    normalized_phrase = _normalize_text(phrase)
+    return any(normalized_phrase in _normalize_text(value) for value in haystacks if value)
+
+
+def _matched_terms(
+    *,
+    query_tokens: tuple[str, ...],
+    candidate: RetrievalEvidence,
+    quoted_phrases: tuple[str, ...],
+) -> tuple[str, ...]:
+    terms: list[str] = []
+    candidate_tokens = set(
+        _tokenize(
+            " ".join(part for part in (candidate.title or "", candidate.text or "") if part)
+        )
+    )
+    for token in query_tokens:
+        if token in candidate_tokens and token not in terms:
+            terms.append(token)
+    for phrase in quoted_phrases:
+        if _contains_phrase(candidate, phrase) and phrase not in terms:
+            terms.append(phrase)
+    return tuple(terms)
+
+
+class RetrievalRanker:
+    """Deterministic scorer over already-filtered retrieval evidence."""
+
+    def rank(
+        self,
+        *,
+        query: str,
+        plan: QueryPlan,
+        candidates: tuple[RetrievalEvidence, ...],
+    ) -> tuple[RetrievalHit, ...]:
+        query_tokens = _tokenize(query)
+        hits: list[RetrievalHit] = []
+
+        for candidate in candidates:
+            breakdown: dict[str, float] = {}
+
+            if plan.page_filter is not None:
+                if candidate.page_span == plan.page_filter:
+                    breakdown["page_exact"] = 12.0
+                elif _intersects(candidate.page_span, plan.page_filter):
+                    breakdown["page_overlap"] = 6.0
+                else:
+                    breakdown["page_miss_penalty"] = -12.0
+
+            if plan.modality_filters:
+                if candidate.modality in set(plan.modality_filters):
+                    breakdown["modality_match"] = 10.0
+                else:
+                    breakdown["modality_mismatch_penalty"] = -10.0
+
+            if plan.visual_query:
+                if candidate.unit_type in {
+                    RetrievalUnitType.VISUAL,
+                    RetrievalUnitType.UNRESOLVED_VISUAL,
+                }:
+                    breakdown["visual_intent_match"] = 8.0
+                else:
+                    breakdown["visual_intent_penalty"] = -14.0
+
+            if plan.table_query:
+                if candidate.unit_type is RetrievalUnitType.TABLE:
+                    breakdown["table_intent_match"] = 8.0
+                else:
+                    breakdown["table_intent_penalty"] = -8.0
+
+            quoted_matches = sum(
+                1 for phrase in plan.quoted_phrases if _contains_phrase(candidate, phrase)
+            )
+            if quoted_matches:
+                breakdown["quoted_phrase_match"] = 12.0 * quoted_matches
+
+            title_matches = 0.0
+            normalized_title = _normalize_text(candidate.title or "")
+            for phrase in plan.title_like_phrases:
+                normalized_phrase = _normalize_text(phrase)
+                if normalized_phrase and normalized_phrase == normalized_title:
+                    title_matches += 1
+                elif normalized_phrase and normalized_phrase in normalized_title:
+                    title_matches += 0.5
+            if title_matches:
+                breakdown["title_match"] = 8.0 * title_matches
+
+            keyword_overlap = len(set(query_tokens) & set(_tokenize(" ".join(candidate.keywords))))
+            if keyword_overlap:
+                breakdown["keyword_overlap"] = 2.0 * keyword_overlap
+
+            token_overlap = len(
+                set(query_tokens)
+                & set(
+                    _tokenize(
+                        " ".join(
+                            part for part in (candidate.title or "", candidate.text or "") if part
+                        )
+                    )
+                )
+            )
+            if token_overlap:
+                breakdown["token_overlap"] = 1.5 * token_overlap
+
+            if candidate.authoritative:
+                breakdown["authoritative_bonus"] = 2.0
+            if (
+                candidate.unit_type is RetrievalUnitType.NODE_TEXT
+                and candidate.metadata.get("verified") is True
+            ):
+                breakdown["verified_node_bonus"] = 1.5
+            if candidate.unit_type is RetrievalUnitType.NODE_SUMMARY:
+                breakdown["summary_penalty"] = -2.5
+            if candidate.interpretive and not plan.visual_query:
+                breakdown["interpretive_penalty"] = -5.0
+            if candidate.unit_type is RetrievalUnitType.UNRESOLVED_VISUAL and not candidate.text:
+                breakdown["unresolved_visual_penalty"] = -3.0
+            if candidate.text in (None, "") and candidate.unit_type not in {
+                RetrievalUnitType.VISUAL,
+                RetrievalUnitType.UNRESOLVED_VISUAL,
+            }:
+                breakdown["empty_text_penalty"] = -4.0
+
+            score = sum(breakdown.values())
+            hits.append(
+                RetrievalHit(
+                    unit=candidate,
+                    score=score,
+                    score_breakdown=breakdown,
+                    matched_terms=_matched_terms(
+                        query_tokens=query_tokens,
+                        candidate=candidate,
+                        quoted_phrases=plan.quoted_phrases,
+                    ),
+                )
+            )
+
+        return tuple(
+            sorted(
+                hits,
+                key=lambda hit: (
+                    hit.score,
+                    hit.unit.authoritative,
+                    hit.unit.unit_type.value,
+                    hit.unit.unit_id,
+                ),
+                reverse=True,
+            )
+        )
+
+
+__all__ = ["RetrievalRanker"]
diff --git a/src/nullvector/retrieval/service.py b/src/nullvector/retrieval/service.py
new file mode 100644
index 0000000..499738e
--- /dev/null
+++ b/src/nullvector/retrieval/service.py
@@ -0,0 +1,161 @@
+"""Retrieval orchestration over a persisted corpus."""
+
+from __future__ import annotations
+
+from nullvector.domain.models import PageSpan
+from nullvector.domain.retrieval import (
+    QueryPlan,
+    RetrievalCorpus,
+    RetrievalEvidence,
+    RetrievalHit,
+    RetrievalUnitType,
+)
+from nullvector.retrieval.index import InMemoryRetrievalIndex
+from nullvector.retrieval.planner import QueryPlanner
+from nullvector.retrieval.rank import RetrievalRanker
+
+
+def _intersects(unit: RetrievalEvidence, page_span: PageSpan) -> bool:
+    return not (
+        unit.page_span.end_page < page_span.start_page
+        or page_span.end_page < unit.page_span.start_page
+    )
+
+
+def _dedupe_units(units: tuple[RetrievalEvidence, ...]) -> tuple[RetrievalEvidence, ...]:
+    deduped: list[RetrievalEvidence] = []
+    seen: set[str] = set()
+    for unit in units:
+        if unit.unit_id in seen:
+            continue
+        seen.add(unit.unit_id)
+        deduped.append(unit)
+    return tuple(deduped)
+
+
+class RetrievalService:
+    """Query planning, filtering, widening, and ranking over one corpus."""
+
+    def __init__(
+        self,
+        planner: QueryPlanner,
+        ranker: RetrievalRanker,
+    ) -> None:
+        self._planner = planner
+        self._ranker = ranker
+
+    def plan(self, *, corpus: RetrievalCorpus, query: str) -> QueryPlan:
+        plan = self._planner.plan(query)
+        if plan.page_filter is None and "last page" in plan.normalized_query:
+            max_page = max((unit.page_span.end_page for unit in corpus.units), default=0)
+            return plan.model_copy(
+                update={"page_filter": PageSpan(start_page=max_page, end_page=max_page)}
+            )
+        return plan
+
+    def search(
+        self,
+        *,
+        corpus: RetrievalCorpus,
+        query: str,
+        limit: int = 10,
+    ) -> tuple[RetrievalHit, ...]:
+        plan = self.plan(corpus=corpus, query=query)
+        index = InMemoryRetrievalIndex(corpus)
+        candidates = index.filter_units(plan)
+        if not candidates:
+            candidates = self._widen_candidates(corpus=corpus, plan=plan)
+        if not candidates:
+            return ()
+        ranked = self._ranker.rank(query=query, plan=plan, candidates=candidates)
+        return ranked[:limit]
+
+    def _widen_candidates(
+        self,
+        *,
+        corpus: RetrievalCorpus,
+        plan: QueryPlan,
+    ) -> tuple[RetrievalEvidence, ...]:
+        if plan.visual_query:
+            if plan.page_filter is not None:
+                same_page_visual = tuple(
+                    unit
+                    for unit in corpus.units
+                    if _intersects(unit, plan.page_filter)
+                    and unit.unit_type
+                    in {
+                        RetrievalUnitType.VISUAL,
+                        RetrievalUnitType.UNRESOLVED_VISUAL,
+                    }
+                )
+                if same_page_visual:
+                    return _dedupe_units(same_page_visual)
+
+                same_page_units = tuple(
+                    unit
+                    for unit in corpus.units
+                    if _intersects(unit, plan.page_filter)
+                    and unit.unit_type
+                    in {
+                        RetrievalUnitType.PAGE_TEXT,
+                        RetrievalUnitType.TABLE,
+                        RetrievalUnitType.UNASSIGNED_SPAN,
+                    }
+                )
+                return _dedupe_units(same_page_units)
+
+            visual_units = tuple(
+                unit
+                for unit in corpus.units
+                if unit.unit_type
+                in {
+                    RetrievalUnitType.VISUAL,
+                    RetrievalUnitType.UNRESOLVED_VISUAL,
+                }
+            )
+            return _dedupe_units(visual_units)
+
+        if plan.table_query:
+            if plan.page_filter is not None:
+                same_page_tables = tuple(
+                    unit
+                    for unit in corpus.units
+                    if _intersects(unit, plan.page_filter)
+                    and unit.unit_type is RetrievalUnitType.TABLE
+                )
+                if same_page_tables:
+                    return _dedupe_units(same_page_tables)
+                same_page_text = tuple(
+                    unit
+                    for unit in corpus.units
+                    if _intersects(unit, plan.page_filter)
+                    and unit.unit_type
+                    in {
+                        RetrievalUnitType.PAGE_TEXT,
+                        RetrievalUnitType.UNASSIGNED_SPAN,
+                    }
+                )
+                if same_page_text:
+                    return _dedupe_units(same_page_text)
+            return _dedupe_units(
+                tuple(unit for unit in corpus.units if unit.unit_type is RetrievalUnitType.TABLE)
+            )
+
+        if plan.page_filter is not None:
+            same_page_units = tuple(
+                unit for unit in corpus.units if _intersects(unit, plan.page_filter)
+            )
+            if same_page_units:
+                return _dedupe_units(same_page_units)
+
+        if plan.unit_types:
+            type_only_units = tuple(
+                unit for unit in corpus.units if unit.unit_type in set(plan.unit_types)
+            )
+            if type_only_units:
+                return _dedupe_units(type_only_units)
+
+        return corpus.units
+
+
+__all__ = ["RetrievalService"]
diff --git a/tests/llm/test_multimodal_litellm_adapter.py b/tests/llm/test_multimodal_litellm_adapter.py
new file mode 100644
index 0000000..13ab28d
--- /dev/null
+++ b/tests/llm/test_multimodal_litellm_adapter.py
@@ -0,0 +1,138 @@
+"""LiteLLM multimodal adapter tests."""
+
+from __future__ import annotations
+
+from pathlib import Path
+from typing import Any
+
+import pytest
+
+from nullvector.domain import BoundingBox, VisualRegionReference
+from nullvector.llm.multimodal_gateway import (
+    LiteLLMMultimodalAdapter,
+    MultimodalFailureCategory,
+    MultimodalGatewayConfig,
+    MultimodalGatewayError,
+    MultimodalGatewayRequest,
+    MultimodalGatewayService,
+    MultimodalProviderConfig,
+    RegionImageInput,
+    VisualInsightResponse,
+)
+
+
+def _write_attachment(tmp_path: Path) -> Path:
+    attachment = tmp_path / "region.png"
+    attachment.write_bytes(b"png-fixture")
+    return attachment
+
+
+def _make_region(image_path: Path) -> RegionImageInput:
+    return RegionImageInput(
+        region=VisualRegionReference(
+            document_id="d" * 64,
+            page_index=0,
+            region_id="region-001",
+            bbox=BoundingBox(x0=0.0, y0=0.0, x1=20.0, y1=20.0),
+            image_ref="image-001",
+            asset_path=str(image_path),
+        ),
+        image_path=str(image_path),
+    )
+
+
+def _make_gateway(
+    tmp_path: Path,
+    *,
+    completion_callable: Any,
+) -> MultimodalGatewayService:
+    adapter = LiteLLMMultimodalAdapter(
+        completion_callable=completion_callable,
+        supports_vision_callable=lambda *_args, **_kwargs: True,
+        supports_response_schema_callable=lambda *_args, **_kwargs: True,
+    )
+    return MultimodalGatewayService(
+        MultimodalGatewayConfig(
+            provider=MultimodalProviderConfig(
+                provider="litellm_multimodal",
+                model="openai/gpt-4.1-mini",
+                extra_body={"custom_llm_provider": "openai"},
+            ),
+            audit_root=str(tmp_path / "audit"),
+        ),
+        provider_adapter=adapter,
+    )
+
+
+def _request(image_path: Path) -> MultimodalGatewayRequest[VisualInsightResponse]:
+    return MultimodalGatewayRequest[VisualInsightResponse](
+        operation_name="visual_region_enrichment",
+        prompt="Describe the image region.",
+        regions=(_make_region(image_path),),
+        response_model=VisualInsightResponse,
+    )
+
+
+def test_litellm_multimodal_adapter_returns_typed_success(tmp_path: Path) -> None:
+    gateway = _make_gateway(
+        tmp_path,
+        completion_callable=lambda **_kwargs: {
+            "choices": [
+                {
+                    "message": {
+                        "content": (
+                            '{"insight":{"summary":"diagram summary","labels":["diagram"],'
+                            '"attributes":{"kind":"flow"},"confidence":0.8}}'
+                        )
+                    }
+                }
+            ],
+            "usage": {"input_tokens": 5, "output_tokens": 7, "total_tokens": 12},
+        },
+    )
+
+    response = gateway.invoke(_request(_write_attachment(tmp_path)))
+
+    assert response.output.insight.summary == "diagram summary"
+    assert response.usage is not None
+    assert response.usage.total_tokens == 12
+
+
+def test_litellm_multimodal_adapter_validation_failure_is_typed(tmp_path: Path) -> None:
+    gateway = _make_gateway(
+        tmp_path,
+        completion_callable=lambda **_kwargs: {
+            "choices": [{"message": {"content": '{"wrong":"shape"}'}}],
+        },
+    )
+
+    with pytest.raises(MultimodalGatewayError) as exc_info:
+        gateway.invoke(_request(_write_attachment(tmp_path)))
+
+    assert exc_info.value.failure.category is MultimodalFailureCategory.VALIDATION_FAILURE
+
+
+@pytest.mark.parametrize(
+    ("exc_type", "status_code", "expected_category"),
+    [
+        ("APITimeoutError", 408, MultimodalFailureCategory.TIMEOUT),
+        ("AuthenticationError", 401, MultimodalFailureCategory.AUTH_FAILURE),
+        ("APIConnectionError", None, MultimodalFailureCategory.NETWORK_FAILURE),
+    ],
+)
+def test_litellm_multimodal_adapter_maps_provider_failures(
+    tmp_path: Path,
+    exc_type: str,
+    status_code: int | None,
+    expected_category: MultimodalFailureCategory,
+) -> None:
+    def raising_completion(**_kwargs: Any) -> dict[str, Any]:
+        error_cls = type(exc_type, (Exception,), {"status_code": status_code})
+        raise error_cls(exc_type)
+
+    gateway = _make_gateway(tmp_path, completion_callable=raising_completion)
+
+    with pytest.raises(MultimodalGatewayError) as exc_info:
+        gateway.invoke(_request(_write_attachment(tmp_path)))
+
+    assert exc_info.value.failure.category is expected_category
diff --git a/tests/retrieval/__init__.py b/tests/retrieval/__init__.py
new file mode 100644
index 0000000..a6bad02
--- /dev/null
+++ b/tests/retrieval/__init__.py
@@ -0,0 +1 @@
+"""Retrieval subsystem tests."""
diff --git a/tests/retrieval/support.py b/tests/retrieval/support.py
new file mode 100644
index 0000000..c683813
--- /dev/null
+++ b/tests/retrieval/support.py
@@ -0,0 +1,413 @@
+"""Synthetic retrieval artifact fixtures."""
+
+from __future__ import annotations
+
+import hashlib
+import json
+from dataclasses import dataclass
+from pathlib import Path
+from typing import Any
+
+from nullvector.domain import (
+    AcquisitionManifest,
+    AcquisitionRunManifest,
+    AcquisitionSettings,
+    AnchorSource,
+    BoundingBox,
+    CanonicalDocumentLedger,
+    CanonicalPage,
+    DocumentFingerprint,
+    ExtractionProvenance,
+    GroundingEvidence,
+    HierarchyNode,
+    LineBlock,
+    NodeAnchor,
+    NodeCard,
+    NodeOwnedSpan,
+    NodeSummary,
+    NodeSummaryMethod,
+    OutlineSource,
+    PageSourceAnchor,
+    PageSpan,
+    SourceMetadata,
+    SourceTrack,
+    StructuredRegionInsight,
+    TableArtifact,
+    TreeBuildManifest,
+    TreeNodeVerificationResult,
+    TreeSettings,
+    UnassignedPageSpan,
+    VerificationReport,
+    VisualArtifact,
+    VisualEnrichmentAttachment,
+)
+from nullvector.domain.common import ContentSpan
+from nullvector.domain.events import ContentAuthoritativeness
+from nullvector.domain.tree import HierarchyOrigin, VerificationStatus
+from nullvector.ingest.acquisition_artifacts import settings_digest as acquisition_settings_digest
+from nullvector.ingest.artifacts import canonical_json_bytes
+from nullvector.ingest.projection import build_canonical_text_substrate
+
+
+def _json_safe(value: Any) -> Any:
+    if hasattr(value, "model_dump") and callable(value.model_dump):
+        return _json_safe(value.model_dump(mode="json"))
+    if isinstance(value, dict):
+        return {str(key): _json_safe(item) for key, item in value.items()}
+    if isinstance(value, list | tuple):
+        return [_json_safe(item) for item in value]
+    if isinstance(value, str | int | float | bool) or value is None:
+        return value
+    return str(value)
+
+
+def _write_json(path: Path, payload: Any) -> None:
+    path.parent.mkdir(parents=True, exist_ok=True)
+    path.write_text(
+        json.dumps(_json_safe(payload), indent=2, sort_keys=True, ensure_ascii=True),
+        encoding="utf-8",
+    )
+
+
+def _native_provenance(
+    *,
+    authoritativeness: ContentAuthoritativeness,
+) -> ExtractionProvenance:
+    return ExtractionProvenance(
+        source_track=SourceTrack.NATIVE,
+        producer_name="synthetic-retrieval-fixture",
+        grounded_in_native_metadata=True,
+        grounded_in_bbox=True,
+        content_authoritativeness=authoritativeness,
+    )
+
+
+def _line_block(*, page_index: int, reading_index: int, text: str) -> LineBlock:
+    return LineBlock(
+        line_id=f"page-{page_index}-line-{reading_index:04d}",
+        bbox=BoundingBox(
+            x0=0.0,
+            y0=float(reading_index * 14),
+            x1=float(max(len(text), 1) * 7),
+            y1=float(reading_index * 14 + 12),
+        ),
+        content=text,
+        reading_index=reading_index,
+        occurrence_index=0,
+        top_y=float(reading_index * 14),
+        font_size=12.0,
+        provenance=_native_provenance(
+            authoritativeness=ContentAuthoritativeness.AUTHORITATIVE,
+        ),
+    )
+
+
+@dataclass(frozen=True)
+class SyntheticRetrievalBundle:
+    """Paths and expected values for synthetic retrieval tests."""
+
+    acquisition_manifest_path: Path
+    tree_manifest_path: Path
+    cached_attachment: VisualEnrichmentAttachment
+    expected_node_text: str
+    document_id: str
+
+
+def write_synthetic_bundle(tmp_path: Path) -> SyntheticRetrievalBundle:
+    """Create a synthetic acquisition + tree artifact bundle for retrieval tests."""
+
+    document_id = "a" * 64
+    acquisition_root = tmp_path / "synthetic-acquisition"
+    tree_root = tmp_path / "synthetic-tree"
+    source_path = acquisition_root / "source" / "original.pdf"
+    source_path.parent.mkdir(parents=True, exist_ok=True)
+    source_path.write_bytes(b"%PDF-1.4 synthetic retrieval fixture")
+
+    page_render = acquisition_root / "assets" / "pages" / "000000" / "render-144dpi.png"
+    page_asset = acquisition_root / "assets" / "pages" / "000000" / "page-0-visual.png"
+    page_render.parent.mkdir(parents=True, exist_ok=True)
+    page_render.write_bytes(b"png-render")
+    page_asset.write_bytes(b"png-crop")
+
+    page_one_lines = (
+        "Appendix A",
+        "Alpha body line",
+        "Beta body line",
+    )
+    page_one_text = "\n".join(page_one_lines)
+    alpha_start = page_one_text.index("Alpha body line")
+    expected_node_text = page_one_text[alpha_start:]
+
+    ledger = CanonicalDocumentLedger(
+        document_id=document_id,
+        source_fingerprint=DocumentFingerprint(
+            document_id=document_id,
+            source_path=str(source_path),
+            sha256=document_id,
+            file_size_bytes=source_path.stat().st_size,
+            page_count=2,
+        ),
+        source_metadata=SourceMetadata(
+            source_path=str(source_path),
+            file_size_bytes=source_path.stat().st_size,
+            mime_type="application/pdf",
+            page_count=2,
+        ),
+        acquisition_manifest=AcquisitionManifest(
+            source_fingerprint_sha256=document_id,
+            settings_digest=acquisition_settings_digest(AcquisitionSettings()),
+            acquisition_provider_identity="synthetic-retrieval-fixture",
+            selected_outline_source=OutlineSource.NONE,
+            ledger_artifact_path=str(
+                acquisition_root / "ledger" / "canonical-document-ledger.json"
+            ),
+        ),
+        pages=(
+            CanonicalPage(
+                page_index=0,
+                width=612.0,
+                height=792.0,
+                native_available=False,
+                blocks=(
+                    VisualArtifact(
+                        visual_id="page-0-visual-0000",
+                        bbox=BoundingBox(x0=10.0, y0=10.0, x1=120.0, y1=140.0),
+                        reading_index=0,
+                        kind_hint="cover_figure",
+                        image_ref="page-0-image-0000",
+                        asset_path=str(page_asset),
+                        page_render_path=str(page_render),
+                        render_dpi=144,
+                        needs_enrichment=True,
+                        provenance=_native_provenance(
+                            authoritativeness=ContentAuthoritativeness.SUPPLEMENTAL,
+                        ),
+                    ),
+                ),
+                events=(),
+            ),
+            CanonicalPage(
+                page_index=1,
+                width=612.0,
+                height=792.0,
+                native_available=True,
+                blocks=(
+                    _line_block(page_index=1, reading_index=0, text=page_one_lines[0]),
+                    _line_block(page_index=1, reading_index=1, text=page_one_lines[1]),
+                    _line_block(page_index=1, reading_index=2, text=page_one_lines[2]),
+                    TableArtifact(
+                        table_id="page-1-table-0000",
+                        bbox=BoundingBox(x0=20.0, y0=200.0, x1=200.0, y1=260.0),
+                        reading_index=3,
+                        rows=(("Name", "Value"), ("Alpha", "1"), ("Beta", "2")),
+                        markdown_projection="| Name | Value |\n| Alpha | 1 |\n| Beta | 2 |",
+                        provenance=_native_provenance(
+                            authoritativeness=ContentAuthoritativeness.SUPPLEMENTAL,
+                        ),
+                        grounding=GroundingEvidence(
+                            has_native_text_anchor=True,
+                            has_page_bbox_anchor=True,
+                            has_layout_anchor=True,
+                        ),
+                    ),
+                ),
+                events=(),
+            ),
+        ),
+        document_events=(),
+    )
+    substrate = build_canonical_text_substrate(ledger)
+    ledger_path = acquisition_root / "ledger" / "canonical-document-ledger.json"
+    substrate_path = acquisition_root / "projection" / "canonical-text-substrate.json"
+    outline_path = acquisition_root / "outline" / "selected.json"
+    events_path = acquisition_root / "events" / "document-events.jsonl"
+    _write_json(ledger_path, ledger)
+    _write_json(substrate_path, substrate)
+    _write_json(outline_path, {"selected_source": "none", "entries": []})
+    events_path.parent.mkdir(parents=True, exist_ok=True)
+    events_path.write_text("", encoding="utf-8")
+
+    acquisition_manifest = AcquisitionRunManifest(
+        acquisition_run_id="synthetic-acquisition-run",
+        document_id=document_id,
+        artifact_root=str(acquisition_root),
+        source_fingerprint=ledger.source_fingerprint,
+        settings=AcquisitionSettings(),
+        settings_digest=acquisition_settings_digest(AcquisitionSettings()),
+        provider_identity="synthetic-retrieval-fixture",
+        ledger_path=str(ledger_path),
+        source_copy_path=str(source_path),
+        event_stream_path=str(events_path),
+        selected_outline_source=OutlineSource.NONE,
+        outline_quality_reports=(),
+        selected_outline_path=str(outline_path),
+        pymupdf_outline_path=str(outline_path),
+        pymupdf_rich_outline_path=str(outline_path),
+        pypdf_outline_path=str(outline_path),
+        page_count=2,
+        canonical_text_substrate_path=str(substrate_path),
+    )
+    acquisition_manifest_path = acquisition_root / "manifest.json"
+    _write_json(acquisition_manifest_path, acquisition_manifest)
+
+    node = HierarchyNode(
+        node_id="node-appendix-a",
+        document_id=document_id,
+        path=("Appendix A",),
+        level=1,
+        title="Appendix A",
+        normalized_title="appendix a",
+        page_span=PageSpan(start_page=1, end_page=1),
+        heading_anchor=NodeAnchor(
+            page=1,
+            start_offset=0,
+            end_offset=len("Appendix A"),
+            anchor_text="Appendix A",
+            anchor_source=AnchorSource.TEXT,
+            occurrence_index=0,
+        ),
+        owned_spans=(
+            NodeOwnedSpan(
+                kind="body",
+                span=ContentSpan(
+                    start_page=1,
+                    start_offset=alpha_start,
+                    end_page=1,
+                    end_offset=len(page_one_text),
+                ),
+            ),
+        ),
+        source_anchors=(
+            PageSourceAnchor(
+                page=1,
+                start_offset=alpha_start,
+                end_offset=alpha_start + len("Alpha body line"),
+                quote="Alpha body line",
+            ),
+        ),
+        origin=HierarchyOrigin.INFERRED,
+        confidence=1.0,
+    )
+    node_card = NodeCard(
+        node_id=node.node_id,
+        document_id=document_id,
+        path=node.path,
+        level=node.level,
+        title=node.title,
+        page_span=node.page_span,
+        owned_spans=node.owned_spans,
+        source_anchors=node.source_anchors,
+    )
+    node_summary = NodeSummary(
+        node_id=node.node_id,
+        summary="Appendix A summarizes the alpha and beta body lines.",
+        keywords=("appendix", "alpha"),
+        summary_method=NodeSummaryMethod.PASSTHROUGH,
+        token_count=10,
+        estimated_token_count=10,
+        exact_token_count=10,
+        tokenizer_identity="synthetic-tokenizer",
+    )
+    unassigned_span = UnassignedPageSpan(
+        document_id=document_id,
+        reason="before_first_heading",
+        page_span=PageSpan(start_page=0, end_page=0),
+    )
+    verification_report = VerificationReport(
+        document_id=document_id,
+        tree_run_id="synthetic-tree-run",
+        status=VerificationStatus.FAILED,
+        node_results=(
+            TreeNodeVerificationResult(
+                document_id=document_id,
+                tree_run_id="synthetic-tree-run",
+                subject_id=node.node_id,
+                status=VerificationStatus.PASSED,
+                issues=(),
+                covered_page_span=node.page_span,
+            ),
+        ),
+        unassigned_spans=(unassigned_span,),
+    )
+
+    tree_settings = TreeSettings()
+    tree_digest = hashlib.sha256(canonical_json_bytes(tree_settings)).hexdigest()
+    placeholder_json_files: dict[Path, object] = {
+        tree_root / "strategy" / "attempts" / "01" / "headings.json": {},
+        tree_root / "strategy" / "attempts" / "01" / "raw-hierarchy.json": [],
+        tree_root / "strategy" / "attempts" / "01" / "repair-requests.json": [],
+        tree_root / "strategy" / "attempts" / "01" / "repair-decisions.json": [],
+        tree_root / "strategy" / "attempts" / "01" / "repaired-hierarchy.json": [],
+        tree_root / "strategy" / "attempts" / "01" / "build-report.json": {},
+        tree_root / "run-index.json": {},
+    }
+    for path, payload in placeholder_json_files.items():
+        _write_json(path, payload)
+
+    committed_path = tree_root / "strategy" / "attempts" / "01" / "committed.json"
+    node_cards_path = tree_root / "strategy" / "attempts" / "01" / "node-cards.json"
+    node_summaries_path = tree_root / "strategy" / "attempts" / "01" / "node-summaries.json"
+    unassigned_path = tree_root / "strategy" / "attempts" / "01" / "unassigned-spans.json"
+    verification_path = tree_root / "strategy" / "attempts" / "01" / "verification-report.json"
+    _write_json(committed_path, (node,))
+    _write_json(node_cards_path, (node_card,))
+    _write_json(node_summaries_path, (node_summary,))
+    _write_json(unassigned_path, (unassigned_span,))
+    _write_json(verification_path, verification_report)
+
+    tree_manifest = TreeBuildManifest(
+        tree_run_id="synthetic-tree-run",
+        document_id=document_id,
+        registry_root=str(tree_root / "_registry"),
+        acquisition_manifest_path=str(acquisition_manifest_path),
+        acquisition_artifact_identity=str(acquisition_manifest_path),
+        acquisition_fingerprint_sha256=document_id,
+        artifact_root=str(tree_root),
+        settings=tree_settings,
+        settings_digest=tree_digest,
+        run_index_path=str(tree_root / "run-index.json"),
+        headings_path=str(next(iter(placeholder_json_files.keys()))),
+        raw_hierarchy_path=str(tree_root / "strategy" / "attempts" / "01" / "raw-hierarchy.json"),
+        repair_requests_path=str(
+            tree_root / "strategy" / "attempts" / "01" / "repair-requests.json"
+        ),
+        repair_decisions_path=str(
+            tree_root / "strategy" / "attempts" / "01" / "repair-decisions.json"
+        ),
+        repaired_hierarchy_path=str(
+            tree_root / "strategy" / "attempts" / "01" / "repaired-hierarchy.json"
+        ),
+        committed_hierarchy_path=str(committed_path),
+        node_cards_path=str(node_cards_path),
+        unassigned_spans_path=str(unassigned_path),
+        verification_report_path=str(verification_path),
+        build_report_path=str(tree_root / "strategy" / "attempts" / "01" / "build-report.json"),
+        node_summaries_path=str(node_summaries_path),
+        committed_node_count=1,
+        unassigned_span_count=1,
+    )
+    tree_manifest_path = tree_root / "manifest.json"
+    _write_json(tree_manifest_path, tree_manifest)
+
+    cached_attachment = VisualEnrichmentAttachment(
+        attachment_id="attach-page-0-visual",
+        document_id=document_id,
+        region_id="page-0-visual-0000",
+        provider_identity="cached-fixture",
+        authoritative=False,
+        insight=StructuredRegionInsight(
+            summary="A title-page illustration of a pipeline overview.",
+            labels=("illustration",),
+            attributes={"kind": "overview"},
+            confidence=0.9,
+        ),
+        audit_path=str(tmp_path / "cached-attachment-audit.json"),
+    )
+
+    return SyntheticRetrievalBundle(
+        acquisition_manifest_path=acquisition_manifest_path,
+        tree_manifest_path=tree_manifest_path,
+        cached_attachment=cached_attachment,
+        expected_node_text=expected_node_text,
+        document_id=document_id,
+    )
diff --git a/tests/retrieval/test_corpus_builder.py b/tests/retrieval/test_corpus_builder.py
new file mode 100644
index 0000000..acb918c
--- /dev/null
+++ b/tests/retrieval/test_corpus_builder.py
@@ -0,0 +1,59 @@
+"""Retrieval corpus builder tests."""
+
+from __future__ import annotations
+
+from pathlib import Path
+
+from nullvector.domain.retrieval import RetrievalUnitType
+from nullvector.retrieval import RetrievalCorpusBuilder, load_retrieval_corpus
+
+from .support import write_synthetic_bundle
+
+
+def test_image_only_page_emits_visual_units(tmp_path: Path) -> None:
+    bundle = write_synthetic_bundle(tmp_path)
+    manifest = RetrievalCorpusBuilder().build(
+        acquisition_manifest_path=str(bundle.acquisition_manifest_path),
+        tree_manifest_path=str(bundle.tree_manifest_path),
+    )
+
+    corpus = load_retrieval_corpus(manifest.corpus_path)
+    page_zero_units = tuple(
+        unit
+        for unit in corpus.units
+        if unit.page_span.start_page == 0 and unit.page_span.end_page == 0
+    )
+
+    assert any(unit.unit_type is RetrievalUnitType.VISUAL for unit in page_zero_units)
+
+
+def test_unassigned_spans_emit_retrieval_units(tmp_path: Path) -> None:
+    bundle = write_synthetic_bundle(tmp_path)
+    manifest = RetrievalCorpusBuilder().build(
+        acquisition_manifest_path=str(bundle.acquisition_manifest_path),
+        tree_manifest_path=str(bundle.tree_manifest_path),
+    )
+
+    corpus = load_retrieval_corpus(manifest.corpus_path)
+    unassigned_units = tuple(
+        unit for unit in corpus.units if unit.unit_type is RetrievalUnitType.UNASSIGNED_SPAN
+    )
+
+    assert len(unassigned_units) == 1
+    assert unassigned_units[0].metadata["reason"] == "before_first_heading"
+
+
+def test_node_text_is_reconstructed_from_owned_spans(tmp_path: Path) -> None:
+    bundle = write_synthetic_bundle(tmp_path)
+    manifest = RetrievalCorpusBuilder().build(
+        acquisition_manifest_path=str(bundle.acquisition_manifest_path),
+        tree_manifest_path=str(bundle.tree_manifest_path),
+    )
+
+    corpus = load_retrieval_corpus(manifest.corpus_path)
+    node_text_unit = next(
+        unit for unit in corpus.units if unit.unit_type is RetrievalUnitType.NODE_TEXT
+    )
+
+    assert node_text_unit.text == bundle.expected_node_text
+    assert node_text_unit.text != "Appendix A summarizes the alpha and beta body lines."
diff --git a/tests/retrieval/test_qa.py b/tests/retrieval/test_qa.py
new file mode 100644
index 0000000..7449f99
--- /dev/null
+++ b/tests/retrieval/test_qa.py
@@ -0,0 +1,82 @@
+"""QA tests over retrieval hits."""
+
+from __future__ import annotations
+
+from pathlib import Path
+
+from nullvector.retrieval import (
+    QueryPlanner,
+    RetrievalCorpusBuilder,
+    RetrievalQAService,
+    RetrievalRanker,
+    RetrievalService,
+    augment_corpus_with_attachments,
+    load_retrieval_corpus,
+)
+
+from .support import write_synthetic_bundle
+
+
+def _services() -> tuple[RetrievalService, RetrievalQAService]:
+    retrieval_service = RetrievalService(QueryPlanner(), RetrievalRanker())
+    return retrieval_service, RetrievalQAService(retrieval_service)
+
+
+def test_visual_query_without_multimodal_returns_honest_failure(tmp_path: Path) -> None:
+    bundle = write_synthetic_bundle(tmp_path)
+    manifest = RetrievalCorpusBuilder().build(
+        acquisition_manifest_path=str(bundle.acquisition_manifest_path),
+        tree_manifest_path=str(bundle.tree_manifest_path),
+    )
+    corpus = load_retrieval_corpus(manifest.corpus_path)
+    _, qa_service = _services()
+
+    response = qa_service.answer(
+        corpus=corpus,
+        query="what is the image on first page about?",
+    )
+    expected = (
+        "Page 0 contains visual evidence, but no grounded visual interpretation is "
+        "available in the current corpus."
+    )
+
+    assert response.answer == expected
+    assert response.answer_mode == "visual_interpretation_unavailable"
+
+
+def test_visual_query_with_cached_attachment_returns_grounded_answer(tmp_path: Path) -> None:
+    bundle = write_synthetic_bundle(tmp_path)
+    manifest = RetrievalCorpusBuilder().build(
+        acquisition_manifest_path=str(bundle.acquisition_manifest_path),
+        tree_manifest_path=str(bundle.tree_manifest_path),
+    )
+    corpus = augment_corpus_with_attachments(
+        corpus=load_retrieval_corpus(manifest.corpus_path),
+        attachments=(bundle.cached_attachment,),
+    )
+    _, qa_service = _services()
+
+    response = qa_service.answer(
+        corpus=corpus,
+        query="what is the image on first page about?",
+    )
+
+    assert response.answer == bundle.cached_attachment.insight.summary
+    assert response.answer_mode == "cached_visual_attachment"
+
+
+def test_text_query_returns_citations_from_authoritative_units(tmp_path: Path) -> None:
+    bundle = write_synthetic_bundle(tmp_path)
+    manifest = RetrievalCorpusBuilder().build(
+        acquisition_manifest_path=str(bundle.acquisition_manifest_path),
+        tree_manifest_path=str(bundle.tree_manifest_path),
+    )
+    corpus = load_retrieval_corpus(manifest.corpus_path)
+    _, qa_service = _services()
+
+    response = qa_service.answer(corpus=corpus, query="Alpha body line")
+
+    assert response.answer_mode == "authoritative_text"
+    assert response.citations
+    assert response.citations[0].quote is not None
+    assert "Alpha body line" in (response.citations[0].quote or "")
diff --git a/tests/retrieval/test_query_planner.py b/tests/retrieval/test_query_planner.py
new file mode 100644
index 0000000..e48ecc3
--- /dev/null
+++ b/tests/retrieval/test_query_planner.py
@@ -0,0 +1,46 @@
+"""Query planner tests for deterministic page and modality extraction."""
+
+from __future__ import annotations
+
+from nullvector.domain.retrieval import RetrievalModality, RetrievalUnitType
+from nullvector.retrieval import QueryPlanner
+
+
+def test_query_planner_detects_first_page_image_query() -> None:
+    plan = QueryPlanner().plan("what is the image on first page about?")
+
+    assert plan.page_filter is not None
+    assert plan.page_filter.start_page == 0
+    assert plan.page_filter.end_page == 0
+    assert plan.modality_filters == (RetrievalModality.VISUAL,)
+    assert plan.unit_types == (
+        RetrievalUnitType.VISUAL,
+        RetrievalUnitType.UNRESOLVED_VISUAL,
+    )
+    assert plan.visual_query is True
+    assert plan.requires_multimodal is True
+
+
+def test_query_planner_detects_page_12_table_query() -> None:
+    plan = QueryPlanner().plan("show me the table on page 12")
+
+    assert plan.page_filter is not None
+    assert plan.page_filter.start_page == 11
+    assert plan.modality_filters == (RetrievalModality.TABLE,)
+    assert plan.unit_types == (RetrievalUnitType.TABLE,)
+    assert plan.table_query is True
+
+
+def test_query_planner_detects_appendix_a_as_structural_query() -> None:
+    plan = QueryPlanner().plan("appendix A")
+
+    assert plan.structural_query is True
+    assert "appendix a" in plan.title_like_phrases
+
+
+def test_query_planner_extracts_quoted_title_phrases() -> None:
+    plan = QueryPlanner().plan('where is "Safety Overview" discussed?')
+
+    assert plan.structural_query is True
+    assert plan.quoted_phrases == ("safety overview",)
+    assert "safety overview" in plan.title_like_phrases
diff --git a/tests/retrieval/test_ranker.py b/tests/retrieval/test_ranker.py
new file mode 100644
index 0000000..ab671cf
--- /dev/null
+++ b/tests/retrieval/test_ranker.py
@@ -0,0 +1,83 @@
+"""Retrieval ranking tests."""
+
+from __future__ import annotations
+
+from nullvector.domain.models import PageSpan
+from nullvector.domain.retrieval import (
+    QueryPlan,
+    RetrievalEvidence,
+    RetrievalModality,
+    RetrievalUnitType,
+)
+from nullvector.retrieval import QueryPlanner, RetrievalRanker
+
+
+def test_page_filtered_visual_query_ranks_page_zero_visual_above_text_nodes() -> None:
+    ranker = RetrievalRanker()
+    plan = QueryPlanner().plan("what is the image on first page about?")
+    visual = RetrievalEvidence(
+        unit_id="visual-0",
+        document_id="d" * 64,
+        unit_type=RetrievalUnitType.VISUAL,
+        modality=RetrievalModality.VISUAL,
+        page_span=PageSpan(start_page=0, end_page=0),
+        authoritative=False,
+    )
+    page_text = RetrievalEvidence(
+        unit_id="page-text-0",
+        document_id="d" * 64,
+        unit_type=RetrievalUnitType.PAGE_TEXT,
+        modality=RetrievalModality.TEXT,
+        page_span=PageSpan(start_page=0, end_page=0),
+        text="Cover page title only.",
+        authoritative=True,
+    )
+    node_text = RetrievalEvidence(
+        unit_id="node-text-1",
+        document_id="d" * 64,
+        unit_type=RetrievalUnitType.NODE_TEXT,
+        modality=RetrievalModality.TEXT,
+        page_span=PageSpan(start_page=1, end_page=1),
+        text="Alpha body line",
+        authoritative=True,
+    )
+
+    hits = ranker.rank(
+        query="what is the image on first page about?",
+        plan=plan,
+        candidates=(page_text, node_text, visual),
+    )
+
+    assert hits[0].unit.unit_id == "visual-0"
+    assert hits[0].score > hits[1].score
+
+
+def test_summary_unit_does_not_outrank_exact_page_text() -> None:
+    ranker = RetrievalRanker()
+    plan = QueryPlan(
+        raw_query="Alpha body line",
+        normalized_query="alpha body line",
+    )
+    page_text = RetrievalEvidence(
+        unit_id="page-text",
+        document_id="d" * 64,
+        unit_type=RetrievalUnitType.PAGE_TEXT,
+        modality=RetrievalModality.TEXT,
+        page_span=PageSpan(start_page=1, end_page=1),
+        text="Alpha body line",
+        authoritative=True,
+    )
+    summary = RetrievalEvidence(
+        unit_id="node-summary",
+        document_id="d" * 64,
+        unit_type=RetrievalUnitType.NODE_SUMMARY,
+        modality=RetrievalModality.TEXT,
+        page_span=PageSpan(start_page=1, end_page=1),
+        text="Alpha body line is summarized here.",
+        interpretive=True,
+        authoritative=False,
+    )
+
+    hits = ranker.rank(query="Alpha body line", plan=plan, candidates=(summary, page_text))
+
+    assert hits[0].unit.unit_id == "page-text"
```
