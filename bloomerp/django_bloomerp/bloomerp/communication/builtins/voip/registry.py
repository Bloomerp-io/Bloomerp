"""Carrier definitions resolved independently of IM provider configuration."""

from bloomerp.utils.registry import BaseRegistry

from .builtins.telnyx import TELNYX_PROVIDER
from .builtins.twilio import TWILIO_PROVIDER
from .definition import VoIPProviderDefinition


class VoIPProviderRegistry(BaseRegistry[VoIPProviderDefinition]):
    """Index configured carriers by their stable persisted key."""

    def register(self, key: str, obj: VoIPProviderDefinition) -> None:
        """Reject duplicate or mismatched carrier identities."""
        if key != obj.key or key != obj.adapter_class.provider_key or self.get(key):
            raise ValueError("Invalid or duplicate VoIP provider key")
        super().register(key, obj)


VOIP_PROVIDER_REGISTRY = VoIPProviderRegistry(VoIPProviderDefinition)
VOIP_PROVIDER_REGISTRY.register(TWILIO_PROVIDER.key, TWILIO_PROVIDER)

VOIP_PROVIDER_REGISTRY.register(TELNYX_PROVIDER.key, TELNYX_PROVIDER)
