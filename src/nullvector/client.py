"""Public client facade for end-to-end NullVector workflows."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from pydantic import Field

from nullvector._client_utils import (
    default_run_id,
    derived_run_id,
    infer_source_kind,
    load_model_artifact,
    manifest_ref,
    provider_identity_for,
)
from nullvector.domain.common import NonEmptyStr, NullVectorModel
from nullvector.domain.ledger import (
    AcquisitionRequest,
    AcquisitionRunManifest,
    SourceDocumentKind,
)
from nullvector.domain.retrieval import (
    DocumentDescription,
    DocumentDescriptionManifest,
    DocumentDescriptionRequest,
    RetrievalCorpus,
    RetrievalHit,
    RetrievalManifest,
)
from nullvector.domain.tree import TreeBuildManifest, TreeBuildRequest
from nullvector.errors import ClientValidationError, DocumentNotIndexedError, translate_error
from nullvector.ingest.acquisition_service import AcquisitionService
from nullvector.llm.protocols import StructuredLLMGateway
from nullvector.observability.logging import resolve_runtime_logger
from nullvector.presets import DocumentPreset, resolve_preset
from nullvector.retrieval import (
    DocumentDescriptionBuilder,
    QAResponse,
    QueryPlanner,
    RetrievalCorpusBuilder,
    RetrievalQAService,
    RetrievalRanker,
    RetrievalService,
    load_document_description,
    load_document_description_manifest,
    load_retrieval_corpus,
    load_retrieval_manifest,
)
from nullvector.storage import StorageConfig
from nullvector.storage._serialization import canonical_json_text
from nullvector.tree import build_tree


class ClientIngestResult(NullVectorModel):
    """Stable result payload for the client's query-ready ingest pipeline."""

    document_id: NonEmptyStr
    acquisition_manifest_path: NonEmptyStr
    tree_manifest_path: NonEmptyStr
    retrieval_manifest_path: NonEmptyStr
    description_manifest_path: NonEmptyStr | None = None


class _ClientCatalogEntry(NullVectorModel):
    """Latest known client-managed artifact refs for one document."""

    document_id: NonEmptyStr
    acquisition_manifest_path: NonEmptyStr | None = None
    tree_manifest_path: NonEmptyStr | None = None
    retrieval_manifest_path: NonEmptyStr | None = None
    description_manifest_path: NonEmptyStr | None = None


class _ClientCatalog(NullVectorModel):
    """Client-local catalog persisted under the workspace root."""

    documents: dict[NonEmptyStr, _ClientCatalogEntry] = Field(default_factory=dict)


class NullVectorClient:
    """High-level DX facade over acquisition, tree, retrieval, and QA flows."""

    def __init__(
        self,
        storage_path: str | Path,
        *,
        storage: StorageConfig | None = None,
        gateway: StructuredLLMGateway | None = None,
        logger: Any = None,
    ) -> None:
        self._storage_path = Path(storage_path).resolve()
        self._storage = storage
        self._gateway = gateway
        self._logger = resolve_runtime_logger(logger)

    @property
    def storage_path(self) -> Path:
        """Return the client workspace root used for local DX state."""

        return self._storage_path

    async def async_ingest(self, source_path: str | Path, **kwargs: Any) -> ClientIngestResult:
        """Async wrapper around :meth:`ingest`."""

        return await asyncio.to_thread(self.ingest, source_path, **kwargs)

    async def async_build_tree(
        self,
        acquisition_manifest_path: str,
        **kwargs: Any,
    ) -> TreeBuildManifest:
        """Async wrapper around :meth:`build_tree`."""

        return await asyncio.to_thread(self.build_tree, acquisition_manifest_path, **kwargs)

    async def async_build_retrieval(
        self,
        acquisition_manifest_path: str,
        **kwargs: Any,
    ) -> RetrievalManifest:
        """Async wrapper around :meth:`build_retrieval`."""

        return await asyncio.to_thread(self.build_retrieval, acquisition_manifest_path, **kwargs)

    async def async_build_description(
        self,
        acquisition_manifest_path: str,
        tree_manifest_path: str,
        **kwargs: Any,
    ) -> DocumentDescriptionManifest:
        """Async wrapper around :meth:`build_description`."""

        return await asyncio.to_thread(
            self.build_description,
            acquisition_manifest_path,
            tree_manifest_path,
            **kwargs,
        )

    async def async_search(self, query: str, **kwargs: Any) -> tuple[RetrievalHit, ...]:
        """Async wrapper around :meth:`search`."""

        return await asyncio.to_thread(self.search, query, **kwargs)

    async def async_ask(self, query: str, **kwargs: Any) -> QAResponse:
        """Async wrapper around :meth:`ask`."""

        return await asyncio.to_thread(self.ask, query, **kwargs)

    def acquire(
        self,
        source_path: str | Path,
        *,
        source_kind: str | SourceDocumentKind | None = None,
        preset: str | DocumentPreset | None = None,
        acquisition_run_id: str | None = None,
    ) -> tuple[AcquisitionRunManifest, str]:
        """Acquire one document without building a tree or retrieval corpus.

        Returns the acquisition manifest and its storage reference path.
        """
        try:
            resolved_preset = resolve_preset(preset)
        except Exception as exc:
            raise translate_error(exc, operation="validation") from exc
        manifest, ref = self._acquire_manifest(
            Path(source_path),
            source_kind=source_kind,
            preset=resolved_preset,
            acquisition_run_id=acquisition_run_id,
        )
        return manifest, ref

    def ingest(
        self,
        source_path: str | Path,
        *,
        source_kind: str | SourceDocumentKind | None = None,
        preset: str | DocumentPreset | None = None,
        summarize: bool | None = None,
        acquisition_run_id: str | None = None,
        tree_run_id: str | None = None,
        retrieval_run_id: str | None = None,
    ) -> ClientIngestResult:
        """Acquire, build a tree, and build retrieval artifacts for one document."""

        try:
            resolved_preset = resolve_preset(preset)
        except Exception as exc:
            raise translate_error(exc, operation="validation") from exc

        source_path_obj = Path(source_path)
        try:
            acquisition_manifest, acquisition_manifest_path = self._acquire_manifest(
                source_path_obj,
                source_kind=source_kind,
                preset=resolved_preset,
                acquisition_run_id=acquisition_run_id,
            )
        except Exception as exc:
            raise translate_error(exc, operation="ingest") from exc

        resolved_tree_run_id = tree_run_id or default_run_id(source_path_obj, "tree")
        try:
            tree_manifest, tree_manifest_path = self._build_tree_manifest(
                acquisition_manifest_path,
                tree_run_id=resolved_tree_run_id,
                preset=resolved_preset,
                summarize=summarize,
                update_catalog=False,
            )
        except Exception as exc:
            raise translate_error(exc, operation="tree") from exc

        resolved_retrieval_run_id = retrieval_run_id or default_run_id(source_path_obj, "retrieval")
        try:
            retrieval_manifest, retrieval_manifest_path = self._build_retrieval_manifest(
                acquisition_manifest_path,
                tree_manifest_path=tree_manifest_path,
                retrieval_run_id=resolved_retrieval_run_id,
                update_catalog=False,
            )
        except Exception as exc:
            raise translate_error(exc, operation="retrieval") from exc

        self._update_catalog(
            acquisition_manifest.document_id,
            acquisition_manifest_path=acquisition_manifest_path,
            tree_manifest_path=tree_manifest_path,
            retrieval_manifest_path=retrieval_manifest_path,
        )
        return ClientIngestResult(
            document_id=acquisition_manifest.document_id,
            acquisition_manifest_path=acquisition_manifest_path,
            tree_manifest_path=tree_manifest_path,
            retrieval_manifest_path=retrieval_manifest_path,
        )

    def build_tree(
        self,
        acquisition_manifest_path: str,
        *,
        tree_run_id: str | None = None,
        preset: str | DocumentPreset | None = None,
        summarize: bool | None = None,
    ) -> TreeBuildManifest:
        """Build a tree from one acquisition manifest and update the local catalog."""

        try:
            resolved_preset = resolve_preset(preset)
        except Exception as exc:
            raise translate_error(exc, operation="validation") from exc
        try:
            manifest, _ = self._build_tree_manifest(
                acquisition_manifest_path,
                tree_run_id=tree_run_id,
                preset=resolved_preset,
                summarize=summarize,
                update_catalog=True,
            )
        except Exception as exc:
            raise translate_error(exc, operation="tree") from exc
        return manifest

    def build_retrieval(
        self,
        acquisition_manifest_path: str,
        *,
        tree_manifest_path: str | None = None,
        retrieval_run_id: str | None = None,
    ) -> RetrievalManifest:
        """Build retrieval artifacts and update the local catalog."""

        try:
            manifest, _ = self._build_retrieval_manifest(
                acquisition_manifest_path,
                tree_manifest_path=tree_manifest_path,
                retrieval_run_id=retrieval_run_id,
                update_catalog=True,
            )
        except Exception as exc:
            raise translate_error(exc, operation="retrieval") from exc
        return manifest

    def build_description(
        self,
        acquisition_manifest_path: str,
        tree_manifest_path: str,
        *,
        description_run_id: str | None = None,
        preset: str | DocumentPreset | None = None,
    ) -> DocumentDescriptionManifest:
        """Build a document-level description and update the local catalog."""

        try:
            resolved_preset = resolve_preset(preset)
        except Exception as exc:
            raise translate_error(exc, operation="validation") from exc
        try:
            manifest = self._build_description_manifest(
                acquisition_manifest_path,
                tree_manifest_path,
                description_run_id=description_run_id,
                preset=resolved_preset,
            )
        except Exception as exc:
            raise translate_error(exc, operation="retrieval") from exc
        return manifest

    def search(
        self,
        query: str,
        *,
        retrieval_manifest_path: str | None = None,
        ingest_result: ClientIngestResult | None = None,
        document_id: str | None = None,
        limit: int = 10,
    ) -> tuple[RetrievalHit, ...]:
        """Search one resolved retrieval corpus."""

        if limit < 1:
            msg = f"limit must be >= 1, got {limit}"
            raise ClientValidationError(msg)
        try:
            corpus = self._load_retrieval_corpus_for_query(
                retrieval_manifest_path=retrieval_manifest_path,
                ingest_result=ingest_result,
                document_id=document_id,
            )
            return self._retrieval_service().search(corpus=corpus, query=query, limit=limit)
        except Exception as exc:
            raise translate_error(exc, operation="query") from exc

    def ask(
        self,
        query: str,
        *,
        retrieval_manifest_path: str | None = None,
        ingest_result: ClientIngestResult | None = None,
        document_id: str | None = None,
        limit: int = 5,
    ) -> QAResponse:
        """Answer one query over a resolved retrieval corpus."""

        if limit < 1:
            msg = f"limit must be >= 1, got {limit}"
            raise ClientValidationError(msg)
        try:
            corpus = self._load_retrieval_corpus_for_query(
                retrieval_manifest_path=retrieval_manifest_path,
                ingest_result=ingest_result,
                document_id=document_id,
            )
            qa_service = RetrievalQAService(
                self._retrieval_service(),
                gateway=self._gateway,
                document_description=self._load_catalogued_description(corpus.document_id),
                logger=self._logger,
            )
            return qa_service.answer(corpus=corpus, query=query, limit=limit)
        except Exception as exc:
            raise translate_error(exc, operation="query") from exc

    def _catalog_path(self) -> Path:
        return self._storage_path / ".nullvector" / "catalog.json"

    def _load_catalog(self) -> _ClientCatalog:
        catalog_path = self._catalog_path()
        if not catalog_path.exists():
            return _ClientCatalog()
        return _ClientCatalog.model_validate_json(catalog_path.read_text(encoding="utf-8"))

    def _write_catalog(self, catalog: _ClientCatalog) -> None:
        catalog_path = self._catalog_path()
        catalog_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = catalog_path.with_name(f"{catalog_path.name}.tmp")
        temp_path.write_text(
            canonical_json_text(catalog.model_dump(mode="json"), pretty=True),
            encoding="utf-8",
        )
        temp_path.replace(catalog_path)

    def _update_catalog(
        self,
        document_id: str,
        *,
        acquisition_manifest_path: str | None = None,
        tree_manifest_path: str | None = None,
        retrieval_manifest_path: str | None = None,
        description_manifest_path: str | None = None,
    ) -> None:
        catalog = self._load_catalog()
        current = catalog.documents.get(document_id, _ClientCatalogEntry(document_id=document_id))
        updated = current.model_copy(
            update={
                "acquisition_manifest_path": (
                    acquisition_manifest_path or current.acquisition_manifest_path
                ),
                "tree_manifest_path": tree_manifest_path or current.tree_manifest_path,
                "retrieval_manifest_path": (
                    retrieval_manifest_path or current.retrieval_manifest_path
                ),
                "description_manifest_path": (
                    description_manifest_path or current.description_manifest_path
                ),
            }
        )
        documents = dict(catalog.documents)
        documents[document_id] = updated
        self._write_catalog(catalog.model_copy(update={"documents": documents}))

    def _resolve_catalog_entry(self, document_id: str) -> _ClientCatalogEntry:
        catalog = self._load_catalog()
        entry = catalog.documents.get(document_id)
        if entry is None:
            msg = f"document_id {document_id!r} is not indexed in {self._catalog_path()}"
            raise DocumentNotIndexedError(msg)
        return entry

    def _resolve_retrieval_manifest_path(
        self,
        *,
        retrieval_manifest_path: str | None,
        ingest_result: ClientIngestResult | None,
        document_id: str | None,
    ) -> str:
        if retrieval_manifest_path is not None:
            return retrieval_manifest_path
        if ingest_result is not None:
            return ingest_result.retrieval_manifest_path
        if document_id is not None:
            entry = self._resolve_catalog_entry(document_id)
            if entry.retrieval_manifest_path is None:
                msg = (
                    f"document_id {document_id!r} does not have a retrieval manifest in the catalog"
                )
                raise DocumentNotIndexedError(msg)
            return entry.retrieval_manifest_path
        msg = "search and ask require retrieval_manifest_path, ingest_result, or document_id"
        raise DocumentNotIndexedError(msg)

    def _retrieval_service(self) -> RetrievalService:
        return RetrievalService(
            QueryPlanner(),
            RetrievalRanker(),
            logger=self._logger,
            storage=self._storage,
        )

    def _load_retrieval_corpus_for_query(
        self,
        *,
        retrieval_manifest_path: str | None,
        ingest_result: ClientIngestResult | None,
        document_id: str | None,
    ) -> RetrievalCorpus:
        manifest = load_retrieval_manifest(
            self._resolve_retrieval_manifest_path(
                retrieval_manifest_path=retrieval_manifest_path,
                ingest_result=ingest_result,
                document_id=document_id,
            ),
            storage=self._storage,
        )
        return load_retrieval_corpus(manifest.corpus_path, storage=self._storage)

    def _load_catalogued_description(self, document_id: str) -> DocumentDescription | None:
        catalog = self._load_catalog()
        entry = catalog.documents.get(document_id)
        if entry is None or entry.description_manifest_path is None:
            return None
        manifest = load_document_description_manifest(
            entry.description_manifest_path,
            storage=self._storage,
        )
        return load_document_description(manifest.description_path, storage=self._storage)

    def _acquire_manifest(
        self,
        source_path: Path,
        *,
        source_kind: str | SourceDocumentKind | None,
        preset: DocumentPreset,
        acquisition_run_id: str | None,
    ) -> tuple[AcquisitionRunManifest, str]:
        resolved_source_kind = infer_source_kind(source_path, source_kind)
        resolved_acquisition_run_id = acquisition_run_id or default_run_id(
            source_path,
            "acquisition",
        )
        manifest = AcquisitionService(logger=self._logger, storage=self._storage).acquire(
            AcquisitionRequest(
                source_path=str(source_path),
                acquisition_run_id=resolved_acquisition_run_id,
                artifact_root=str(self._storage_path),
                source_kind=resolved_source_kind,
                provider_identity=provider_identity_for(resolved_source_kind),
                settings=preset.acquisition_settings,
            )
        )
        return (
            manifest,
            manifest_ref(
                run_type="acquisition",
                run_id=resolved_acquisition_run_id,
                document_id=manifest.document_id,
                artifact_root=manifest.artifact_root,
            ),
        )

    def _build_tree_manifest(
        self,
        acquisition_manifest_path: str,
        *,
        tree_run_id: str | None,
        preset: DocumentPreset,
        summarize: bool | None,
        update_catalog: bool,
    ) -> tuple[TreeBuildManifest, str]:
        acquisition_manifest = load_model_artifact(
            AcquisitionRunManifest,
            acquisition_manifest_path,
            storage=self._storage,
        )
        resolved_tree_run_id = tree_run_id or derived_run_id(
            acquisition_manifest.acquisition_run_id,
            current_stage="acquisition",
            target_stage="tree",
        )
        manifest = build_tree(
            TreeBuildRequest(
                acquisition_manifest_path=acquisition_manifest_path,
                tree_run_id=resolved_tree_run_id,
                summarize=(preset.tree_summarize if summarize is None else summarize),
                settings=preset.tree_settings,
            ),
            gateway=self._gateway,
            logger=self._logger,
            storage=self._storage,
        )
        tree_manifest_path = manifest_ref(
            run_type="tree",
            run_id=resolved_tree_run_id,
            document_id=manifest.document_id,
            artifact_root=manifest.artifact_root,
        )
        if update_catalog:
            self._update_catalog(
                manifest.document_id,
                acquisition_manifest_path=acquisition_manifest_path,
                tree_manifest_path=tree_manifest_path,
            )
        return manifest, tree_manifest_path

    def _build_retrieval_manifest(
        self,
        acquisition_manifest_path: str,
        *,
        tree_manifest_path: str | None,
        retrieval_run_id: str | None,
        update_catalog: bool,
    ) -> tuple[RetrievalManifest, str]:
        acquisition_manifest = load_model_artifact(
            AcquisitionRunManifest,
            acquisition_manifest_path,
            storage=self._storage,
        )
        tree_manifest = (
            load_model_artifact(TreeBuildManifest, tree_manifest_path, storage=self._storage)
            if tree_manifest_path is not None
            else None
        )
        resolved_retrieval_run_id = retrieval_run_id or (
            tree_manifest.tree_run_id
            if tree_manifest is not None
            else acquisition_manifest.acquisition_run_id
        )
        manifest = RetrievalCorpusBuilder(logger=self._logger, storage=self._storage).build(
            acquisition_manifest_path=acquisition_manifest_path,
            tree_manifest_path=tree_manifest_path,
            retrieval_run_id=resolved_retrieval_run_id,
        )
        retrieval_manifest_path = manifest_ref(
            run_type="retrieval",
            run_id=resolved_retrieval_run_id,
            document_id=manifest.document_id,
            artifact_root=manifest.artifact_root,
        )
        if update_catalog:
            self._update_catalog(
                manifest.document_id,
                acquisition_manifest_path=acquisition_manifest_path,
                tree_manifest_path=tree_manifest_path,
                retrieval_manifest_path=retrieval_manifest_path,
            )
        return manifest, retrieval_manifest_path

    def _build_description_manifest(
        self,
        acquisition_manifest_path: str,
        tree_manifest_path: str,
        *,
        description_run_id: str | None,
        preset: DocumentPreset,
    ) -> DocumentDescriptionManifest:
        tree_manifest = load_model_artifact(
            TreeBuildManifest,
            tree_manifest_path,
            storage=self._storage,
        )
        resolved_description_run_id = description_run_id or derived_run_id(
            tree_manifest.tree_run_id,
            current_stage="tree",
            target_stage="description",
        )
        manifest = DocumentDescriptionBuilder(
            logger=self._logger,
            storage=self._storage,
        ).build(
            DocumentDescriptionRequest(
                acquisition_manifest_path=acquisition_manifest_path,
                tree_manifest_path=tree_manifest_path,
                description_run_id=resolved_description_run_id,
                settings=preset.document_description_settings,
            ),
            gateway=self._gateway,
        )
        description_manifest_path = manifest_ref(
            run_type="document_description",
            run_id=resolved_description_run_id,
            document_id=manifest.document_id,
            artifact_root=manifest.artifact_root,
        )
        self._update_catalog(
            manifest.document_id,
            acquisition_manifest_path=acquisition_manifest_path,
            tree_manifest_path=tree_manifest_path,
            description_manifest_path=description_manifest_path,
        )
        return manifest


__all__ = [
    "ClientIngestResult",
    "NullVectorClient",
]
