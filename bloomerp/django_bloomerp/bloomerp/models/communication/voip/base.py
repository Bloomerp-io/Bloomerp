"""Validated, private persistence for telephony records."""

from bloomerp.models.communication.instant_messaging.base import IMModel


class VoIPModel(IMModel):
    """Reuse validated communications persistence without exposing generated APIs."""

    class Meta(IMModel.Meta):
        abstract = True
