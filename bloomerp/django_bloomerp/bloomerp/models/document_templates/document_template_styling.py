from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils.translation import gettext_noop

from bloomerp.dataviews.table.config import TableDataView
from bloomerp.model_fields.code_field import CodeField
from bloomerp.models import BloomerpModel
from bloomerp.models.definition import (
    BloomerpModelConfig,
    DetailViewSettings,
    FieldLayout,
    LayoutItem,
    LayoutRow,
    ModelViewSettings,
)


# ---------------------------------
# Document Template Styling Model
# ---------------------------------
class DocumentTemplateStyling(BloomerpModel):

    bloomerp_config = BloomerpModelConfig(
        model_view_settings=ModelViewSettings(
            default_dataviews=[
                TableDataView(
                    name=gettext_noop("Document template styles"),
                    display_fields=["name", "datetime_updated"],
                    sort_field="name",
                )
            ]
        ),
        detail_view_settings=DetailViewSettings(
            layouts=[
                FieldLayout(
                    rows=[
                        LayoutRow(
                            columns=1,
                            title=gettext_noop("Style"),
                            items=[LayoutItem(id="name"), LayoutItem(id="styling")],
                        )
                    ]
                )
            ]
        ),
    )
    avatar = None

    class Meta(BloomerpModel.Meta):
        verbose_name = _("Document Template Styling")
        verbose_name_plural = _("Document Template Stylings")
        managed = True
        db_table = "bloomerp_document_template_styling"

    name = models.CharField(
        max_length=100,
        blank=False,
        null=False,
        help_text=_("Name of the document template styling."),
        verbose_name=_("Name"),
    )
    styling = CodeField(
        language="css", default="", verbose_name=_("Styling")
    )  # Content of the styling

    def __str__(self):
        return self.name
