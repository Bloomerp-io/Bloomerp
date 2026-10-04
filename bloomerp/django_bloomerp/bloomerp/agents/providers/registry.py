"""The single process-wide AI provider registry; registration makes no network calls."""

from bloomerp.agents.providers.definition import AIProviderDefinition
from bloomerp.agents.runtime import AgentRuntime, AgentRuntimeConfig
from bloomerp.utils.registry import BaseRegistry


class AIProviderRegistry(BaseRegistry[AIProviderDefinition]):
    """Hold built-in and project-specific provider definitions."""

    def register(self, key: str, obj: AIProviderDefinition) -> None:
        """Register one stable key and reject mismatched definition identities."""
        if key != obj.id:
            raise ValueError("Provider registry key must match the definition id")
        super().register(key, obj)


AI_PROVIDER_REGISTRY = AIProviderRegistry(AIProviderDefinition)


def provider_choices() -> list[tuple[str, str]]:
    """Expose registered provider labels to Django without freezing extension choices."""
    return [(key, definition.name) for key, definition in AI_PROVIDER_REGISTRY.items()]


def pydantic_runtime(config: AgentRuntimeConfig) -> AgentRuntime:
    """Construct a fresh adapter after validating the resolved provider configuration."""
    definition = AI_PROVIDER_REGISTRY.get(config.provider)
    if definition is None:
        raise ValueError("Unknown AI provider")
    definition.config_schema.model_validate(config.parameters)
    from bloomerp.agents.runtimes.pydantic_ai import PydanticAIRuntime

    return PydanticAIRuntime()


def register_builtins() -> None:
    """Register provider-owned integrations without allocating clients or discovering models."""
    from .builtins.pydantic_ai_common import PydanticAIProvider, PydanticAISettings
    from .builtins.pydantic_anthropic import AnthropicSettings, create_anthropic_model
    from .builtins.pydantic_deepseek import create_deepseek_model
    from .builtins.pydantic_open_ai import create_openai_chat_model, create_openai_model
    from .builtins.pydantic_openrouter import create_openrouter_model

    descriptions = {
        "openai": "Use OpenAI agents through the Responses API, including compatible reasoning models.",
        "openai_chat": "Use OpenAI or compatible endpoints through the Chat Completions API.",
        "deepseek": "Use DeepSeek models through its OpenAI-compatible Chat Completions API.",
        "anthropic": "Use Claude models through the Anthropic Messages API.",
        "openrouter": "Use OpenRouter with a vendor/model identifier. Available tools and settings depend on the selected model.",
    }
    for key, name, factory, schema in [
        ("openai", "OpenAI", create_openai_model, PydanticAISettings),
        (
            "openai_chat",
            "OpenAI Chat Completions",
            create_openai_chat_model,
            PydanticAISettings,
        ),
        ("deepseek", "DeepSeek", create_deepseek_model, PydanticAISettings),
        ("anthropic", "Anthropic", create_anthropic_model, AnthropicSettings),
        ("openrouter", "OpenRouter", create_openrouter_model, PydanticAISettings),
    ]:
        AI_PROVIDER_REGISTRY.register(
            key,
            AIProviderDefinition(
                id=key,
                name=name,
                description=descriptions[key],
                runtime_factory=pydantic_runtime,
                config_schema=schema,
                integration=PydanticAIProvider(factory, schema),
            ),
        )


register_builtins()
