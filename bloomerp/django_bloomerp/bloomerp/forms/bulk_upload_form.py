from django import forms
from django.contrib.contenttypes.models import ContentType
from django.db.models import Model

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


class BloomerpDownloadBulkUploadTemplateForm(forms.Form):
    file_type = forms.ChoiceField(
        choices=[("csv", "CSV"), ("xlsx", "Excel")],
        label="Template format",
    )

    def __init__(
        self,
        model: type[Model] | None = None,
        content_type: ContentType | None = None,
        application_fields=None,
        make_required: bool = True,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)

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

        for application_field in application_fields:
            if application_field.field in AUTO_MANAGED_FIELD_NAMES:
                continue

            try:
                form_field = application_field.get_form_field()
            except Exception:
                continue

            if form_field is None:
                continue

            try:
                model_field = application_field._get_model_field()
            except Exception:
                continue
            if not getattr(model_field, "editable", True):
                continue
            if not getattr(model_field, "concrete", True):
                continue

            field_name = application_field.field
            is_required = bool(form_field.required) if make_required else False
            self.fields[field_name] = forms.BooleanField(
                label=form_field.label or application_field.title,
                required=False,
                initial=is_required,
                disabled=is_required,
                help_text=form_field.help_text,
            )
            if is_required:
                self.required_model_fields.add(field_name)
            self.application_fields.append(application_field)
            self.model_fields.append(field_name)

        self.fields["content_type_id"] = forms.IntegerField(
            widget=forms.HiddenInput(),
            initial=self.content_type.pk,
        )

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
