from django.db import models
from django.http import HttpRequest, HttpResponse
from django.utils.translation import gettext_lazy as _
from django.utils.translation import gettext_noop

from bloomerp.dataviews.table.config import TableDataView
from bloomerp.models import BloomerpModel
from bloomerp.models.definition import (
    BloomerpModelConfig,
    DetailViewSettings,
    FieldLayout,
    LayoutItem,
    LayoutRow,
    ModelViewSettings,
    ObjectAction,
)
from bloomerp.utils.requests import render_message


def execute_persist(request:HttpRequest, obj:"FormSubmission") -> HttpResponse:
    from bloomerp.services.form_services import FormManager
    if obj.persisted:
        return render_message(
            request,
            "Object already persisted",
            "warning"
        )
    
    
    manager = FormManager(obj.form)
    manager.persist_form_submission(obj, request)
    return render_message(
        request,
        "Form persisted succesfully",
        "success"
    )
    


class FormSubmission(BloomerpModel):
    class Meta:
        verbose_name = _("Form Submission")
        verbose_name_plural = _("Form Submissions")

    bloomerp_config = BloomerpModelConfig(
        model_view_settings=ModelViewSettings(
            default_dataviews=[
                TableDataView(
                    name=gettext_noop("Form submissions"),
                    display_fields=["form", "persisted", "datetime_created"],
                    sort_field="datetime_created",
                    sort_direction="desc",
                )
            ]
        ),
        detail_view_settings=DetailViewSettings(
            layouts=[FieldLayout(
                rows=[
                    LayoutRow(
                        title=gettext_noop("Details"),
                        columns=2,
                        items=[
                            LayoutItem(id="form"),
                            LayoutItem(id="persisted"),
                            LayoutItem(id="data", colspan=2)
                        ]
                    )
                ]
            )],
        ),
        object_actions=[
            ObjectAction(
                id="persist",
                label=gettext_noop("Persist"),
                execution_func=execute_persist,
                should_render_func=lambda req, obj: obj.persisted == False
            )
        ]
    )
    
    avatar = None
    
    form = models.ForeignKey(
        to="bloomerp.Form",
        on_delete=models.SET_NULL, # We probs don't wanna lose all of our submissions if the form is deleted.
        blank=False,
        null=True,
        related_name="submissions",
        verbose_name=_("Form"),
    )
    data: dict = models.JSONField(verbose_name=_("Data"))
    persisted = models.BooleanField(
        default=False,
        help_text=_("Whether the form was persisted"),
        editable=False,
        verbose_name=_("Persisted"),
    )
    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
        verbose_name=_("IP Address"),
    )
    
    def __str__(self):
        return f"{self.form} - {self.datetime_created}"
    
