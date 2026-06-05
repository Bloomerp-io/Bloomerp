from django.db import models
from django.http import HttpRequest, HttpResponse

from bloomerp.models.base_bloomerp_model import BloomerpModel, FieldLayout, LayoutItem, LayoutRow
from bloomerp.models.definition import BloomerpModelConfig, ObjectAction
from django.utils.translation import gettext_lazy as _
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
    try:
        manager.persist_form_submission(obj, request)
        print("Persisting successfulllay")
        return render_message(
            request,
            "Form persisted succesfully",
            "success"
        )
    except Exception as e:
        return render_message(
            request,
            "An error occurred.",
            "error"
        )


class FormSubmission(BloomerpModel):
    bloomerp_config = BloomerpModelConfig(
        layout=FieldLayout(
            rows=[
                LayoutRow(
                    title="Details",
                    columns=2,
                    items=[
                        LayoutItem(id="form"),
                        LayoutItem(id="persisted"),
                        LayoutItem(id="data", colspan=2)
                    ]
                )
            ]
        ),
        object_actions=[
            ObjectAction(
                id="persist",
                label="Persist",
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
        null=True
    )
    data : dict = models.JSONField(
        
    )
    persisted = models.BooleanField(
        default=False,
        help_text=_("Whether the form was persisted"),
        editable=False
    )
    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
    )
    
    def __str__(self):
        return f"{self.form} - {self.datetime_created}"
    
