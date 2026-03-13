"""Provider adapters for the attachment-only multimodal gateway."""

from nullvector.llm.multimodal_gateway.providers.noop import (
    NoopMultimodalProviderAdapter,
    NoopMultimodalResponse,
)

__all__ = [
    "NoopMultimodalProviderAdapter",
    "NoopMultimodalResponse",
]
