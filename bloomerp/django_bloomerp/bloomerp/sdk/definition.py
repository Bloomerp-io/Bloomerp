"""Opt-in serializer contracts for custom SDK operations."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from django.db.models import Model
from rest_framework.serializers import BaseSerializer

SerializerSource = type[BaseSerializer] | Callable[[type[Model] | None], type[BaseSerializer]]


@dataclass(frozen=True)
class SdkEndpoint:
    """Describe one JSON operation; factories receive the route's concrete model."""

    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    input_serializer: SerializerSource
    output_serializer: SerializerSource

    def __post_init__(self) -> None:
        """Reject incomplete contracts and unsupported HTTP methods early."""
        if self.method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            raise ValueError("SDK endpoints require GET, POST, PUT, PATCH, or DELETE")
        if not callable(self.input_serializer) or not callable(self.output_serializer):
            raise TypeError("SDK endpoints require both input and output serializers")

    def resolve(self, source: SerializerSource, model: type[Model] | None) -> BaseSerializer:
        """Instantiate a serializer class or resolve a deferred model-specific factory."""
        serializer_class = source if isinstance(source, type) else source(model)
        if not isinstance(serializer_class, type) or not issubclass(serializer_class, BaseSerializer):
            raise TypeError("SDK serializer factories must return a DRF serializer class")
        return serializer_class()


SdkEndpoints = SdkEndpoint | list[SdkEndpoint] | tuple[SdkEndpoint, ...]


def normalize_sdk_endpoints(sdk: SdkEndpoints | None) -> tuple[SdkEndpoint, ...]:
    """Normalize one route's contracts and reject ambiguous HTTP method declarations."""
    if sdk is None:
        return ()
    if isinstance(sdk, SdkEndpoint):
        return (sdk,)
    if not isinstance(sdk, (list, tuple)) or any(not isinstance(item, SdkEndpoint) for item in sdk):
        raise TypeError("sdk must be an SdkEndpoint or a list/tuple of SdkEndpoint contracts")
    if not sdk:
        raise ValueError("SDK endpoint lists cannot be empty; use sdk=None to opt out")
    methods: set[str] = set()
    for contract in sdk:
        if contract.method in methods:
            raise ValueError(f"Duplicate SDK method: {contract.method}")
        methods.add(contract.method)
    return tuple(sdk)
