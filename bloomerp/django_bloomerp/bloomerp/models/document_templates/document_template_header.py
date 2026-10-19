from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils.translation import gettext_noop

from bloomerp.dataviews.table.config import TableDataView
from bloomerp.models import BloomerpModel, FieldLayout, LayoutItem, LayoutRow
from bloomerp.models.definition import (
    BloomerpModelConfig,
    DetailViewSettings,
    ModelViewSettings,
)


# ---------------------------------
# Document Template Model
# ---------------------------------
class DocumentTemplateHeader(BloomerpModel):
    avatar = None

    bloomerp_config = BloomerpModelConfig(
        model_view_settings=ModelViewSettings(
            default_dataviews=[
                TableDataView(
                    name=gettext_noop("Document template headers"),
                    display_fields=["name", "header", "height", "datetime_updated"],
                    sort_field="name",
                )
            ],
        ),
        detail_view_settings=DetailViewSettings(
            layouts=[
                FieldLayout(
                    rows=[
                        LayoutRow(
                            columns=2,
                            title=gettext_noop("Header"),
                            items=[
                                LayoutItem(id="name"),
                                LayoutItem(id="header"),
                            ],
                        ),
                        LayoutRow(
                            columns=2,
                            title=gettext_noop("Size and margins (inches)"),
                            items=[
                                LayoutItem(id="height", colspan=2),
                                LayoutItem(id="margin_top"),
                                LayoutItem(id="margin_bottom"),
                                LayoutItem(id="margin_left"),
                                LayoutItem(id="margin_right"),
                            ],
                        ),
                    ]
                )
            ],
        ),
    )

    class Meta(BloomerpModel.Meta):
        verbose_name = _("Document Template Header")
        verbose_name_plural = _("Document Template Headers")
        managed = True
        db_table = "bloomerp_document_template_header"

    name = models.CharField(
        max_length=100,
        blank=False,
        null=False,
        help_text=_("Name of the template header."),
        verbose_name=_("Name"),
    )
    header = models.ImageField(
        help_text=_("Image of the header."),
        upload_to="document_templates/headers",
        verbose_name=_("Header"),
    )
    margin_top = models.FloatField(
        default=0.5,
        help_text=_("Top margin of the header in inches."),
        verbose_name=_("Margin Top"),
    )
    margin_bottom = models.FloatField(
        default=0.0,
        help_text=_("Bottom margin of the header in inches."),
        verbose_name=_("Margin Bottom"),
    )
    margin_left = models.FloatField(
        default=1.0,
        help_text=_("Left margin of the header in inches."),
        verbose_name=_("Margin Left"),
    )
    margin_right = models.FloatField(
        default=1.0,
        help_text=_("Right margin of the header in inches."),
        verbose_name=_("Margin Right"),
    )
    height = models.FloatField(
        default=1.0,
        help_text=_("Height of the header in inches."),
        verbose_name=_("Height"),
    )

    def __str__(self):
        return self.name
