"""Integration tests for the Phase 03 LLM gateway and repair boundary."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from pydantic import BaseModel

from nullvector.domain import RepairKind, RepairRequest, TreeBuildRequest
from nullvector.llm import (
    GatewayAssuranceMode,
    GatewayAuditConfig,
    GatewayAuthError,
    GatewayConfig,
    GatewayContextLengthError,
    GatewayFailureCategory,
    GatewayProviderRefusalError,
    GatewayRequest,
    GatewayService,
    LLMMessage,
    LLMRole,
    OpenAIProviderConfig,
    OpenAIResponsesHTTPAdapter,
    StructuredOutputMode,
    evaluate_repairs,
)
from nullvector.tree import build_tree
from nullvector.tree import service as tree_service_module

from ..support.acquisition_fixtures import convert_legacy_parse_fixture_to_acquisition

FIXTURE_ROOT = Path("fixtures/phase02/inputs")


class EchoResponse(BaseModel):
    """Simple structured response model for OpenAI adapter tests."""

    message: str


def openai_config(tmp_path: Path) -> GatewayConfig:
    return GatewayConfig(
        provider=OpenAIProviderConfig(model="gpt-4.1-mini"),
        audit=GatewayAuditConfig(persist_root=str(tmp_path / "audit")),
        structured_output_mode_preference=StructuredOutputMode.PROVIDER_NATIVE,
    )


def make_request(operation_name: str) -> GatewayRequest[EchoResponse]:
    return GatewayRequest[EchoResponse](
        operation_name=operation_name,
        messages=(LLMMessage(role=LLMRole.USER, content="Return a greeting"),),
        response_model=EchoResponse,
        structured_output_mode=StructuredOutputMode.PROVIDER_NATIVE,
    )


@pytest.mark.integration
def test_openai_responses_adapter_strict_success_with_mocked_transport(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/responses"
        payload = json.loads(request.content.decode("utf-8"))
        assert payload["text"]["format"]["type"] == "json_schema"
        return httpx.Response(
            200,
            headers={"x-request-id": "req-openai-1"},
            json={
                "id": "resp-openai-1",
                "output": [
                    {
                        "content": [
                            {
                                "type": "output_text",
                                "text": '{"message":"hello from openai"}',
                            }
                        ]
                    }
                ],
                "usage": {
                    "input_tokens": 3,
                    "output_tokens": 4,
                    "total_tokens": 7,
                },
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.openai.com")
    gateway = GatewayService(
        openai_config(tmp_path),
        provider_adapter=OpenAIResponsesHTTPAdapter(client=client),
    )

    success = gateway.invoke(make_request("openai-success"))

    assert success.assurance_mode is GatewayAssuranceMode.PROVIDER_NATIVE_STRICT
    assert success.output.message == "hello from openai"
    assert success.provider_request_id == "req-openai-1"


@pytest.mark.integration
def test_openai_responses_refusal_is_typed_and_not_retried(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleep_calls: list[float] = []
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            headers={"x-request-id": "req-openai-refusal"},
            json={
                "id": "resp-openai-refusal",
                "output": [
                    {
                        "content": [
                            {
                                "type": "refusal",
                                "refusal": "safety refusal",
                            }
                        ]
                    }
                ],
            },
        )

    gateway = GatewayService(
        openai_config(tmp_path),
        provider_adapter=OpenAIResponsesHTTPAdapter(
            client=httpx.Client(
                transport=httpx.MockTransport(handler), base_url="https://api.openai.com"
            ),
        ),
        sleep_fn=sleep_calls.append,
    )

    with pytest.raises(GatewayProviderRefusalError) as exc_info:
        gateway.invoke(make_request("openai-refusal"))

    assert exc_info.value.failure.category is GatewayFailureCategory.PROVIDER_REFUSAL
    assert sleep_calls == []
    assert exc_info.value.failure.attempt_count == 1


@pytest.mark.integration
@pytest.mark.parametrize(
    ("status_code", "error_message", "expected_error"),
    [
        (401, "invalid api key", GatewayAuthError),
        (400, "context length exceeded for this model", GatewayContextLengthError),
    ],
)
def test_openai_non_retryable_failures_do_not_backoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
    error_message: str,
    expected_error: type[Exception],
) -> None:
    sleep_calls: list[float] = []
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            status_code,
            headers={"x-request-id": "req-openai-error"},
            json={"error": {"message": error_message, "code": "bad_request"}},
        )

    gateway_config = openai_config(tmp_path)
    gateway = GatewayService(
        gateway_config,
        provider_adapter=OpenAIResponsesHTTPAdapter(
            client=httpx.Client(
                transport=httpx.MockTransport(handler), base_url="https://api.openai.com"
            ),
        ),
        sleep_fn=sleep_calls.append,
    )

    with pytest.raises(expected_error):
        gateway.invoke(make_request("openai-error"))

    assert sleep_calls == []


def copy_fixture(case_name: str, tmp_path: Path) -> Path:
    destination = tmp_path / case_name
    shutil.copytree(FIXTURE_ROOT / case_name, destination)
    return convert_legacy_parse_fixture_to_acquisition(destination)


@pytest.mark.integration
def test_evaluate_repairs_emits_typed_decisions_without_breaking_tree_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    acquisition_manifest_path = copy_fixture("clean_outline", tmp_path)
    tree_run_id = "gateway-repair-tree"
    audit_root = (
        acquisition_manifest_path.parent / "tree" / tree_run_id / "repair" / "gateway-audit"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        decision_payload = {
            "request_id": payload.get("metadata", {}).get("request_id", "repair-request"),
            "status": "proposal_generated",
            "message": "normalize title casing",
            "proposed_title": "Overview",
        }
        return httpx.Response(
            200,
            headers={"x-request-id": "req-gateway-repair"},
            json={
                "id": "resp-gateway-repair",
                "output": [
                    {
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(decision_payload),
                            }
                        ]
                    }
                ],
                "usage": {
                    "input_tokens": 8,
                    "output_tokens": 5,
                    "total_tokens": 13,
                },
            },
        )

    tree_service_any = cast(Any, tree_service_module)
    original_build_hierarchy = cast(Any, tree_service_any.build_hierarchy)

    def wrapped_build_hierarchy(*args: Any, **kwargs: Any) -> tuple[Any, Any, Any]:
        nodes, _, ambiguity_count = original_build_hierarchy(*args, **kwargs)
        if not nodes:
            return nodes, (), ambiguity_count
        repair_request = RepairRequest(
            request_id="repair-request",
            subject_id=nodes[0].node_id,
            repair_kind=RepairKind.TITLE_NORMALIZATION,
            rationale="synthetic gateway repair integration exercise",
            details={"candidate_title": nodes[0].title},
        )
        return nodes, (repair_request,), ambiguity_count + 1

    monkeypatch.setattr(tree_service_any, "build_hierarchy", wrapped_build_hierarchy)
    gateway_config = openai_config(tmp_path).model_copy(
        update={
            "audit": openai_config(tmp_path).audit.model_copy(
                update={"persist_root": str(audit_root)}
            )
        }
    )
    gateway = GatewayService(
        gateway_config,
        provider_adapter=OpenAIResponsesHTTPAdapter(
            client=httpx.Client(
                transport=httpx.MockTransport(handler), base_url="https://api.openai.com"
            ),
        ),
    )

    class _GatewayBackedRepairEngine:
        def evaluate(self, requests: tuple[RepairRequest, ...]) -> tuple[Any, ...]:
            return evaluate_repairs(gateway, requests)

    repair_engine = _GatewayBackedRepairEngine()

    manifest = build_tree(
        TreeBuildRequest(
            acquisition_manifest_path=str(acquisition_manifest_path),
            tree_run_id=tree_run_id,
        ),
        repair_engine=repair_engine,
    )

    verification_report = cast(
        dict[str, Any],
        json.loads(Path(manifest.verification_report_path).read_text(encoding="utf-8")),
    )
    repair_decisions = cast(
        list[dict[str, Any]],
        json.loads(Path(manifest.repair_decisions_path).read_text(encoding="utf-8")),
    )

    assert verification_report["status"] == "passed"
    assert repair_decisions[0]["status"] == "proposal_generated"
    assert repair_decisions[0]["request_id"] == "repair-request"
    assert (audit_root / "repair-request.json").exists()


@pytest.mark.integration
def test_progress_notebook_executes_for_phase03(tmp_path: Path) -> None:
    output_path = tmp_path / "progress.executed.ipynb"
    subprocess.run(
        [
            sys.executable,
            "scripts/run_progress_notebook.py",
            "--output",
            str(output_path),
        ],
        cwd=Path(__file__).resolve().parents[2],
        check=True,
    )

    executed_notebook = cast(dict[str, Any], json.loads(output_path.read_text(encoding="utf-8")))
    assert output_path.exists()
    assert not any(
        output.get("output_type") == "error"
        for cell in executed_notebook["cells"]
        if cell.get("cell_type") == "code"
        for output in cell.get("outputs", [])
    )


@pytest.mark.integration
def test_phase03_cookbook_notebook_executes_deterministic_sections(tmp_path: Path) -> None:
    output_path = tmp_path / "phase03-cookbook.executed.ipynb"
    subprocess.run(
        [
            sys.executable,
            "scripts/run_progress_notebook.py",
            "--notebook",
            "notebooks/phase03_llm_gateway_cookbook.ipynb",
            "--output",
            str(output_path),
        ],
        cwd=Path(__file__).resolve().parents[2],
        check=True,
    )

    executed_notebook = cast(dict[str, Any], json.loads(output_path.read_text(encoding="utf-8")))
    inspect_cell = next(
        cast(dict[str, Any], cell)
        for cell in executed_notebook["cells"]
        if cell.get("cell_type") == "code"
        and "".join(cast(list[str], cell.get("source", []))).startswith("# inspect results")
    )
    inspect_output = "".join(
        text
        for output in inspect_cell.get("outputs", [])
        if output.get("output_type") == "stream"
        for text in output.get("text", [])
    )
    summary = cast(dict[str, Any], json.loads(inspect_output))

    assert output_path.exists()
    assert not any(
        output.get("output_type") == "error"
        for cell in executed_notebook["cells"]
        if cell.get("cell_type") == "code"
        for output in cell.get("outputs", [])
    )
    assert "moonshot_live_probe" in summary
    assert summary["moonshot_live_probe"]["status"] == "skipped"
    assert "ENABLE_MOONSHOT_LIVE" in summary["moonshot_live_probe"]["reason"]
    assert summary["moonshot_live_probe_audit_excerpt"] is None


@pytest.mark.integration
def test_phase03_cookbook_notebook_declares_probe_honestly() -> None:
    notebook = cast(
        dict[str, Any],
        json.loads(
            Path("notebooks/phase03_llm_gateway_cookbook.ipynb").read_text(encoding="utf-8")
        ),
    )

    markdown_sources = [
        "".join(cast(list[str], cell.get("source", [])))
        for cell in notebook["cells"]
        if cell.get("cell_type") == "markdown"
    ]
    code_sources = [
        "".join(cast(list[str], cell.get("source", [])))
        for cell in notebook["cells"]
        if cell.get("cell_type") == "code"
    ]

    assert any("### Experimental Moonshot Transport Probe" in source for source in markdown_sources)
    assert any(
        source.startswith("# execution: experimental Moonshot transport probe")
        for source in code_sources
    )
    assert not any(
        output.get("output_type") == "error"
        for cell in notebook["cells"]
        if cell.get("cell_type") == "code"
        for output in cell.get("outputs", [])
    )
