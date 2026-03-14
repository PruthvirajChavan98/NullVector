"""Provider adapters for the attachment-only multimodal gateway."""

from nullvector.llm.multimodal_gateway.providers.litellm_sdk import (
    LiteLLMMultimodalAdapter,
)
from nullvector.llm.multimodal_gateway.providers.noop import (
    NoopMultimodalProviderAdapter,
    NoopMultimodalResponse,
)

__all__ = [
    "LiteLLMMultimodalAdapter",
    "NoopMultimodalProviderAdapter",
    "NoopMultimodalResponse",
]
