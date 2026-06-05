from django.db import models
from django.core.exceptions import ValidationError
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from bloomerp.models.base_bloomerp_model import BloomerpModel, FieldLayout, LayoutItem, LayoutRow
from bloomerp.models.definition import BloomerpModelConfig, ObjectHTML, DetailViewSettings
from bloomerp.models.mixins.content_layout_model_mixin import ContentLayoutModelMixin
from django.utils.translation import gettext_lazy as _
from django.template.loader import render_to_string
from bloomerp.services.sectioned_layout_services import create_default_layout


class Form(BloomerpModel, ContentLayoutModelMixin, models.Model):
    
    bloomerp_config = BloomerpModelConfig(
        create_redirect_url_func=lambda x: reverse("forms_detail_form_builder", kwargs={"pk" : x.id}),
        allow_string_search=True,
        layout=FieldLayout(
            rows=[
                LayoutRow(
                    columns=2,
                    title="Core Details",
                    items=[
                        LayoutItem(id="name"),
                        LayoutItem(id="content_type"),
                        LayoutItem(id="description", colspan=2),
                    ]
                ),
                LayoutRow(
                    columns=2,
                    title="Settings",
                    items=[
                        LayoutItem(id="requires_review"),
                        LayoutItem(id="requires_authentication"),
                        LayoutItem(id="max_submissions"),
                        LayoutItem(id="max_submissions_per_ip"),
                        LayoutItem(id="opens_at"),
                        LayoutItem(id="closes_at"),   
                    ]
                )
            ]
        ),
        detail_view_settings=DetailViewSettings(
            skip_views=[
                "document_templates"
            ]
        ),
        object_actions=[
            ObjectHTML(
                template_name="models/forms/links_btn.html"
            )
        ]
    )
    
    name = models.CharField(
        max_length=255,
        default="Untitled form",
        help_text=_("The name of the form")
    )
    description = models.TextField(
        null=True,
        blank=True
    )
    content_type = models.ForeignKey(
        to=ContentType,
        on_delete=models.CASCADE
    )
    initial_payload = models.JSONField(
        default=dict,
        blank=True,
        help_text=_("Initial payload for the form")
    )
    
    # Other information
    requires_review = models.BooleanField(
        default=True,
        help_text=_("Whether the form submission needs to be reviewed before it is persisted.")
    )
    requires_authentication = models.BooleanField(
        default=False,
        help_text=_("Whether the form requires an authenticated user in order to be accessible.")
    )
    max_submissions = models.IntegerField(
        null=True,
        blank=True,
        help_text=_("Maximum number of submissions possible for the form")
    )
    max_submissions_per_ip = models.IntegerField(
        null=True,
        blank=True,
        help_text=_("Maximum number of submissions per IP address")
    )
    opens_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_("The date and time from which the form will accept submissions.")
    )
    closes_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_("The date and time after which the form will no longer accept submissions.")
    )
    

    def __str__(self):
        return f"{self.name} - {str(self.content_type)}" 
    
    def clean(self):
        errors = {}

        if self.opens_at and self.closes_at and self.opens_at >= self.closes_at:
            errors["closes_at"] = _("Closing time must be after opening time.")

        if (
            self.max_submissions_per_ip is not None
            and self.max_submissions is not None
            and self.max_submissions_per_ip > self.max_submissions
        ):
            errors["max_submissions_per_ip"] = _(
                "Maximum submissions per IP address cannot exceed the total maximum submissions."
            )

        content_type_changed = self.has_content_type_changed()
        if content_type_changed:
            self.initial_payload = {}

        if self.content_type_id and (content_type_changed or not self.layout):
            self.set_layout(
                create_default_layout(
                    self.content_type.model_class(),
                )
            )

        if errors:
            raise ValidationError(errors)
        
        
        return super().clean()

    def has_content_type_changed(self) -> bool:
        if not self.pk or not self.content_type_id:
            return False
        return (
            self.__class__.objects
            .filter(pk=self.pk)
            .exclude(content_type_id=self.content_type_id)
            .exists()
        )

    
    @property
    def submit_url(self) -> str:
        """Returns the submit URL

        Returns:
            str: _description_
        """
        return reverse(
            "forms_detail_submit",
            kwargs={
                "pk" : self.pk
            }
        )
    
    
