import re
from typing import Any

from django.db import models
from django.contrib.contenttypes.models import ContentType
from pydantic import BaseModel
from bloomerp.models.base_bloomerp_model import BloomerpModel
from bloomerp.models.application_field import ApplicationField
from bloomerp.model_fields.text_editor_field import TextEditorField
from django.utils.translation import gettext_lazy as _
from bloomerp.models.files.file_folder import FileFolder

class PageSize(models.TextChoices):
    A4 = 'A4', _('A4')
    LETTER = 'Letter', _('Letter')
    A3 = 'A3', _('A3')

class Orientation(models.TextChoices):
    PORTRAIT = 'portrait', _('Portrait')
    LANDSCAPE = 'landscape', _('Landscape')

class FreeVariableChoice(BaseModel):
    value: str
    label: str


class FreeVariableConfig(BaseModel):
    slug: str
    label: str
    type: str
    required: bool = False
    help_text: str | None = None
    default: Any = None
    choices: list[FreeVariableChoice] = []

    @property
    def normalized_slug(self) -> str:
        return re.sub(r"[^a-zA-Z0-9_]", "_", self.slug.strip()).strip("_").lower()

    def as_json(self) -> dict[str, Any]:
        data = self.model_dump()
        data["slug"] = self.normalized_slug
        return data


class DocumentTemplate(BloomerpModel):
    class Meta(BloomerpModel.Meta):
        managed = True
        db_table = 'bloomerp_document_template'

    avatar = None

    name = models.CharField(
        max_length=100,
        help_text=_("Name of the document template.")
        ) #Name of the document template
    template = TextEditorField(
        default='Hello world',
        help_text=_("Content of the template, including the variables."),
        blank=True,
        null=False,
        ) # Content of the template, including the variables
    content_types = models.ManyToManyField(
        ContentType,
        blank=True,
        help_text=_("Root object types that can be used as variables in the document template."),
        related_name="document_templates",
    )
    free_variables = models.JSONField(
        default=list,
        blank=True,
    )
    template_header = models.ForeignKey(
        "DocumentTemplateHeader",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text=_("Header of the document template.")
        ) #Foreign key to the document template header
    footer = models.TextField(
        help_text=_("Footer content of the document template."),
        blank=True,
        null=True
        )
    styling = models.ForeignKey(
        "DocumentTemplateStyling",
        on_delete=models.SET_NULL,
        null=True, 
        blank=True,
        help_text=_("Styling of the document template.")
        ) # Foreign key to the document template styling
    page_orientation = models.CharField(
        max_length=10,
        default='portrait',
        help_text=_("Orientation of the document template."),
        choices=Orientation.choices
        ) # Orientation of the document template
    page_size = models.CharField(
        max_length=10,
        default='A4',
        help_text=_("Size of the document template."),
        choices=PageSize.choices
        ) 
    page_margin = models.FloatField(
        default=1.0,
        help_text=_("Margin of the document template in inches.")
        ) # Margin of the document template in inches
    include_page_numbers = models.BooleanField(
        default=True,
        help_text=_("Signifies whether the page numbers are included or not.")
        ) 

    save_to_folder = models.ForeignKey(
        to = FileFolder,
        null=True,
        blank=True,
        help_text=_('Signifies to which folder a file generated from the template needs to be saved upon creation.'),
        on_delete=models.SET_NULL
    )

    def __str__(self):
        return self.name


    def get_related_content_types(model):
        related_content_types = [ContentType.objects.get_for_model(model)]
        return related_content_types

    @property
    def model_variable(self):
        """
        Backwards-compatible primary content type for older generation paths.
        New builder logic should use content_types instead.
        """
        if self._state.adding:
            return getattr(self, "_unsaved_model_variable", None)
        return self.content_types.order_by("app_label", "model").first()

    @model_variable.setter
    def model_variable(self, value):
        if not self._state.adding:
            self.content_types.set([value] if value else [])
        else:
            self._unsaved_model_variable = value

    @property
    def model_variable_id(self):
        content_type = self.model_variable
        return content_type.pk if content_type else None

    def get_template_content_types(self):
        if not self._state.adding:
            return self.content_types.all().order_by("app_label", "model")
        content_types = getattr(self, "_unsaved_content_types", None)
        if content_types is not None:
            content_type_ids = [content_type.pk for content_type in content_types if content_type is not None]
            return ContentType.objects.filter(pk__in=content_type_ids).order_by("app_label", "model")
        content_type = getattr(self, "_unsaved_model_variable", None)
        if content_type is not None:
            return ContentType.objects.filter(pk=content_type.pk)
        return ContentType.objects.none()

    @property
    def application_fields(self):
        '''
        Returns a queryset of ApplicationField that are related to the content types of the document template.
        '''
        content_types = self.get_template_content_types()
        if not content_types.exists():
            return ApplicationField.objects.none()
        return ApplicationField.objects.filter(content_type__in=content_types)

    def get_free_variable_configs(self) -> list[FreeVariableConfig]:
        configs: list[FreeVariableConfig] = []
        for raw_config in self.free_variables or []:
            if not isinstance(raw_config, dict):
                continue
            try:
                config = FreeVariableConfig(**raw_config)
            except Exception:
                continue
            if not config.normalized_slug:
                continue
            configs.append(config)
        return configs

    def set_free_variable_configs(self, configs: list[FreeVariableConfig]) -> None:
        self.free_variables = [config.as_json() for config in configs]

    def get_free_variable_slugs(self) -> set[str]:
        return {config.normalized_slug for config in self.get_free_variable_configs()}
    
    

    
    

    
    
    
    
