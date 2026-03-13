"""Integration coverage for the Phase 00 bootstrap."""

from __future__ import annotations

from pathlib import Path

from nullvector import (
    AcquisitionRequest,
    AcquisitionRunIndex,
    AcquisitionRunManifest,
    CanonicalDocumentLedger,
    ContentSpan,
    ExtractionProvenance,
    NodeCard,
    NodeOwnedSpan,
    PageLedgerRow,
    ParseJobLifecycle,
    ParseJobState,
    TreeBuildManifest,
    TreeBuildRequest,
    TreeNodeVerificationResult,
    TreeSynthesisView,
    TrustTier,
    VerificationResult,
)
from nullvector.domain.models import AcquisitionRequest as DomainAcquisitionRequest
from nullvector.domain.models import AcquisitionRunIndex as DomainAcquisitionRunIndex
from nullvector.domain.models import AcquisitionRunManifest as DomainAcquisitionRunManifest
from nullvector.domain.models import CanonicalDocumentLedger as DomainCanonicalDocumentLedger
from nullvector.domain.models import ContentSpan as DomainContentSpan
from nullvector.domain.models import ExtractionProvenance as DomainExtractionProvenance
from nullvector.domain.models import NodeCard as DomainNodeCard
from nullvector.domain.models import NodeOwnedSpan as DomainNodeOwnedSpan
from nullvector.domain.models import PageLedgerRow as DomainPageLedgerRow
from nullvector.domain.models import ParseJobLifecycle as DomainParseJobLifecycle
from nullvector.domain.models import ParseJobState as DomainParseJobState
from nullvector.domain.models import TreeBuildManifest as DomainTreeBuildManifest
from nullvector.domain.models import TreeBuildRequest as DomainTreeBuildRequest
from nullvector.domain.models import TreeNodeVerificationResult as DomainTreeNodeVerificationResult
from nullvector.domain.models import TreeSynthesisView as DomainTreeSynthesisView
from nullvector.domain.models import TrustTier as DomainTrustTier
from nullvector.domain.models import VerificationResult as DomainVerificationResult


def test_required_bootstrap_paths_exist() -> None:
    repo_root = Path(__file__).resolve().parents[2]

    required_paths = (
        repo_root / "src" / "nullvector" / "domain" / "common.py",
        repo_root / "src" / "nullvector" / "domain" / "events.py",
        repo_root / "src" / "nullvector" / "domain" / "gateway.py",
        repo_root / "src" / "nullvector" / "domain" / "ledger.py",
        repo_root / "src" / "nullvector" / "domain" / "models.py",
        repo_root / "src" / "nullvector" / "domain" / "tree.py",
        repo_root / "src" / "nullvector" / "ingest" / "protocols.py",
        repo_root / "src" / "nullvector" / "ingest" / "acquisition_artifacts.py",
        repo_root / "src" / "nullvector" / "ingest" / "profiling.py",
        repo_root / "src" / "nullvector" / "ingest" / "projection.py",
        repo_root / "src" / "nullvector" / "ingest" / "acquisition_service.py",
        repo_root / "src" / "nullvector" / "ingest" / "providers" / "native_pymupdf.py",
        repo_root / "src" / "nullvector" / "semantic" / "tokens.py",
        repo_root / "src" / "nullvector" / "semantic" / "summarize.py",
        repo_root / "src" / "nullvector" / "semantic" / "decompose.py",
        repo_root / "src" / "nullvector" / "llm" / "multimodal_gateway" / "service.py",
        repo_root / "src" / "nullvector" / "observability" / "bus.py",
        repo_root / "src" / "nullvector" / "observability" / "events.py",
        repo_root / "src" / "nullvector" / "export" / "langchain.py",
        repo_root / "src" / "nullvector" / "export" / "llamaindex.py",
        repo_root / "docs" / "adr" / "0001-phase-00-bootstrap.md",
        repo_root / "fixtures" / "pdfs" / "README.md",
        repo_root / "fixtures" / "expected" / "README.md",
        repo_root / "notebooks" / "progress.ipynb",
        repo_root / "src" / "nullvector" / "tree" / "service.py",
        repo_root / "tests" / "unit" / "test_domain_models.py",
    )

    missing_paths = [path for path in required_paths if not path.exists()]

    assert not missing_paths


def test_top_level_exports_resolve_to_authoritative_models() -> None:
    assert AcquisitionRequest is DomainAcquisitionRequest
    assert AcquisitionRunIndex is DomainAcquisitionRunIndex
    assert AcquisitionRunManifest is DomainAcquisitionRunManifest
    assert CanonicalDocumentLedger is DomainCanonicalDocumentLedger
    assert NodeCard is DomainNodeCard
    assert NodeOwnedSpan is DomainNodeOwnedSpan
    assert PageLedgerRow is DomainPageLedgerRow
    assert ContentSpan is DomainContentSpan
    assert ExtractionProvenance is DomainExtractionProvenance
    assert ParseJobLifecycle is DomainParseJobLifecycle
    assert ParseJobState is DomainParseJobState
    assert TreeBuildManifest is DomainTreeBuildManifest
    assert TreeBuildRequest is DomainTreeBuildRequest
    assert TreeSynthesisView is DomainTreeSynthesisView
    assert TreeNodeVerificationResult is DomainTreeNodeVerificationResult
    assert TrustTier is DomainTrustTier
    assert VerificationResult is DomainVerificationResult
