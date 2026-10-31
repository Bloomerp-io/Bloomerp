"""Validated, private persistence for telephony records."""

from bloomerp.models.communication.instant_messaging.base import IMModel
from bloomerp.models.definition import BloomerpModelConfig
from bloomerp.modules.communication import CommunicationModule


def voip_model_config(
    *,
    icon=None,
    description=None
):
    return BloomerpModelConfig(
        module=CommunicationModule,
        icon=icon,
        description=description
    )

class VoIPModel(IMModel):
    """Reuse validated communications persistence without exposing generated APIs."""

    class Meta(IMModel.Meta):
        abstract = True
