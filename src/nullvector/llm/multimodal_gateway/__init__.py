"""Attachment-only multimodal gateway exports."""

from nullvector.llm.multimodal_gateway.errors import MultimodalGatewayError
from nullvector.llm.multimodal_gateway.protocols import (
    MultimodalProviderAdapter,
    StructuredMultimodalGateway,
)
from nullvector.llm.multimodal_gateway.providers import (
    LiteLLMMultimodalAdapter,
    NoopMultimodalProviderAdapter,
    NoopMultimodalResponse,
)
from nullvector.llm.multimodal_gateway.service import (
    MultimodalGatewayService,
    VisualEnrichmentService,
)
from nullvector.llm.multimodal_gateway.types import (
    MultimodalAssuranceMode,
    MultimodalFailureCategory,
    MultimodalGatewayAuditRecord,
    MultimodalGatewayConfig,
    MultimodalGatewayFailure,
    MultimodalGatewayRequest,
    MultimodalGatewaySuccess,
    MultimodalProviderConfig,
    MultimodalUsage,
    RegionImageInput,
    VisualInsightResponse,
)

__all__ = [
    "LiteLLMMultimodalAdapter",
    "MultimodalAssuranceMode",
    "MultimodalFailureCategory",
    "MultimodalGatewayAuditRecord",
    "MultimodalGatewayConfig",
    "MultimodalGatewayError",
    "MultimodalGatewayFailure",
    "MultimodalGatewayRequest",
    "MultimodalGatewayService",
    "MultimodalGatewaySuccess",
    "MultimodalProviderAdapter",
    "MultimodalProviderConfig",
    "MultimodalUsage",
    "NoopMultimodalProviderAdapter",
    "NoopMultimodalResponse",
    "RegionImageInput",
    "StructuredMultimodalGateway",
    "VisualEnrichmentService",
    "VisualInsightResponse",
]
