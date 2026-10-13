"""Extensible IM provider registry, shared by setup, adapters and presentation."""

from bloomerp.utils.registry import BaseRegistry
from .builtins.bloomerp import INTERNAL_IM_PROVIDER
from .builtins.slack import SLACK_IM_PROVIDER
from .builtins.whatsapp import WHATSAPP_IM_PROVIDER
from .definition import IMProviderDefinition


class IMProviderRegistry(BaseRegistry[IMProviderDefinition]):
    """Resolve symbolic extension keys and stable stored provider identifiers."""

    def register(self, key: str, obj: IMProviderDefinition) -> None:
        """Reject ambiguous symbolic or persisted identifiers before registration."""
        if not isinstance(obj, IMProviderDefinition):
            raise TypeError("Expected an IMProviderDefinition.")
        for registered_key, provider in self.items():
            if obj.key in (registered_key, provider.key) or key == provider.key:
                raise ValueError(f"IM provider key {obj.key!r} is already registered")
        if obj.adapter_class.provider_key != obj.key:
            raise ValueError("Provider and adapter keys must match.")
        super().register(key, obj)

    def get(self, key: str) -> IMProviderDefinition | None:
        """Resolve either the registration name or provider's persisted key."""
        registered = super().get(key)
        if registered is not None:
            return registered
        for provider in self.values():
            if provider.key == key:
                return provider
        return None

    def choices(self) -> list[tuple[str, str]]:
        """Build setup choices lazily so project-level extensions are included."""
        return [(provider.key, provider.display_name) for provider in self.values()]


IM_PROVIDER_REGISTRY = IMProviderRegistry(IMProviderDefinition)

IM_PROVIDER_REGISTRY.register("INTERNAL", INTERNAL_IM_PROVIDER)
IM_PROVIDER_REGISTRY.register("WHATSAPP", WHATSAPP_IM_PROVIDER)
IM_PROVIDER_REGISTRY.register("SLACK", SLACK_IM_PROVIDER)


def im_provider_choices() -> list[tuple[str, str]]:
    """Return current provider choices without freezing extension registrations."""
    return IM_PROVIDER_REGISTRY.choices()


from .builtins.phone import PHONE_IM_PROVIDER

IM_PROVIDER_REGISTRY.register("PHONE", PHONE_IM_PROVIDER)
