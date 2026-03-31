"""Unit tests for async batch entrypoint wrappers."""

from __future__ import annotations

from typing import cast

import pytest

from nullvector.domain import AcquisitionRequest, BatchResult, TreeBuildRequest
from nullvector.ingest.acquisition_service import AcquisitionService, async_acquire_batch
from nullvector.llm.errors import GatewayConfigurationError
from nullvector.tree.service import TreePipelineService, async_build_tree_batch


@pytest.mark.asyncio
async def test_async_acquire_batch_collects_per_item_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = (
        AcquisitionRequest(source_path="doc-1.pdf", acquisition_run_id="acq-1"),
        AcquisitionRequest(source_path="doc-2.pdf", acquisition_run_id="acq-2"),
    )

    def _fake_acquire(self: AcquisitionService, request: AcquisitionRequest) -> object:
        if request.acquisition_run_id == "acq-2":
            raise RuntimeError("boom")
        return cast(object, {"run_id": request.acquisition_run_id})

    monkeypatch.setattr(AcquisitionService, "acquire", _fake_acquire)

    result = await async_acquire_batch(requests, max_workers=2)

    assert isinstance(result, BatchResult)
    assert len(result.successful) == 1
    assert len(result.failed) == 1
    assert result.failed[0].item_index == 1
    assert result.failed[0].error_type == "RuntimeError"


@pytest.mark.asyncio
async def test_async_build_tree_batch_collects_nonfatal_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = (
        TreeBuildRequest(acquisition_manifest_path="/tmp/acq-1.json", tree_run_id="tree-1"),
        TreeBuildRequest(acquisition_manifest_path="/tmp/acq-2.json", tree_run_id="tree-2"),
    )

    def _fake_build(
        self: TreePipelineService,
        request: TreeBuildRequest,
        **kwargs: object,
    ) -> object:
        del kwargs
        if request.tree_run_id == "tree-2":
            raise RuntimeError("bad tree")
        return cast(object, {"tree_run_id": request.tree_run_id})

    monkeypatch.setattr(TreePipelineService, "build", _fake_build)

    result = await async_build_tree_batch(requests, max_workers=2)

    assert len(result.successful) == 1
    assert len(result.failed) == 1
    assert result.failed[0].item_index == 1
    assert result.failed[0].error_type == "RuntimeError"


@pytest.mark.asyncio
async def test_async_build_tree_batch_reraises_first_batch_fatal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = (
        TreeBuildRequest(acquisition_manifest_path="/tmp/acq-1.json", tree_run_id="tree-1"),
        TreeBuildRequest(acquisition_manifest_path="/tmp/acq-2.json", tree_run_id="tree-2"),
    )

    def _fake_build(
        self: TreePipelineService,
        request: TreeBuildRequest,
        **kwargs: object,
    ) -> object:
        del kwargs
        if request.tree_run_id == "tree-1":
            raise GatewayConfigurationError("bad config")
        raise RuntimeError("secondary failure")

    monkeypatch.setattr(TreePipelineService, "build", _fake_build)

    with pytest.raises(GatewayConfigurationError):
        await async_build_tree_batch(requests, max_workers=2)
