"""Integration coverage for the Phase 00 bootstrap."""

from __future__ import annotations

from pathlib import Path

from strataforge import (
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
from strataforge.domain.models import AcquisitionRequest as DomainAcquisitionRequest
from strataforge.domain.models import AcquisitionRunIndex as DomainAcquisitionRunIndex
from strataforge.domain.models import AcquisitionRunManifest as DomainAcquisitionRunManifest
from strataforge.domain.models import CanonicalDocumentLedger as DomainCanonicalDocumentLedger
from strataforge.domain.models import ContentSpan as DomainContentSpan
from strataforge.domain.models import ExtractionProvenance as DomainExtractionProvenance
from strataforge.domain.models import NodeCard as DomainNodeCard
from strataforge.domain.models import NodeOwnedSpan as DomainNodeOwnedSpan
from strataforge.domain.models import PageLedgerRow as DomainPageLedgerRow
from strataforge.domain.models import ParseJobLifecycle as DomainParseJobLifecycle
from strataforge.domain.models import ParseJobState as DomainParseJobState
from strataforge.domain.models import TreeBuildManifest as DomainTreeBuildManifest
from strataforge.domain.models import TreeBuildRequest as DomainTreeBuildRequest
from strataforge.domain.models import TreeNodeVerificationResult as DomainTreeNodeVerificationResult
from strataforge.domain.models import TreeSynthesisView as DomainTreeSynthesisView
from strataforge.domain.models import TrustTier as DomainTrustTier
from strataforge.domain.models import VerificationResult as DomainVerificationResult


def test_required_bootstrap_paths_exist() -> None:
    repo_root = Path(__file__).resolve().parents[2]

    required_paths = (
        repo_root / "src" / "strataforge" / "domain" / "common.py",
        repo_root / "src" / "strataforge" / "domain" / "events.py",
        repo_root / "src" / "strataforge" / "domain" / "gateway.py",
        repo_root / "src" / "strataforge" / "domain" / "ledger.py",
        repo_root / "src" / "strataforge" / "domain" / "models.py",
        repo_root / "src" / "strataforge" / "domain" / "tree.py",
        repo_root / "src" / "strataforge" / "ingest" / "protocols.py",
        repo_root / "src" / "strataforge" / "ingest" / "acquisition_artifacts.py",
        repo_root / "src" / "strataforge" / "ingest" / "profiling.py",
        repo_root / "src" / "strataforge" / "ingest" / "projection.py",
        repo_root / "src" / "strataforge" / "ingest" / "acquisition_service.py",
        repo_root / "src" / "strataforge" / "ingest" / "providers" / "native_pymupdf.py",
        repo_root / "src" / "strataforge" / "semantic" / "tokens.py",
        repo_root / "src" / "strataforge" / "semantic" / "summarize.py",
        repo_root / "src" / "strataforge" / "semantic" / "decompose.py",
        repo_root / "src" / "strataforge" / "llm" / "multimodal_gateway" / "service.py",
        repo_root / "src" / "strataforge" / "observability" / "bus.py",
        repo_root / "src" / "strataforge" / "observability" / "events.py",
        repo_root / "src" / "strataforge" / "export" / "langchain.py",
        repo_root / "src" / "strataforge" / "export" / "llamaindex.py",
        repo_root / "docs" / "adr" / "0001-phase-00-bootstrap.md",
        repo_root / "fixtures" / "pdfs" / "README.md",
        repo_root / "fixtures" / "expected" / "README.md",
        repo_root / "notebooks" / "progress.ipynb",
        repo_root / "src" / "strataforge" / "tree" / "service.py",
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
