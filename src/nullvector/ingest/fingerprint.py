"""Source fingerprinting helpers."""

from __future__ import annotations

import hashlib
from pathlib import Path

from nullvector.domain.ledger import (
    AcquisitionSettings,
    DocumentFingerprint,
    SourceDocumentKind,
)
from nullvector.ingest._markdown import count_markdown_logical_pages
from nullvector.ingest.errors import InvalidSourceError
from nullvector.ingest.pdf_backend import open_document

_HASH_CHUNK_SIZE = 1024 * 1024


def _sha256_path(source: Path) -> str:
    digest = hashlib.sha256()
    with source.open("rb") as handle:
        while chunk := handle.read(_HASH_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint_document(
    source_path: str,
    *,
    source_kind: SourceDocumentKind = SourceDocumentKind.PDF,
    acquisition_settings: AcquisitionSettings | None = None,
) -> DocumentFingerprint:
    """Fingerprint a readable source and record its deterministic page count."""

    source = Path(source_path)
    if not source.exists():
        raise InvalidSourceError("source document does not exist", source_path=str(source))
    if not source.is_file():
        raise InvalidSourceError("source path must be a file", source_path=str(source))

    sha256 = _sha256_path(source)

    if source_kind is SourceDocumentKind.MARKDOWN:
        settings = acquisition_settings or AcquisitionSettings()
        page_count = count_markdown_logical_pages(
            str(source.resolve()),
            settings.markdown,
        )
    else:
        try:
            with open_document(str(source)) as document:
                page_count = document.page_count
        except RuntimeError as exc:
            raise InvalidSourceError(
                "source PDF could not be opened",
                source_path=str(source),
            ) from exc

    return DocumentFingerprint(
        document_id=sha256,
        source_path=str(source.resolve()),
        sha256=sha256,
        file_size_bytes=source.stat().st_size,
        page_count=page_count,
    )
