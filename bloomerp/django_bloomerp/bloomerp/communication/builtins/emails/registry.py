"""Registry for BloomERP email providers."""

from bloomerp.communication.builtins.emails.email_providers import (
    EmailProvider,
    EmailProviderDefinition,
)
from bloomerp.utils.registry import BaseRegistry


class EmailProviderRegistry(BaseRegistry[EmailProviderDefinition]):
    def register(self, key: str, obj: EmailProviderDefinition) -> None:
        if any(provider.key == obj.key for provider in self.values()):
            raise ValueError(f"Email provider key {obj.key!r} is already registered")
        super().register(key, obj)

    def get(self, key: str) -> EmailProviderDefinition | None:
        registered = super().get(key)
        if registered is not None:
            return registered
        return next(
            (provider for provider in self.values() if provider.key == key),
            None,
        )

    def choices(self) -> list[tuple[str, str]]:
        return [(provider.key, provider.name) for provider in self.values()]


EMAIL_PROVIDER_REGISTRY = EmailProviderRegistry(EmailProviderDefinition)

for provider in EmailProvider:
    EMAIL_PROVIDER_REGISTRY.register(provider.name, provider.value)


def email_provider_choices() -> list[tuple[str, str]]:
    """Return provider choices lazily so extension registrations are included."""
    return EMAIL_PROVIDER_REGISTRY.choices()
