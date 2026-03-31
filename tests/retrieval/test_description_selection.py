"""Description-selection loaders and service tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

from nullvector.domain.document_selection import (
    DescriptionSelectionMode,
    DescriptionSelectionRequest,
    DocumentDescriptionRecord,
)
from nullvector.domain.retrieval import DocumentDescriptionRequest
from nullvector.llm import (
    GatewayAuditConfig,
    GatewayConfig,
    GatewayService,
    NoopProviderAdapter,
    NoopScriptedResponse,
)
from nullvector.llm.prompts.description_selection import (
    DescriptionSelectionPromptCandidate,
    DescriptionSelectionPromptResponse,
)
from nullvector.llm.protocols import StructuredLLMGateway
from nullvector.llm.types import JSONValue
from nullvector.retrieval import (
    DescriptionSelectionService,
    DocumentDescriptionBuilder,
    load_document_description,
    load_document_description_manifest,
)
from nullvector.storage import (
    FilesystemStorageConfig,
    PostgresStorageConfig,
    build_postgres_artifact_ref,
)

from .support import write_synthetic_bundle


def _description_record(
    *,
    document_id: str,
    display_name: str,
    description_text: str,
    description_manifest_path: str = "/tmp/description-manifest.json",
) -> DocumentDescriptionRecord:
    return DocumentDescriptionRecord(
        document_id=document_id,
        display_name=display_name,
        description_text=description_text,
        description_manifest_path=description_manifest_path,
    )


def _gateway(
    tmp_path: Path,
    *,
    output_json: dict[str, JSONValue],
) -> GatewayService:
    return GatewayService(
        GatewayConfig(
            default_model="test-model",
            audit=GatewayAuditConfig(persist_root=str(tmp_path / "audit")),
        ),
        provider_adapter=NoopProviderAdapter(
            {
                "description_selection": NoopScriptedResponse(output_json=output_json),
            }
        ),
    )


class _QueuedGateway:
    def __init__(self, outputs: list[DescriptionSelectionPromptResponse]) -> None:
        self._outputs = outputs
        self.calls = 0

    def invoke(self, request: object) -> object:
        del request
        output = self._outputs[self.calls]
        self.calls += 1
        return type("_GatewayResult", (), {"output": output})()

    def invoke_many(
        self,
        requests: object,
        *,
        max_workers: int | None = None,
    ) -> tuple[object, ...]:
        del requests, max_workers
        msg = "_QueuedGateway.invoke_many is not used in this test fixture"
        raise NotImplementedError(msg)


def _build_description_records(tmp_path: Path) -> tuple[DocumentDescriptionRecord, ...]:
    builder = DocumentDescriptionBuilder()
    bundle_alpha = write_synthetic_bundle(
        tmp_path / "alpha",
        document_id="1" * 64,
        bundle_name="alpha",
        section_title="Revenue Overview",
        body_lines=("Alpha revenue rose", "Margins improved"),
        summary_text="Revenue Overview explains alpha revenue growth and margin improvements.",
        keywords=("revenue", "alpha"),
    )
    bundle_beta = write_synthetic_bundle(
        tmp_path / "beta",
        document_id="2" * 64,
        bundle_name="beta",
        section_title="Litigation Summary",
        body_lines=("Beta litigation continues", "Case deadlines shifted"),
        summary_text="Litigation Summary explains beta litigation deadlines and case posture.",
        keywords=("litigation", "beta"),
    )
    manifests = (
        builder.build(
            DocumentDescriptionRequest(
                acquisition_manifest_path=str(bundle_alpha.acquisition_manifest_path),
                tree_manifest_path=str(bundle_alpha.tree_manifest_path),
                description_run_id="alpha-description",
            )
        ),
        builder.build(
            DocumentDescriptionRequest(
                acquisition_manifest_path=str(bundle_beta.acquisition_manifest_path),
                tree_manifest_path=str(bundle_beta.tree_manifest_path),
                description_run_id="beta-description",
            )
        ),
    )
    display_names = {
        bundle_alpha.document_id: "Alpha Revenue Dossier",
        bundle_beta.document_id: "Beta Litigation Memo",
    }
    records: list[DocumentDescriptionRecord] = []
    for manifest in manifests:
        assert manifest.artifact_root is not None
        description_manifest = load_document_description_manifest(
            Path(manifest.artifact_root) / "manifest.json"
        )
        description = load_document_description(manifest.description_path)
        records.append(
            DocumentDescriptionRecord(
                document_id=description.document_id,
                display_name=display_names[description.document_id],
                description_text=description.description_text,
                description_manifest_path=description_manifest.description_path,
            )
        )
    return tuple(records)


def test_description_selection_fallback_ranks_and_persists_artifacts(tmp_path: Path) -> None:
    service = DescriptionSelectionService(
        storage=FilesystemStorageConfig(root=str(tmp_path / "artifacts"))
    )
    records = _build_description_records(tmp_path)

    response = service.select(
        DescriptionSelectionRequest(
            collection_id="collection-descriptions",
            selection_run_id="selection-001",
            query="alpha revenue growth",
            descriptions=records,
            limit=2,
        )
    )

    assert response.selection_mode is DescriptionSelectionMode.DETERMINISTIC_FALLBACK
    assert tuple(candidate.document_id for candidate in response.candidates) == ("1" * 64,)

    index_payload = Path(response.description_index_path).read_text(encoding="utf-8").splitlines()
    results_payload = json.loads(Path(response.selection_results_path).read_text(encoding="utf-8"))

    assert len(index_payload) == 2
    assert results_payload["selection_mode"] == "deterministic_fallback"
    assert results_payload["candidates"][0]["document_id"] == ("1" * 64)


def test_description_selection_applies_exact_substring_boost(tmp_path: Path) -> None:
    service = DescriptionSelectionService(
        storage=FilesystemStorageConfig(root=str(tmp_path / "artifacts"))
    )

    response = service.select(
        DescriptionSelectionRequest(
            collection_id="collection-substring",
            selection_run_id="selection-002",
            query="revenue overview",
            descriptions=(
                _description_record(
                    document_id="doc-substring",
                    display_name="Alpha Revenue Overview",
                    description_text="Revenue overview for alpha planning.",
                ),
                _description_record(
                    document_id="doc-token-overlap",
                    display_name="Alpha Planning File",
                    description_text="Revenue notes and overview guidance.",
                ),
            ),
            limit=2,
        )
    )

    assert tuple(candidate.document_id for candidate in response.candidates) == (
        "doc-substring",
        "doc-token-overlap",
    )
    assert response.candidates[0].score > response.candidates[1].score


def test_description_selection_orders_ties_deterministically(tmp_path: Path) -> None:
    service = DescriptionSelectionService(
        storage=FilesystemStorageConfig(root=str(tmp_path / "artifacts"))
    )

    response = service.select(
        DescriptionSelectionRequest(
            collection_id="collection-ordering",
            selection_run_id="selection-003",
            query="alpha",
            descriptions=(
                _description_record(
                    document_id="doc-b",
                    display_name="alpha brief",
                    description_text="Alpha case file.",
                ),
                _description_record(
                    document_id="doc-a",
                    display_name="Alpha Brief",
                    description_text="Alpha case file.",
                ),
                _description_record(
                    document_id="doc-c",
                    display_name="Zulu Brief",
                    description_text="Alpha case file.",
                ),
            ),
            limit=3,
        )
    )

    assert tuple(candidate.document_id for candidate in response.candidates) == (
        "doc-a",
        "doc-b",
        "doc-c",
    )


def test_description_selection_omits_zero_score_candidates_by_default(
    tmp_path: Path,
) -> None:
    service = DescriptionSelectionService(
        storage=FilesystemStorageConfig(root=str(tmp_path / "artifacts"))
    )

    response = service.select(
        DescriptionSelectionRequest(
            collection_id="collection-zero-score",
            selection_run_id="selection-004",
            query="alpha revenue",
            descriptions=(
                _description_record(
                    document_id="doc-match",
                    display_name="Alpha File",
                    description_text="Revenue summary for alpha.",
                ),
                _description_record(
                    document_id="doc-zero-a",
                    display_name="Bravo File",
                    description_text="Completely unrelated memo.",
                ),
                _description_record(
                    document_id="doc-zero-b",
                    display_name="Charlie File",
                    description_text="Completely unrelated brief.",
                ),
            ),
            limit=2,
        )
    )

    assert tuple(candidate.document_id for candidate in response.candidates) == ("doc-match",)
    assert len(response.candidates) == 1


def test_description_selection_zero_score_fillers_are_opt_in(tmp_path: Path) -> None:
    service = DescriptionSelectionService(
        storage=FilesystemStorageConfig(root=str(tmp_path / "artifacts"))
    )

    response = service.select(
        DescriptionSelectionRequest(
            collection_id="collection-zero-score-fillers",
            selection_run_id="selection-004b",
            query="alpha revenue",
            include_zero_score_fillers=True,
            descriptions=(
                _description_record(
                    document_id="doc-match",
                    display_name="Alpha File",
                    description_text="Revenue summary for alpha.",
                ),
                _description_record(
                    document_id="doc-zero-a",
                    display_name="Bravo File",
                    description_text="Completely unrelated memo.",
                ),
                _description_record(
                    document_id="doc-zero-b",
                    display_name="Charlie File",
                    description_text="Completely unrelated brief.",
                ),
            ),
            limit=2,
        )
    )

    assert tuple(candidate.document_id for candidate in response.candidates) == (
        "doc-match",
        "doc-zero-a",
    )
    assert response.candidates[1].score == 0.0


def test_description_selection_via_gateway(tmp_path: Path) -> None:
    service = DescriptionSelectionService(
        storage=FilesystemStorageConfig(root=str(tmp_path / "artifacts"))
    )
    gateway = _gateway(
        tmp_path,
        output_json={
            "candidates": [
                {
                    "document_id": "doc-beta",
                    "reason": "Best match for litigation query.",
                    "relevance_score": 0.91,
                },
                {
                    "document_id": "doc-alpha",
                    "reason": "Secondary match for litigation query.",
                    "relevance_score": 0.72,
                },
            ]
        },
    )

    response = service.select(
        DescriptionSelectionRequest(
            collection_id="collection-gateway",
            selection_run_id="selection-005",
            query="beta litigation deadlines",
            descriptions=(
                _description_record(
                    document_id="doc-alpha",
                    display_name="Alpha Revenue Dossier",
                    description_text="Revenue planning document for alpha operations.",
                ),
                _description_record(
                    document_id="doc-beta",
                    display_name="Beta Litigation Memo",
                    description_text="Litigation summary covering beta deadlines and case posture.",
                ),
            ),
            limit=2,
        ),
        gateway=cast(StructuredLLMGateway, gateway),
    )

    assert response.selection_mode is DescriptionSelectionMode.LLM
    assert tuple(candidate.document_id for candidate in response.candidates) == (
        "doc-beta",
        "doc-alpha",
    )


def test_description_selection_shards_and_merges_gateway_results(tmp_path: Path) -> None:
    service = DescriptionSelectionService(
        storage=FilesystemStorageConfig(root=str(tmp_path / "artifacts"))
    )
    records = tuple(
        _description_record(
            document_id=f"doc-{index:03d}",
            display_name=f"Document {index:03d}",
            description_text=f"Description for document {index:03d}.",
        )
        for index in range(30)
    )
    gateway = _QueuedGateway(
        [
            DescriptionSelectionPromptResponse(
                candidates=(
                    DescriptionSelectionPromptCandidate(
                        document_id="doc-003",
                        reason="Top result from first shard.",
                        relevance_score=0.63,
                    ),
                )
            ),
            DescriptionSelectionPromptResponse(
                candidates=(
                    DescriptionSelectionPromptCandidate(
                        document_id="doc-029",
                        reason="Top result from second shard.",
                        relevance_score=0.92,
                    ),
                )
            ),
        ]
    )

    response = service.select(
        DescriptionSelectionRequest(
            collection_id="collection-shards",
            selection_run_id="selection-006",
            query="important description query",
            descriptions=records,
            limit=3,
        ),
        gateway=cast(StructuredLLMGateway, gateway),
    )

    assert gateway.calls == 2
    assert tuple(candidate.document_id for candidate in response.candidates) == (
        "doc-029",
        "doc-003",
    )


def test_description_selection_rejects_unknown_gateway_document_ids(tmp_path: Path) -> None:
    service = DescriptionSelectionService(
        storage=FilesystemStorageConfig(root=str(tmp_path / "artifacts"))
    )
    gateway = _QueuedGateway(
        [
            DescriptionSelectionPromptResponse(
                candidates=(
                    DescriptionSelectionPromptCandidate(
                        document_id="doc-missing",
                        reason="Not actually present.",
                        relevance_score=0.9,
                    ),
                )
            )
        ]
    )

    with pytest.raises(ValueError, match="outside the provided shard"):
        service.select(
            DescriptionSelectionRequest(
                collection_id="collection-invalid-gateway",
                selection_run_id="selection-007",
                query="alpha",
                descriptions=(
                    _description_record(
                        document_id="doc-present",
                        display_name="Present Document",
                        description_text="Alpha description.",
                    ),
                ),
            ),
            gateway=cast(StructuredLLMGateway, gateway),
        )


class _FakeLoaderStore:
    def __init__(self, payloads: dict[str, object]) -> None:
        self._payloads = payloads

    def read_json_artifact(self, ref: str) -> object:
        return self._payloads[ref]


def test_load_document_description_helpers_support_postgres_refs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_ref = build_postgres_artifact_ref(
        run_type="document_description",
        run_id="selection-008",
        document_id="3" * 64,
        artifact_path="manifest.json",
    )
    description_ref = build_postgres_artifact_ref(
        run_type="document_description",
        run_id="selection-008",
        document_id="3" * 64,
        artifact_path="description/document-description.json",
    )
    fake_store = _FakeLoaderStore(
        {
            manifest_ref: {
                "document_id": "3" * 64,
                "description_run_id": "selection-008",
                "artifact_root": "document_description/selection-008",
                "description_path": description_ref,
                "source_tree_manifest_path": "pg://tree/selection-008/manifest.json",
                "source_acquisition_manifest_path": "pg://acquisition/selection-008/manifest.json",
            },
            description_ref: {
                "document_id": "3" * 64,
                "tree_run_id": "tree-run-008",
                "source_manifest_paths": (
                    "pg://acquisition/selection-008/manifest.json",
                    "pg://tree/selection-008/manifest.json",
                ),
                "description_text": "Synthetic postgres-backed description.",
                "description_method": "deterministic_fallback",
                "source_node_ids": ("node-postgres",),
                "settings_digest": "d" * 64,
            },
        }
    )
    monkeypatch.setattr(
        "nullvector.retrieval.load.build_document_store",
        lambda storage: fake_store,
    )
    storage = PostgresStorageConfig(conninfo="postgresql://example/nullvector")

    manifest = load_document_description_manifest(
        manifest_ref,
        storage=storage,
    )
    description = load_document_description(
        description_ref,
        storage=storage,
    )

    assert manifest.description_path == description_ref
    assert description.description_text == "Synthetic postgres-backed description."
