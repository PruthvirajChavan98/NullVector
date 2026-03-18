"""Optional convenience adapters for popular LLM provider SDKs.

These adapters are thin wrappers that conform to the ``ProviderAdapter``
protocol. They require the corresponding SDK to be installed separately —
NullVector does **not** declare them as dependencies.

Usage::

    # OpenAI SDK
    from openai import OpenAI
    from nullvector.llm.adapters import OpenAIAdapter

    adapter = OpenAIAdapter(client=OpenAI(api_key="sk-..."))

    # LiteLLM
    from nullvector.llm.adapters import LiteLLMAdapter

    adapter = LiteLLMAdapter()
"""

from nullvector.llm.adapters._litellm import LiteLLMAdapter
from nullvector.llm.adapters._openai import OpenAIAdapter

__all__ = ["LiteLLMAdapter", "OpenAIAdapter"]
