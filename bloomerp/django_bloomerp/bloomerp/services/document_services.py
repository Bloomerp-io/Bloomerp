import re
from dataclasses import asdict, dataclass, field as dataclass_field
from enum import Enum
from typing import Any, Optional

from django import forms
from django.contrib.contenttypes.models import ContentType
from django.core.files.base import ContentFile
from django.db.models import Model, QuerySet
from django.template import engines
from django.utils import timezone
from django.utils.text import slugify

from bloomerp.field_types.types import FieldType
from bloomerp.forms.document_templates import DocumentTemplateForm
from bloomerp.models import AbstractBloomerpUser, ApplicationField, DocumentTemplate
from bloomerp.models.document_templates.document_template import FreeVariableConfig
from bloomerp.models.files.file import File
from bloomerp.services.permission_services import UserPermissionManager
from bloomerp.utils.pdf import generate_pdf
from bloomerp.widgets.foreign_field_widget import ForeignFieldWidget


@dataclass(frozen=True)
class FreeVariableTypeDefinition:
    id: str
    display_name: str
    icon: str
    form_field_cls: type[forms.Field]
    form_field_kwargs: dict[str, Any] = dataclass_field(default_factory=dict)
    supports_choices: bool = False
    injection_methods: list[str] = dataclass_field(default_factory=lambda: ["value"])

    def build_form_field(self, config: FreeVariableConfig) -> forms.Field:
        kwargs = {
            "label": config.label,
            "required": config.required,
            "help_text": config.help_text or "",
            **self.form_field_kwargs,
        }
        if config.default not in (None, ""):
            kwargs["initial"] = config.default
        if self.supports_choices:
            kwargs["choices"] = [(choice.value, choice.label) for choice in config.choices]
        return self.form_field_cls(**kwargs)


class FreeVariableType(Enum):
    TEXT = FreeVariableTypeDefinition(
        id="text",
        display_name="Text",
        icon="fa-solid fa-font",
        form_field_cls=forms.CharField,
    )
    DATE = FreeVariableTypeDefinition(
        id="date",
        display_name="Date",
        icon="fa-solid fa-calendar-days",
        form_field_cls=forms.DateField,
        form_field_kwargs={"widget": forms.DateInput(attrs={"type": "date"})},
        injection_methods=["value", "formatted_date"],
    )
    BOOLEAN = FreeVariableTypeDefinition(
        id="boolean",
        display_name="Boolean",
        icon="fa-solid fa-toggle-on",
        form_field_cls=forms.BooleanField,
        form_field_kwargs={"required": False},
        injection_methods=["value", "yes_no"],
    )
    INTEGER = FreeVariableTypeDefinition(
        id="integer",
        display_name="Integer",
        icon="fa-solid fa-hashtag",
        form_field_cls=forms.IntegerField,
    )
    FLOAT = FreeVariableTypeDefinition(
        id="float",
        display_name="Decimal number",
        icon="fa-solid fa-calculator",
        form_field_cls=forms.FloatField,
    )
    CHOICE = FreeVariableTypeDefinition(
        id="choice",
        display_name="Choice",
        icon="fa-solid fa-list",
        form_field_cls=forms.ChoiceField,
        supports_choices=True,
    )

    @property
    def id(self) -> str:
        return self.value.id

    @property
    def display_name(self) -> str:
        return self.value.display_name

    @property
    def icon(self) -> str:
        return self.value.icon

    @classmethod
    def from_id(cls, type_id: str) -> "FreeVariableType":
        normalized = (type_id or "").strip().lower()
        aliases = {
            "char": "text",
            "string": "text",
            "list": "choice",
        }
        normalized = aliases.get(normalized, normalized)
        for member in cls:
            if member.id == normalized:
                return member
        raise ValueError(f"Unknown free variable type: {type_id}")

    @classmethod
    def choices_payload(cls) -> list[dict[str, Any]]:
        return [
            {
                "id": member.id,
                "label": member.display_name,
                "icon": member.icon,
                "supportsChoices": member.value.supports_choices,
                "injectionMethods": member.value.injection_methods,
            }
            for member in cls
        ]


@dataclass(frozen=True)
class TemplateInjectionMethod:
    id: str
    label: str
    icon: str
    description: str
    requires_field_selection: bool = False

    def as_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["requiresFieldSelection"] = payload.pop("requires_field_selection")
        return payload


VALUE = TemplateInjectionMethod(
    id="value",
    label="Value",
    icon="fa-solid fa-code",
    description="Insert the value.",
)
FORMATTED_DATE = TemplateInjectionMethod(
    id="formatted_date",
    label="Formatted date",
    icon="fa-solid fa-calendar-day",
    description="Insert the value with a date format.",
)
YES_NO = TemplateInjectionMethod(
    id="yes_no",
    label="Yes / no",
    icon="fa-solid fa-circle-check",
    description="Render a boolean value as yes or no.",
)
NESTED_FIELD = TemplateInjectionMethod(
    id="nested_field",
    label="Nested field",
    icon="fa-solid fa-arrow-right",
    description="Insert a field from the related object.",
    requires_field_selection=True,
)
LOOP = TemplateInjectionMethod(
    id="loop",
    label="Loop",
    icon="fa-solid fa-repeat",
    description="Render every related object in a loop.",
)
TABLE = TemplateInjectionMethod(
    id="table",
    label="Table",
    icon="fa-solid fa-table",
    description="Render related objects as a table.",
    requires_field_selection=True,
)
COUNT = TemplateInjectionMethod(
    id="count",
    label="Count",
    icon="fa-solid fa-hashtag",
    description="Insert the number of related objects.",
)
LIST = TemplateInjectionMethod(
    id="list",
    label="List",
    icon="fa-solid fa-list-ul",
    description="Render related objects as a list.",
)

INJECTION_METHODS = {
    method.id: method
    for method in [VALUE, FORMATTED_DATE, YES_NO, NESTED_FIELD, LOOP, TABLE, COUNT, LIST]
}

FIELD_TYPE_TEMPLATE_INJECTIONS = {
    FieldType.PROPERTY.id: [VALUE],
    FieldType.CHAR_FIELD.id: [VALUE],
    FieldType.CHOICE_FIELD.id: [VALUE],
    FieldType.TEXT_FIELD.id: [VALUE],
    FieldType.EMAIL_FIELD.id: [VALUE],
    FieldType.URL_FIELD.id: [VALUE],
    FieldType.PHONE_NUMBER_FIELD.id: [VALUE],
    FieldType.SLUG_FIELD.id: [VALUE],
    FieldType.INTEGER_FIELD.id: [VALUE],
    FieldType.FLOAT_FIELD.id: [VALUE],
    FieldType.DECIMAL_FIELD.id: [VALUE],
    FieldType.POSITIVE_INTEGER_FIELD.id: [VALUE],
    FieldType.POSITIVE_SMALL_INTEGER_FIELD.id: [VALUE],
    FieldType.BIG_INTEGER_FIELD.id: [VALUE],
    FieldType.SMALL_INTEGER_FIELD.id: [VALUE],
    FieldType.BOOLEAN_FIELD.id: [VALUE, YES_NO],
    FieldType.NULL_BOOLEAN_FIELD.id: [VALUE, YES_NO],
    FieldType.DATE_FIELD.id: [VALUE, FORMATTED_DATE],
    FieldType.DATE_TIME_FIELD.id: [VALUE, FORMATTED_DATE],
    FieldType.TIME_FIELD.id: [VALUE],
    FieldType.DURATION_FIELD.id: [VALUE],
    FieldType.FILE_FIELD.id: [VALUE],
    FieldType.IMAGE_FIELD.id: [VALUE],
    FieldType.FOREIGN_KEY.id: [VALUE, NESTED_FIELD],
    FieldType.ONE_TO_ONE_FIELD.id: [VALUE, NESTED_FIELD],
    FieldType.MANY_TO_MANY_FIELD.id: [LIST, TABLE, COUNT],
    FieldType.ONE_TO_MANY_FIELD.id: [LOOP, TABLE, COUNT],
    FieldType.USER_FIELD.id: [VALUE, NESTED_FIELD],
    FieldType.UUID_FIELD.id: [VALUE],
    FieldType.STATUS_FIELD.id: [VALUE],
    FieldType.ICON_FIELD.id: [VALUE],
    FieldType.BLOOMERP_FILE_FIELD.id: [VALUE],
}



@dataclass
class DocumentTemplateValidationMessage:
    code: str
    message: str
    variable: str | None = None

    def as_payload(self) -> dict[str, str | None]:
        return asdict(self)


@dataclass
class DocumentTemplateValidationResult:
    errors: list[DocumentTemplateValidationMessage] = dataclass_field(default_factory=list)
    warnings: list[DocumentTemplateValidationMessage] = dataclass_field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not self.errors

    def as_payload(self) -> dict[str, Any]:
        return {
            "isValid": self.is_valid,
            "errors": [message.as_payload() for message in self.errors],
            "warnings": [message.as_payload() for message in self.warnings],
        }


class DocumentTemplateService:
    def __init__(self, document_template: DocumentTemplate, user: AbstractBloomerpUser | None = None):
        self.document_template = document_template
        self.user = user

    def generate(self, form: DocumentTemplateForm):
        if not form.is_valid():
            raise ValueError("Cannot generate a document from an invalid form.")

        root_objects = self.get_cleaned_model_variable_values(form)
        formatted_html = self.format_html({
            "object": getattr(form, "instance", None),
            "objects": getattr(form, "objects", None),
            **root_objects,
            "vars": self.get_cleaned_free_variable_values(form),
        })
        bytes =  generate_pdf(
            formatted_html,
            page_margin=self.document_template.page_margin,
            header_url=self.document_template.template_header.header.url if self.document_template.template_header else None,
            
        )
        return bytes

    def get_model_content_types(self) -> QuerySet[ContentType]:
        return self.document_template.get_template_content_types()

    def get_model_variables(self) -> QuerySet[ApplicationField]:
        content_types = self.get_model_content_types()
        if not content_types.exists():
            return ApplicationField.objects.none()
        if self.user:
            manager = UserPermissionManager(self.user)
            field_ids: list[int] = []
            for content_type in content_types:
                permission = f"view_{content_type.model}"
                field_ids.extend(manager.get_accessible_fields(content_type, permission).values_list("id", flat=True))
            return ApplicationField.objects.filter(id__in=field_ids).select_related("content_type").order_by("content_type__app_label", "content_type__model", "field")
        return self.document_template.application_fields

    def get_free_variables(self) -> list[FreeVariableConfig]:
        """Returns the free variables for a document template

        Returns:
            list[FreeVariableConfig]: _description_
        """
        return self.document_template.get_free_variable_configs()

    def get_form(self, instance:Optional[Model]=None) -> type[DocumentTemplateForm]:
        """Returns the form required to generate a document template. If an instance is passed, it will remove
        this content type from the inputs.

        For example: if content types are "Employee" and "EmployeeSalary", and an instance is given of "Employee",
        the form will only contain have an input of "EmployeeSalary" and will consider the employee instance as being set.

        Args:
            instance (Optional[Model], optional): An optional instance passed to the form. Defaults to None.

        Returns:
            type[DocumentTemplateForm]: form
        """
        form_attrs: dict[str, Any] = {}
        preset_content_type = ContentType.objects.get_for_model(instance) if instance is not None else None
        preset_variable_name = (
            self.get_content_type_variable_name(preset_content_type)
            if preset_content_type is not None
            else None
        )

        variable_field_names: list[str] = []
        variable_name_by_field_name: dict[str, str] = {}
        for content_type in self.get_model_content_types():
            model_class = content_type.model_class()
            if model_class is None:
                continue
            if preset_content_type is not None and content_type.pk == preset_content_type.pk:
                continue

            variable_field_names.append(content_type.model)
            variable_name_by_field_name[content_type.model] = self.get_content_type_variable_name(content_type)
            form_attrs[content_type.model] = forms.ModelChoiceField(
                queryset=model_class.objects.all(),
                widget=ForeignFieldWidget(model_class, attrs={"class" : "input w-full"}),
                label=f"Generate document for {model_class._meta.verbose_name}",
            )

        for config in self.get_free_variables():
            try:
                variable_type = FreeVariableType.from_id(config.type)
            except ValueError:
                variable_type = FreeVariableType.TEXT
            form_attrs[config.normalized_slug] = variable_type.value.build_form_field(config)

        form_attrs["variable_field_names"] = tuple(variable_field_names)
        form_attrs["variable_name_by_field_name"] = variable_name_by_field_name
        form_attrs["preset_instance"] = instance
        form_attrs["preset_variable_name"] = preset_variable_name
        
        generated_form_class = type("DocumentTemplateGeneratedForm", (DocumentTemplateForm,), form_attrs)
        return generated_form_class

    def get_files(self, instance: Optional[Model] = None) -> QuerySet[File]:
        """Returns a queryset of all the saved files from this document template.

        Returns:
            QuerySet[File]: _description_
        """
        qs = File.objects.filter(
            meta__document_template_id=str(self.document_template.id),
        )
        if instance:
            qs = qs.filter(
                object_id=str(instance.pk),
                content_type=ContentType.objects.get_for_model(instance),
            )
            
        return qs
    
    def create_file(
        self, 
        file_bytes:bytes,
        instance:Optional[Model] = None,
        filename:Optional[str] = None 
        ) -> File:
        """Creates a file from the given bytes and associates it with the given instance and this document template.

        Args:
            file_bytes (bytes): The file bytes to save
            instance (Optional[Model], optional): An optional instance to link it to. Defaults to None.
            filename (Optional[str], optional): An optional filename, will generate a default filename if not given. Defaults to None.

        Returns:
            File: The file object
        """
        filename = filename or self.generate_default_filename(instance)
        if not filename.lower().endswith(".pdf"):
            filename = f"{filename}.pdf"

        content_type = ContentType.objects.get_for_model(instance) if instance is not None else None
        meta = {
            "document_template_id": str(self.document_template.id),
            "document_template_name": self.document_template.name,
        }

        file_object = File(
            name=filename,
            content_type=content_type,
            object_id=str(instance.pk) if instance is not None else None,
            folder=self.document_template.save_to_folder,
            persisted=True,
            meta=meta,
            created_by=self.user,
            updated_by=self.user,
        )
        file_object.file.save(filename, ContentFile(file_bytes), save=True)
        return file_object
    
    def generate_default_filename(self, instance: Optional[Model] = None) -> str:
        """Generates a default filename

        Args:
            instance (Optional[Model], optional): The instance. Defaults to None.

        Returns:
            str: default filename
        """
        name_parts = [self.document_template.name or "Generated document"]
        if instance is not None:
            name_parts.append(str(instance))
        timestamp = timezone.now().strftime("%Y%m%d-%H%M%S")
        filename_base = slugify(" ".join(name_parts)) or "generated-document"
        return f"{filename_base}-{timestamp}.pdf"
    
    def get_cleaned_free_variable_values(self, form: forms.Form) -> dict[str, Any]:
        free_variable_slugs = self.document_template.get_free_variable_slugs()
        return {
            slug: value
            for slug, value in form.cleaned_data.items()
            if slug in free_variable_slugs
        }

    def get_cleaned_model_variable_values(self, form: forms.Form) -> dict[str, Any]:
        if hasattr(form, "model_variable_values"):
            return dict(getattr(form, "model_variable_values") or {})
        return {
            self.get_content_type_variable_name(content_type): form.cleaned_data[content_type.model]
            for content_type in self.get_model_content_types()
            if content_type.model in form.cleaned_data
        }

    def validate(self) -> DocumentTemplateValidationResult:
        result = DocumentTemplateValidationResult()
        template = self.document_template.template or ""
        configured_slugs = self.document_template.get_free_variable_slugs()
        used_slugs = set(re.findall(r"\bvars\.([a-zA-Z_][a-zA-Z0-9_]*)", template))

        for slug in sorted(used_slugs - configured_slugs):
            result.errors.append(DocumentTemplateValidationMessage(
                code="unknown_free_variable",
                message=f"Template references vars.{slug}, but no free variable with that slug is configured.",
                variable=slug,
            ))

        for slug in sorted(configured_slugs - used_slugs):
            result.warnings.append(DocumentTemplateValidationMessage(
                code="unused_free_variable",
                message=f"Free variable {slug} is configured but not used in the template.",
                variable=slug,
            ))

        for config in self.get_free_variables():
            try:
                variable_type = FreeVariableType.from_id(config.type)
            except ValueError:
                result.errors.append(DocumentTemplateValidationMessage(
                    code="unknown_free_variable_type",
                    message=f"Free variable {config.normalized_slug} uses unknown type {config.type}.",
                    variable=config.normalized_slug,
                ))
                continue

            if variable_type.value.supports_choices and not config.choices:
                result.errors.append(DocumentTemplateValidationMessage(
                    code="missing_choices",
                    message=f"Free variable {config.normalized_slug} requires choices.",
                    variable=config.normalized_slug,
                ))

        return result

    def format_html(self, data: dict[str, Any]) -> str:
        django_engine = engines["django"]
        temp = django_engine.from_string("{% load document_template_tags %}" + self.document_template.template)
        return temp.render(data)

    def get_content_type_variable_name(self, content_type: ContentType) -> str:
        model_class = content_type.model_class()
        model_name = model_class.__name__ if model_class else content_type.model
        return re.sub(r"(?<!^)(?=[A-Z])", "_", model_name).lower()
