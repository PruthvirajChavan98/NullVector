"""Unit tests for the VLM page transcriber."""

from __future__ import annotations

from pathlib import Path

import pytest

from nullvector.ingest.vlm_transcriber import PageTranscription, VLMPageTranscriber
from nullvector.llm import (
    GatewayAuditConfig,
    GatewayConfig,
    GatewayService,
    NoopProviderAdapter,
    NoopScriptedResponse,
)

PHASE01_FIXTURES = Path("fixtures/pdfs/phase01")
BORN_DIGITAL = PHASE01_FIXTURES / "born_digital_with_outline.pdf"


def _make_gateway(tmp_path: Path, markdown_text: str = "# Hello\n\nWorld") -> GatewayService:
    return GatewayService(
        GatewayConfig(
            default_model="test-vlm",
            audit=GatewayAuditConfig(persist_root=str(tmp_path / "audit")),
        ),
        provider_adapter=NoopProviderAdapter(
            {
                "vlm_page_transcription": NoopScriptedResponse(
                    output_json={
                        "markdown_text": markdown_text,
                        "has_tables": False,
                        "has_images": False,
                    },
                ),
            }
        ),
    )


@pytest.mark.skipif(not BORN_DIGITAL.exists(), reason="fixture PDF not present")
def test_transcribe_document_returns_one_transcription_per_page(tmp_path: Path) -> None:
    gateway = _make_gateway(tmp_path)
    transcriber = VLMPageTranscriber(gateway, dpi=72)

    results = transcriber.transcribe_document(
        str(BORN_DIGITAL),
        document_id="test-doc-id",
    )

    assert isinstance(results, tuple)
    assert len(results) > 0
    for result in results:
        assert isinstance(result, PageTranscription)
        assert result.markdown_text == "# Hello\n\nWorld"
        assert result.has_tables is False
        assert result.has_images is False


@pytest.mark.skipif(not BORN_DIGITAL.exists(), reason="fixture PDF not present")
def test_transcribe_document_page_indices_are_sequential(tmp_path: Path) -> None:
    gateway = _make_gateway(tmp_path)
    transcriber = VLMPageTranscriber(gateway, dpi=72)

    results = transcriber.transcribe_document(
        str(BORN_DIGITAL),
        document_id="test-doc-id",
    )

    indices = [r.page_index for r in results]
    assert indices == list(range(len(results)))


@pytest.mark.skipif(not BORN_DIGITAL.exists(), reason="fixture PDF not present")
def test_transcribe_document_with_tables_flag(tmp_path: Path) -> None:
    gateway = GatewayService(
        GatewayConfig(
            default_model="test-vlm",
            audit=GatewayAuditConfig(persist_root=str(tmp_path / "audit")),
        ),
        provider_adapter=NoopProviderAdapter(
            {
                "vlm_page_transcription": NoopScriptedResponse(
                    output_json={
                        "markdown_text": "| Col A | Col B |\n|-------|-------|\n| 1 | 2 |",
                        "has_tables": True,
                        "has_images": False,
                    },
                ),
            }
        ),
    )
    transcriber = VLMPageTranscriber(gateway, dpi=72)

    results = transcriber.transcribe_document(
        str(BORN_DIGITAL),
        document_id="test-doc-id",
    )

    assert all(r.has_tables is True for r in results)
    assert all(r.has_images is False for r in results)


@pytest.mark.skipif(not BORN_DIGITAL.exists(), reason="fixture PDF not present")
def test_transcribe_document_respects_dpi_setting(tmp_path: Path) -> None:
    gateway = _make_gateway(tmp_path)
    transcriber_low = VLMPageTranscriber(gateway, dpi=36)
    transcriber_high = VLMPageTranscriber(gateway, dpi=300)

    results_low = transcriber_low.transcribe_document(
        str(BORN_DIGITAL),
        document_id="test-doc-id",
    )
    results_high = transcriber_high.transcribe_document(
        str(BORN_DIGITAL),
        document_id="test-doc-id",
    )

    assert len(results_low) == len(results_high)


def test_page_transcription_model_validation() -> None:
    transcription = PageTranscription(
        page_index=0,
        markdown_text="# Test",
        has_tables=True,
        has_images=False,
    )
    assert transcription.page_index == 0
    assert transcription.markdown_text == "# Test"
    assert transcription.has_tables is True
    assert transcription.page_render_path is None


def test_page_transcription_rejects_empty_markdown() -> None:
    with pytest.raises(ValueError):
        PageTranscription(
            page_index=0,
            markdown_text="",
        )
