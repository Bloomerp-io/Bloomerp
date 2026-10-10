
from dataclasses import dataclass

from django.core.exceptions import FieldDoesNotExist, ValidationError
from django.db import transaction
from django.http import HttpRequest

from bloomerp.field_types.registry import FIELD_TYPE_REGISTRY
from bloomerp.form_fields.files_relation_field import FilesCleanedData
from bloomerp.forms.model_form import BloomerpModelForm, bloomerp_modelform_factory
from bloomerp.models import ApplicationField
from bloomerp.models.files.file_reference import FileReference
from bloomerp.models.forms.form import Form
from bloomerp.models.forms.form_submission import FormSubmission
from bloomerp.utils.json_serialization import make_json_safe


@dataclass
class FormSubmissionResponse:
    submitted:bool
    message:str
    form_submission:FormSubmission | None = None


class FormManager:
    MAX_SUBMISSIONS_MESSAGE = "This form has reached the maximum number of submissions."
    
    def __init__(self, form:Form):
        self.form = form
        
    def register_submission(self, form:BloomerpModelForm, request:HttpRequest) -> FormSubmissionResponse:
        """Registers a form submission

        Args:
            data (dict): the incoming data
            request (HttpRequest): the request object
        """
        # Check if form can actually submit
        if not self.can_submit(request):
            return FormSubmissionResponse(
                False,
                self.MAX_SUBMISSIONS_MESSAGE,
                None,
            )
        
        submission_data = form.serialize_cleaned_data()
        
        submission = FormSubmission.objects.create(
            form=self.form,
            data=make_json_safe(submission_data),
        )
        if form.files:
            FilesCleanedData(
                files=[
                    uploaded_file
                    for _, uploaded_files in form.files.lists()
                    for uploaded_file in uploaded_files
                ]
            ).save(submission, user=request.user if request.user.is_authenticated else None)
        
        if not self.form.requires_review:
            submission = self.persist_form_submission(submission, request=request)

        return FormSubmissionResponse(
            True,
            "Form submitted",
            submission,
        )
        
             
    def can_submit(self, request:HttpRequest) -> bool:
        """Checks whether a form can be submitted

        Returns:
            bool: whether the form can be submitted or not
        """
        if self.form.max_submissions:
            nr_of_submissions = FormSubmission.objects.filter(form=self.form).count()
            if nr_of_submissions >= self.form.max_submissions:
                return False
            
        return True


    def get_initial_payload(self) -> dict:
        """Return the configured initial payload as a dict."""
        payload = self.form.initial_payload
        return dict(payload) if isinstance(payload, dict) else {}

    def get_initial_model_payload(self, initial_payload: dict | None = None) -> dict:
        """Return initial payload values that are direct model fields."""
        payload = initial_payload if isinstance(initial_payload, dict) else self.get_initial_payload()
        layout_only_field_names = {
            "files",
            *self.layout_one_to_many_field_names(),
        }
        return {
            field_name: value
            for field_name, value in payload.items()
            if field_name not in layout_only_field_names
        }

    def apply_one_to_many_initial_payload(
        self,
        *,
        initial_payload: dict,
        submitted_one_to_many_data: dict[str, list[dict]],
    ) -> dict[str, list[dict]]:
        one_to_many_data: dict[str, list[dict]] = {}
        one_to_many_field_names = self.layout_one_to_many_field_names()
        for field_name, value in initial_payload.items():
            if field_name not in one_to_many_field_names:
                continue
            config = self.normalize_one_to_many_initial_payload(value)
            submitted_rows = submitted_one_to_many_data.get(field_name)
            rows = submitted_rows if submitted_rows is not None else config["initial_rows"]
            if rows:
                one_to_many_data[field_name] = [
                    {
                        **config["row_defaults"],
                        **row,
                    }
                    for row in rows
                ]

        for field_name, rows in submitted_one_to_many_data.items():
            one_to_many_data.setdefault(field_name, rows)
        return one_to_many_data


    def normalize_one_to_many_initial_payload(self, value) -> dict:
        if isinstance(value, dict):
            initial_rows = value.get("initial_rows", [])
            row_defaults = value.get("row_defaults", {})
            return {
                "initial_rows": initial_rows if isinstance(initial_rows, list) else [],
                "row_defaults": row_defaults if isinstance(row_defaults, dict) else {},
            }
        if isinstance(value, list) and all(isinstance(item, dict) for item in value):
            return {"initial_rows": value, "row_defaults": {}}
        return {"initial_rows": [], "row_defaults": {}}

    def layout_one_to_many_field_names(self) -> set[str]:
        return {
            field.field
            for field in self.layout_application_fields()
            if field.get_field_type().id == FIELD_TYPE_REGISTRY.ONE_TO_MANY_FIELD.id
        }

    def get_initial_form_data(self) -> dict:
        """Return initial payload values for fields present in the visible form."""
        visible_field_names = set(self.layout_model_form_field_names())
        return {
            field_name: value
            for field_name, value in self.get_initial_payload().items()
            if field_name in visible_field_names
        }
    
    def layout_application_fields(self) -> list[ApplicationField]:
        """Return application fields represented by this form's layout, in layout order."""
        layout = self.form.layout_obj
        ordered_ids = [
            str(item.id)
            for row in layout.rows
            for item in row.items
            if item.id not in (None, "")
        ]
        if not ordered_ids:
            return []

        content_type = self.form.content_type
        fields_by_id = {
            str(field.pk): field
            for field in ApplicationField.objects.filter(
                content_type=content_type,
                id__in=[item_id for item_id in ordered_ids if item_id.isdigit()],
            )
        }
        fields_by_name = {
            field.field: field
            for field in ApplicationField.objects.filter(
                content_type=content_type,
                field__in=[item_id for item_id in ordered_ids if not item_id.isdigit()],
            )
        }

        application_fields: list[ApplicationField] = []
        seen: set[str] = set()
        for item_id in ordered_ids:
            application_field = fields_by_id.get(item_id) or fields_by_name.get(item_id)
            if application_field is None or application_field.field in seen:
                continue
            application_fields.append(application_field)
            seen.add(application_field.field)

        return application_fields

    def layout_field_names(self, extra_fields: list[str] | None = None) -> list[str]:
        """Return target field names represented by this form's layout."""
        field_names = [field.field for field in self.layout_application_fields()]
        seen = set(field_names)

        if extra_fields and isinstance(extra_fields, list):
            for field_name in extra_fields:
                if field_name and field_name not in seen:
                    field_names.append(field_name)
                    seen.add(field_name)

        return field_names

    def layout_model_form_field_names(self, extra_fields: list[str] | None = None) -> list[str]:
        """Return layout fields that can be passed to a target model ModelForm."""
        field_names = [
            field.field
            for field in self.layout_application_fields()
        ]
        seen = set(field_names)

        if extra_fields and isinstance(extra_fields, list):
            for field_name in extra_fields:
                if field_name and field_name not in seen and self.can_use_model_form_field(field_name):
                    field_names.append(field_name)
                    seen.add(field_name)

        return field_names

    def can_use_model_form_field(self, field_name: str) -> bool:
        """Return whether a field name can safely be passed to the target ModelForm."""
        target_model = self.form.content_type.model_class()
        if target_model is None or not field_name:
            return False

        try:
            model_field = target_model._meta.get_field(field_name)
        except FieldDoesNotExist:
            return False

        if getattr(model_field, "auto_created", False):
            return False
        if not getattr(model_field, "editable", True):
            return False
        if not getattr(model_field, "concrete", True) and not getattr(model_field, "many_to_many", False):
            return False
        return True

    def layout_form_cls(self, extra_fields:list[str] | None=None) -> type[BloomerpModelForm] | None:
        """Returns the layout form for this form object

        Returns:
            ModelForm: the django form object
        """
        target_model = self.form.content_type.model_class()
        field_names = self.layout_model_form_field_names(extra_fields=extra_fields)
        if target_model is None or not field_names:
            return None
        
        return bloomerp_modelform_factory(target_model, fields=field_names)
        
    def persist_form_submission(
        self, form_submission: FormSubmission, request: HttpRequest | None = None
    ) -> FormSubmission:
        """Method to persist a form submission. Can be used

        Args:
            form_submission (FormSubmission): the form submission
        """
        if form_submission.persisted:
            return form_submission
        
        form_class = self.layout_form_cls()
        target_model = self.form.content_type.model_class()
        if form_class is None or target_model is None:
            raise ValidationError("This form submission cannot be persisted.")

        target_form = form_class.from_deserialized_data(form_submission.data)
        if not target_form.is_valid():
            raise ValidationError(target_form.errors)
        
        with transaction.atomic():
            target_object = target_form.save()
            
            for reference in form_submission.files.filter(
                application_field__isnull=True, occurrence_id__isnull=True
            ):
                FileReference.objects.get_or_create(
                    file_id=reference.file_id,
                    content_type=self.form.content_type,
                    object_id=str(target_object.pk),
                    application_field=None,
                    occurrence_id=None,
                )
            
            form_submission.persisted = True
            form_submission.save(update_fields=["persisted"])

        return form_submission
        
