"""Integration coverage for the Phase 00 bootstrap."""

from __future__ import annotations

from pathlib import Path

from strataforge import (
    ContentSpan,
    NodeCard,
    NodeOwnedSpan,
    PageLedgerRow,
    ParseJobLifecycle,
    ParseJobState,
    TreeBuildManifest,
    TreeBuildRequest,
    TreeNodeVerificationResult,
    VerificationResult,
)
from strataforge.domain.models import ContentSpan as DomainContentSpan
from strataforge.domain.models import NodeCard as DomainNodeCard
from strataforge.domain.models import NodeOwnedSpan as DomainNodeOwnedSpan
from strataforge.domain.models import PageLedgerRow as DomainPageLedgerRow
from strataforge.domain.models import ParseJobLifecycle as DomainParseJobLifecycle
from strataforge.domain.models import ParseJobState as DomainParseJobState
from strataforge.domain.models import TreeBuildManifest as DomainTreeBuildManifest
from strataforge.domain.models import TreeBuildRequest as DomainTreeBuildRequest
from strataforge.domain.models import TreeNodeVerificationResult as DomainTreeNodeVerificationResult
from strataforge.domain.models import VerificationResult as DomainVerificationResult


def test_required_bootstrap_paths_exist() -> None:
    repo_root = Path(__file__).resolve().parents[2]

    required_paths = (
        repo_root / "src" / "strataforge" / "domain" / "models.py",
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
    assert NodeCard is DomainNodeCard
    assert NodeOwnedSpan is DomainNodeOwnedSpan
    assert PageLedgerRow is DomainPageLedgerRow
    assert ContentSpan is DomainContentSpan
    assert ParseJobLifecycle is DomainParseJobLifecycle
    assert ParseJobState is DomainParseJobState
    assert TreeBuildManifest is DomainTreeBuildManifest
    assert TreeBuildRequest is DomainTreeBuildRequest
    assert TreeNodeVerificationResult is DomainTreeNodeVerificationResult
    assert VerificationResult is DomainVerificationResult
