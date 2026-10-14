from django.db import models
from django.utils.translation import gettext as _
from bloomerp.models import BloomerpModel
from bloomerp.models.definition import BloomerpModelConfig
from bloomerp.models.users.base_preference import BasePreference
from bloomerp.modules.communication import CommunicationModule

CALENDAR_CONFIG = BloomerpModelConfig(
    module=CommunicationModule,
    icon="fa fa-calendar"
)

class Calendar(BasePreference):
    class Meta:
        db_table = "bloomerp_calendar"

    bloomerp_config = CALENDAR_CONFIG

    name = models.CharField(max_length=255)
