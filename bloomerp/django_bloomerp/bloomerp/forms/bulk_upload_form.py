from django import forms
from django.contrib.contenttypes.models import ContentType
from django.db.models import Model
from typing import Literal

from bloomerp.field_types import FieldType
from bloomerp.models import ApplicationField


AUTO_MANAGED_FIELD_NAMES = {
    "id",
    "pk",
    "datetime_created",
    "datetime_updated",
    "created_by",
    "updated_by",
    "avatar"
}


class BloomerpBulkForm(forms.Form):
    file_type = forms.ChoiceField(
        choices=[("csv", "CSV"), ("xlsx", "Excel")],
        label="File format",
    )

    def __init__(
        self,
        model: type[Model] | None = None,
        content_type: ContentType | None = None,
        application_fields=None,
        make_required: bool = True,
        skip_ineligible_fields: bool = True,
        mode: Literal["import", "export"] = "import",
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.mode = mode
        self.make_required = make_required if mode == "import" else False
        self.skip_ineligible_fields = skip_ineligible_fields

        self.content_type = self._resolve_content_type(
            model=model,
            content_type=content_type,
            data=kwargs.get("data"),
        )
        self.model = self.content_type.model_class() if self.content_type else None
        if self.model is None:
            raise ValueError("Model could not be determined.")

        if application_fields is None:
            application_fields = ApplicationField.get_for_model(self.model).order_by("field")

        self.application_fields = []
        self.model_fields: list[str] = []
        self.required_model_fields: set[str] = set()

        def skip_field(application_field: ApplicationField) -> bool:
            if not self.skip_ineligible_fields:
                return False
            if application_field.field in AUTO_MANAGED_FIELD_NAMES:
                return True
            try:
                model_field = application_field._get_model_field()
            except Exception:
                return True
            if not getattr(model_field, "editable", True):
                return True
            if not getattr(model_field, "concrete", True):
                return True
            
            form_field = application_field.get_form_field()
            if form_field is None:
                return True
            
            return False
        
        for application_field in application_fields:
            if skip_field(application_field):
                continue

            try:
                model_field = application_field._get_model_field()
            except Exception:
                model_field = None

            try:
                form_field = application_field.get_form_field()
            except Exception:
                form_field = None

            field_name = application_field.field
            label = (
                (form_field.label if form_field is not None else None)
                or application_field.title
                or (str(model_field.verbose_name).title() if model_field is not None else field_name.replace("_", " ").title())
            )
            help_text = (
                (form_field.help_text if form_field is not None else None)
                or (getattr(model_field, "help_text", "") if model_field is not None else "")
            )
            is_required = bool(form_field.required) if self.make_required and form_field is not None else False
            self.fields[field_name] = forms.BooleanField(
                label=label,
                required=False,
                initial=is_required,
                disabled=is_required,
                help_text=help_text,
            )
            if is_required:
                self.required_model_fields.add(field_name)
            self.application_fields.append(application_field)
            self.model_fields.append(field_name)

        self.fields["content_type_id"] = forms.IntegerField(
            widget=forms.HiddenInput(),
            initial=self.content_type.pk,
        )

    @property
    def intro_text(self) -> str:
        if self.mode == "export":
            return "Choose the fields you want to export, then download the result as CSV or Excel."
        return "Choose the fields you want in the template, then download a CSV or Excel file to fill in offline."

    @property
    def selection_help_text(self) -> str:
        if not self.skip_ineligible_fields:
            return "All permitted fields are available for selection."
        if self.mode == "export":
            return "Only fields included in this export are shown here."
        return "Only fields that are editable and not auto-managed are shown here."

    @property
    def submit_label(self) -> str:
        if self.mode == "export":
            return "Export"
        return "Download template"

    def _resolve_content_type(
        self,
        *,
        model: type[Model] | None,
        content_type: ContentType | None,
        data,
    ) -> ContentType | None:
        if content_type is not None:
            return content_type

        content_type_id = None
        if data is not None:
            content_type_id = data.get("content_type_id")

        if content_type_id:
            try:
                return ContentType.objects.get(pk=content_type_id)
            except ContentType.DoesNotExist:
                return None

        if model is not None:
            return ContentType.objects.get_for_model(model)

        return None

    def clean(self):
        cleaned_data = super().clean()
        for field_name in self.required_model_fields:
            cleaned_data[field_name] = True
        if not any(cleaned_data.get(field_name) for field_name in self.model_fields):
            if self.mode == "export":
                raise forms.ValidationError("Select at least one field to export.")
            raise forms.ValidationError("Select at least one field for the template.")
        return cleaned_data

    def get_selected_fields(self) -> list[str]:
        if not self.is_bound or not self.is_valid():
            return []
        return [field_name for field_name in self.model_fields if self.cleaned_data.get(field_name, False)]


class BulkUploadWizardUploadForm(forms.Form):
    bulk_upload_file = forms.FileField(
        label="Upload file",
        help_text="Upload a CSV or Excel template populated with one object per row.",
    )

    def __init__(self, *args, require_file: bool = True, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["bulk_upload_file"].required = require_file
        self.fields["bulk_upload_file"].widget.attrs.update(
            {
                "class": "input w-full",
                "accept": ".csv,.xlsx,.xls",
            }
        )

    def clean_bulk_upload_file(self):
        uploaded_file = self.cleaned_data.get("bulk_upload_file")
        if uploaded_file in (None, ""):
            return uploaded_file
        filename = (getattr(uploaded_file, "name", "") or "").lower()
        if not filename.endswith((".csv", ".xlsx", ".xls")):
            raise forms.ValidationError("Upload a CSV or Excel file.")
        return uploaded_file
