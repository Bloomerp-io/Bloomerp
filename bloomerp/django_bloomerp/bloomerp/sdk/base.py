from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from pathlib import Path

from django.apps import apps
from django.db import models

from bloomerp.models.application_field import ApplicationField
from bloomerp.models.definition import BloomerpModelConfig
from bloomerp.utils.models import model_name_plural_underline


@dataclass(frozen=True)
class SdkFieldDefinition:
    name: str
    field_type: str
    db_field_type: str | None
    nullable: bool
    many: bool
    related_model_name: str | None
    title: str
    editable: bool
    required_on_create: bool
    ts_type: str
    js_doc_type: str
    python_type: str


@dataclass(frozen=True)
class SdkModelDefinition:
    class_name: str
    variable_name: str
    endpoint_name: str
    pk_type: str
    python_pk_type: str
    fields: list[SdkFieldDefinition]


class BaseSdkGenerator(ABC):
    language: str = "base"
    default_filename: str = "index.txt"

    def __init__(
        self,
        path: str,
        package_name: str | None = None,
        force: bool = False,
        filename: str | None = None,
        add_readme: bool = False,
    ):
        self.output_path = Path(path)
        self.package_name = package_name or self.output_path.name or "bloomerp-sdk"
        self.force = force
        self.filename = filename or self.default_filename
        self.add_readme = add_readme

    def generate(self) -> list[Path]:
        model_definitions = self.get_model_definitions()
        files = [self.write_text(self.filename, self.render_source(model_definitions))]
        if self.add_readme:
            files.append(self.write_text("README.md", self.render_readme(model_definitions)))
        return files

    @abstractmethod
    def render_source(self, model_definitions: list[SdkModelDefinition]) -> str:
        pass

    @abstractmethod
    def render_readme(self, model_definitions: list[SdkModelDefinition]) -> str:
        pass

    def ensure_output_path(self) -> None:
        self.output_path.mkdir(parents=True, exist_ok=True)

    def write_text(self, relative_path: str, content: str) -> Path:
        self.ensure_output_path()
        target = self.output_path / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and not self.force:
            raise FileExistsError(
                f"{target} already exists. Re-run with force enabled to overwrite generated files."
            )
        target.write_text(content, encoding="utf-8")
        return target

    def get_model_definitions(self) -> list[SdkModelDefinition]:
        return [self.build_model_definition(model) for model in self.get_api_models()]

    def get_api_models(self) -> list[type[models.Model]]:
        api_models: list[type[models.Model]] = []
        for model in apps.get_models():
            if model._meta.abstract or model._meta.proxy:
                continue

            config = getattr(model, "bloomerp_config", None)
            if isinstance(config, BloomerpModelConfig) and not config.should_enable_api_auto_generation():
                continue

            api_models.append(model)

        api_models.sort(key=lambda model: model.__name__)
        return api_models

    def build_model_definition(self, model: type[models.Model]) -> SdkModelDefinition:
        return SdkModelDefinition(
            class_name=model.__name__,
            variable_name=self.to_camel_case(model_name_plural_underline(model)),
            endpoint_name=model_name_plural_underline(model),
            pk_type=self.get_ts_type_for_field(model._meta.pk),
            python_pk_type=self.get_python_type_for_field(model._meta.pk),
            fields=self.get_field_definitions(model),
        )

    def get_field_definitions(self, model: type[models.Model]) -> list[SdkFieldDefinition]:
        application_fields = {field.field: field for field in ApplicationField.get_for_model(model)}
        serializable_fields = list(model._meta.fields) + list(model._meta.many_to_many)
        field_definitions: list[SdkFieldDefinition] = []

        for model_field in serializable_fields:
            application_field = application_fields.get(model_field.name)
            field_definitions.append(
                SdkFieldDefinition(
                    name=model_field.name,
                    field_type=application_field.field_type if application_field else model_field.get_internal_type(),
                    db_field_type=application_field.db_field_type if application_field else None,
                    nullable=getattr(model_field, "null", False),
                    many=bool(getattr(model_field, "many_to_many", False)),
                    related_model_name=self.get_related_model_name(model_field),
                    title=application_field.title if application_field else model_field.name.replace("_", " ").title(),
                    editable=getattr(model_field, "editable", True),
                    required_on_create=self.is_required_on_create(model_field),
                    ts_type=self.get_ts_type_for_field(model_field),
                    js_doc_type=self.get_js_doc_type_for_field(model_field),
                    python_type=self.get_python_type_for_field(model_field),
                )
            )

        field_definitions.sort(key=lambda field: field.name)
        return field_definitions

    def is_required_on_create(self, field: models.Field) -> bool:
        if getattr(field, "primary_key", False):
            return False
        if not getattr(field, "editable", True):
            return False
        if getattr(field, "auto_created", False):
            return False
        if getattr(field, "auto_now", False) or getattr(field, "auto_now_add", False):
            return False
        if field.has_default():
            return False
        if getattr(field, "blank", False):
            return False
        if getattr(field, "null", False):
            return False
        return True

    def get_related_model_name(self, field: models.Field) -> str | None:
        related_model = getattr(field, "related_model", None)
        if related_model is None:
            return None
        return related_model.__name__

    def get_ts_type_for_field(self, field: models.Field) -> str:
        if isinstance(field, (models.ForeignKey, models.OneToOneField)):
            related_pk_type = self.get_ts_type_for_field(field.related_model._meta.pk)
            return f"{related_pk_type} | null" if getattr(field, "null", False) else related_pk_type
        if isinstance(field, models.ManyToManyField):
            return f"Array<{self.get_ts_type_for_field(field.related_model._meta.pk)}>"
        if isinstance(field, (models.AutoField, models.BigAutoField, models.SmallAutoField)):
            return "number"
        if isinstance(field, models.UUIDField):
            return "string"
        if isinstance(field, (models.IntegerField, models.BigIntegerField, models.SmallIntegerField, models.PositiveIntegerField, models.PositiveSmallIntegerField, models.DecimalField, models.FloatField)):
            return "number"
        if isinstance(field, models.BooleanField):
            return "boolean"
        if isinstance(field, (models.DateField, models.DateTimeField, models.TimeField, models.DurationField)):
            return "string"
        if isinstance(field, (models.CharField, models.TextField, models.EmailField, models.SlugField, models.URLField, models.FileField, models.ImageField)):
            return "string | null" if getattr(field, "null", False) else "string"
        if isinstance(field, models.JSONField):
            return "unknown"
        return "unknown"

    def get_js_doc_type_for_field(self, field: models.Field) -> str:
        ts_type = self.get_ts_type_for_field(field)
        return (
            ts_type.replace("Array<", "Array.<")
            .replace(" | ", "|")
            .replace("unknown", "*")
        )

    def get_python_type_for_field(self, field: models.Field) -> str:
        if isinstance(field, (models.ForeignKey, models.OneToOneField)):
            related_pk_type = self.get_python_type_for_field(field.related_model._meta.pk)
            return f"{related_pk_type} | None" if getattr(field, "null", False) else related_pk_type
        if isinstance(field, models.ManyToManyField):
            return f"list[{self.get_python_type_for_field(field.related_model._meta.pk)}]"
        if isinstance(field, (models.AutoField, models.BigAutoField, models.SmallAutoField, models.IntegerField, models.BigIntegerField, models.SmallIntegerField, models.PositiveIntegerField, models.PositiveSmallIntegerField)):
            return "int"
        if isinstance(field, (models.DecimalField, models.FloatField)):
            return "float"
        if isinstance(field, models.BooleanField):
            return "bool"
        if isinstance(field, models.UUIDField):
            return "str"
        if isinstance(field, (models.DateField, models.DateTimeField, models.TimeField, models.DurationField)):
            return "str"
        if isinstance(field, (models.CharField, models.TextField, models.EmailField, models.SlugField, models.URLField, models.FileField, models.ImageField)):
            return "str | None" if getattr(field, "null", False) else "str"
        if isinstance(field, models.JSONField):
            return "Any"
        return "Any"

    def get_example_model(self, model_definitions: list[SdkModelDefinition]) -> SdkModelDefinition | None:
        if not model_definitions:
            return None
        preferred = next((model for model in model_definitions if model.class_name == "Customer"), None)
        return preferred or model_definitions[0]

    def get_example_field_name(self, model_definition: SdkModelDefinition | None) -> str:
        if not model_definition or not model_definition.fields:
            return "title"
        preferred_field = next(
            (
                field
                for field in model_definition.fields
                if field.name not in {"id", "created_by", "updated_by", "datetime_created", "datetime_updated"}
            ),
            None,
        )
        return preferred_field.name if preferred_field else model_definition.fields[0].name

    def get_example_id_value(self, model_definition: SdkModelDefinition | None, *, quoted: bool) -> str:
        if model_definition and model_definition.pk_type == "string":
            return '"1"' if quoted else "1"
        return "1"

    def serialize_field_metadata(self, field: SdkFieldDefinition) -> dict:
        payload = asdict(field)
        payload.pop("js_doc_type")
        payload.pop("python_type")
        return {
            "name": payload["name"],
            "title": payload["title"],
            "fieldType": payload["field_type"],
            "dbFieldType": payload["db_field_type"],
            "nullable": payload["nullable"],
            "many": payload["many"],
            "relatedModel": payload["related_model_name"],
            "editable": payload["editable"],
            "requiredOnCreate": payload["required_on_create"],
            "tsType": payload["ts_type"],
        }

    def to_camel_case(self, value: str) -> str:
        parts = [part for part in value.replace("-", "_").split("_") if part]
        if not parts:
            return value
        return parts[0] + "".join(part[:1].upper() + part[1:] for part in parts[1:])

    def to_pascal_case(self, value: str) -> str:
        parts = [part for part in value.replace("-", "_").split("_") if part]
        if not parts:
            return value
        return "".join(part[:1].upper() + part[1:] for part in parts)
