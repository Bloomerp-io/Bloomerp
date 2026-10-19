from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.query import QuerySet
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.utils.translation import gettext_noop

from bloomerp.dataviews.table.config import TableDataView
from bloomerp.models import BloomerpModel
from bloomerp.models.application_field import ApplicationField
from bloomerp.models.definition import (
    BloomerpModelConfig,
    DetailViewSettings,
    FieldLayout,
    LayoutItem,
    LayoutRow,
    ModelViewSettings,
    ObjectHTMLAction,
)
from bloomerp.models.mixins.content_layout_model_mixin import ContentLayoutModelMixin
from bloomerp.services.sectioned_layout_services import create_default_layout


class Form(BloomerpModel, ContentLayoutModelMixin, models.Model):
    
    class Meta:
        verbose_name = _("Form")
        verbose_name_plural = _("Forms")

    bloomerp_config = BloomerpModelConfig(
        model_view_settings=ModelViewSettings(
            default_dataviews=[
                TableDataView(
                    name=gettext_noop("Forms"),
                    display_fields=[
                        "name",
                        "content_type",
                        "requires_review",
                        "requires_authentication",
                        "opens_at",
                        "closes_at",
                    ],
                    sort_field="name",
                )
            ]
        ),
        create_redirect_url_func=lambda x: reverse("forms_detail_form_builder", kwargs={"pk" : x.id}),
        detail_view_settings=DetailViewSettings(
            layouts=[FieldLayout(
                rows=[
                    LayoutRow(
                        columns=2,
                        title=gettext_noop("Core Details"),
                        items=[
                            LayoutItem(id="name"),
                            LayoutItem(id="content_type"),
                            LayoutItem(id="description", colspan=2),
                            LayoutItem(id="success_text", colspan=2),
                        ]
                    ),
                    LayoutRow(
                        columns=2,
                        title=gettext_noop("Settings"),
                        items=[
                            LayoutItem(id="requires_review", colspan=2),
                            LayoutItem(id="requires_authentication"),
                            LayoutItem(id="public_embed_enabled"),
                            LayoutItem(id="max_submissions"),
                            LayoutItem(id="max_submissions_per_ip"),
                            LayoutItem(id="opens_at"),
                            LayoutItem(id="closes_at"),
                        ]
                    )
                ]
            )],
            skip_views=[
                "document_templates"
            ]
        ),
        object_actions=[
            ObjectHTMLAction(
                template_name="models/forms/links_btn.html"
            ),
            ObjectHTMLAction(
                template_name="models/forms/public_embed_btn.html",
                should_render_func=lambda request, obj: obj.public_embed_enabled,
            ),
        ]
    )
    
    name = models.CharField(
        max_length=255,
        default="Untitled form",
        help_text=_("The name of the form"),
        verbose_name=_("Name"),
    )
    description = models.TextField(
        null=True,
        blank=True,
        verbose_name=_("Description"),
    )
    success_text = models.TextField(
        null=True,
        blank=True,
        verbose_name=_("Success Text"),
        help_text=_("Text shown after a successful form submission."),
    )
    content_type = models.ForeignKey(
        to=ContentType,
        on_delete=models.CASCADE,
        verbose_name=_("Content Type"),
    )
    initial_payload = models.JSONField(
        default=dict,
        blank=True,
        help_text=_("Initial payload for the form"),
        verbose_name=_("Initial Payload"),
    )
    
    # Other information
    requires_review = models.BooleanField(
        default=True,
        help_text=_("Whether the form submission needs to be reviewed before it is persisted."),
        verbose_name=_("Requires Review"),
    )
    requires_authentication = models.BooleanField(
        default=False,
        help_text=_("Whether the form requires an authenticated user in order to be accessible."),
        verbose_name=_("Requires Authentication"),
    )
    public_embed_enabled = models.BooleanField(
        default=False,
        help_text=_("Whether the form can be embedded in a public page."),
        verbose_name=_("Public Embed Enabled"),
    )
    max_submissions = models.IntegerField(
        null=True,
        blank=True,
        help_text=_("Maximum number of submissions possible for the form"),
        verbose_name=_("Max Submissions"),
    )
    max_submissions_per_ip = models.IntegerField(
        null=True,
        blank=True,
        help_text=_("Maximum number of submissions per IP address"),
        verbose_name=_("Max Submissions Per IP"),
    )
    opens_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_("The date and time from which the form will accept submissions."),
        verbose_name=_("Opens At"),
    )
    closes_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_("The date and time after which the form will no longer accept submissions."),
        verbose_name=_("Closes At"),
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
    def submit_api_url(self) -> str:
        """Returns the form submit API URL

        Returns:
            str: The API URL to submit the form
        """
        return reverse(
            "api_form_submit",
            kwargs={
                "pk": self.pk
            }
        )
    
    @property
    def submit_url(self) -> str:
        """Returns the submit URL

        Returns:
            str: The URL to submit the form
        """
        return reverse(
            "forms_detail_submit",
            kwargs={
                "pk" : self.pk
            }
        )
    
    def get_fields(self) -> QuerySet[ApplicationField]:
        """Returns the fields associated with the form's content type

        Returns:
            list[str]: The fields associated with the form's content type
        """
        field_ids = []
        for row in self.layout_obj.rows:
            for item in row.items:
                field_ids.append(item.id)
                
        return ApplicationField.objects.filter(
            content_type=self.content_type,
            id__in=field_ids
        )
    
    def get_field_names(self) -> list[str]:
        """Returns the field names associated with the form's content type

        Returns:
            list[str]: The field names associated with the form's content type
        """
        return [field.field for field in self.get_fields()]
