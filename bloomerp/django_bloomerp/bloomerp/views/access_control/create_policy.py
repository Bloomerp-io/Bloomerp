import json

from django import forms
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.db.models import Model
from django.http import HttpRequest
from django.shortcuts import redirect
from django_htmx.http import HttpResponseClientRedirect
from django.utils.translation import gettext_lazy as _
from django.views.generic import TemplateView

from bloomerp.models.access_control.row_policy_rule import ROW_POLICY_DISALLOWED_FIELD_TYPE_IDS, RowPolicyRuleContent
from bloomerp.models.access_control.policy import Policy
from bloomerp.models.application_field import ApplicationField
from bloomerp.router import router
from bloomerp.serializers.access_control import PolicySerializer
from bloomerp.views.base import BaseBloomerpView
from bloomerp.views.mixins.wizard_mixin import BaseStateOrchestrator, WizardMixin, WizardStep
from bloomerp.views.mixins.wizard_mixin import WizardError
from pydantic import ValidationError as PydanticValidationError

from bloomerp.widgets.foreign_field_widget import ForeignFieldWidget

CONTENT_TYPE_ID_KEY = "content_type_id"
GLOBAL_PERMISSIONS_KEY = "global_permissions"
ROW_POLICY_NAME_KEY = "row_policy_name"
ROW_POLICY_RULES_KEY = "row_policy_rules"
FIELD_POLICY_NAME_KEY = "field_policy_name"
FIELD_POLICIES_KEY = "field_policies"
POLICY_NAME_KEY = "policy_name"
POLICY_DESCRIPTION_KEY = "policy_description"


class SelectContentTypeForm(forms.Form):
    content_type = forms.ModelChoiceField(
        queryset=ContentType.objects.all(),
        label=_("Content type"),
        widget=ForeignFieldWidget(
            model=ContentType,
            attrs={"class": "input"},
        ),
    )

    def clean_content_type(self) -> ContentType:
        content_type = self.cleaned_data["content_type"]
        if content_type.model_class() is None:
            raise forms.ValidationError(
                _("Please select a content type with an installed model."),
            )
        return content_type


def _clear_policy_configuration(orchestrator: BaseStateOrchestrator) -> None:
    for key in (
        GLOBAL_PERMISSIONS_KEY,
        ROW_POLICY_NAME_KEY,
        ROW_POLICY_RULES_KEY,
        FIELD_POLICY_NAME_KEY,
        FIELD_POLICIES_KEY,
        POLICY_NAME_KEY,
        POLICY_DESCRIPTION_KEY,
    ):
        orchestrator.set_session_data(key, None)


def ctx_content_type(request: HttpRequest, view, orchestrator: BaseStateOrchestrator):
    return {
        "form": SelectContentTypeForm(
            data=request.POST or None,
            initial={"content_type": orchestrator.get_session_data(CONTENT_TYPE_ID_KEY)},
        ),
    }


def pcs_content_type(request: HttpRequest, view, orchestrator: BaseStateOrchestrator):
    form = SelectContentTypeForm(data=request.POST)
    if not form.is_valid():
        return WizardError(
            message=_("Please select a valid content type before continuing."),
            title=_("Content type required"),
            step=0,
        )

    content_type = form.cleaned_data["content_type"]
    previous_content_type_id = orchestrator.get_session_data(CONTENT_TYPE_ID_KEY)
    if previous_content_type_id and int(previous_content_type_id) != content_type.pk:
        _clear_policy_configuration(orchestrator)
    orchestrator.set_session_data(CONTENT_TYPE_ID_KEY, content_type.pk)


def _content_type_for_model(model: type[Model]) -> ContentType:
    return ContentType.objects.get_for_model(model)


def _policy_content_type_for_view(view) -> ContentType:
    return view.get_policy_content_type()


def _policy_model_for_view(view) -> type[Model]:
    return _policy_content_type_for_view(view).model_class()


def _available_permissions(model: type[Model]) -> list[Permission]:
    content_type = _content_type_for_model(model)
    return list(Permission.objects.filter(content_type=content_type).order_by("name"))


def _available_permissions_by_codename(model: type[Model]) -> dict[str, Permission]:
    return {permission.codename: permission for permission in _available_permissions(model)}


def _filter_builder_state_to_global_permissions(orchestrator: BaseStateOrchestrator, global_permissions: list[str]) -> None:
    allowed_permissions = set(global_permissions)

    row_policy_rules = orchestrator.get_session_data(ROW_POLICY_RULES_KEY) or []
    filtered_row_policy_rules = []
    for row_policy_rule in row_policy_rules:
        permissions = [
            permission
            for permission in row_policy_rule.get("permissions", [])
            if permission in allowed_permissions
        ]
        if permissions:
            filtered_row_policy_rules.append(
                {
                    "rule": row_policy_rule.get("rule", {}),
                    "permissions": permissions,
                }
            )
    orchestrator.set_session_data(ROW_POLICY_RULES_KEY, filtered_row_policy_rules)

    field_policies = orchestrator.get_session_data(FIELD_POLICIES_KEY) or {}
    filtered_field_policies = {}
    for field_id, permissions in field_policies.items():
        filtered_permissions = [
            permission
            for permission in permissions
            if permission in allowed_permissions
        ]
        if filtered_permissions:
            filtered_field_policies[str(field_id)] = filtered_permissions
    orchestrator.set_session_data(FIELD_POLICIES_KEY, filtered_field_policies)


def _field_title_by_id(application_fields) -> dict[str, str]:
    return {str(field.pk): field.title for field in application_fields}


def _is_row_policy_field_allowed(application_field: ApplicationField) -> bool:
    return application_field.field_type not in ROW_POLICY_DISALLOWED_FIELD_TYPE_IDS


def _with_row_policy_flags(application_fields) -> list[ApplicationField]:
    fields = list(application_fields)
    for application_field in fields:
        application_field.is_row_policy_allowed = _is_row_policy_field_allowed(application_field)
    return fields


def _get_row_policy_conditions(row_policy_rule: dict) -> list[dict]:
    if not isinstance(row_policy_rule, dict):
        return []

    rule = row_policy_rule.get("rule") or {}
    if not isinstance(rule, dict):
        return []

    try:
        rule_content = RowPolicyRuleContent.model_validate(rule)
    except PydanticValidationError:
        return []

    return rule_content.model_dump(exclude_none=True)["conditions"]


def _policy_builder_context(view, orchestrator: BaseStateOrchestrator) -> dict:
    policy_model = _policy_model_for_view(view)
    application_fields = _with_row_policy_flags(ApplicationField.get_for_model(policy_model))
    field_titles = _field_title_by_id(application_fields)
    global_permissions = orchestrator.get_session_data(GLOBAL_PERMISSIONS_KEY) or []
    available_permissions = [
        permission
        for permission in _available_permissions(policy_model)
        if permission.codename in set(global_permissions)
    ]

    row_policy_rules = orchestrator.get_session_data(ROW_POLICY_RULES_KEY) or []
    field_policies = orchestrator.get_session_data(FIELD_POLICIES_KEY) or {}

    row_field_ids = []
    for row_policy_rule in row_policy_rules:
        for condition in _get_row_policy_conditions(row_policy_rule):
            application_field_id = str(condition.get("application_field_id", "")).strip()
            if application_field_id and application_field_id != "__all__" and application_field_id not in row_field_ids:
                row_field_ids.append(application_field_id)

    column_field_ids = []
    for field_id in field_policies.keys():
        field_key = str(field_id)
        if field_key == "__all__":
            for application_field in application_fields:
                application_field_id = str(application_field.pk)
                if application_field_id not in column_field_ids:
                    column_field_ids.append(application_field_id)
            continue

        if field_key and field_key not in column_field_ids:
            column_field_ids.append(field_key)

    return {
        "application_fields": application_fields,
        "content_type_id": _policy_content_type_for_view(view).id,
        "permissions": available_permissions,
        "selected_global_permissions": global_permissions,
        "row_policy_name": orchestrator.get_session_data(ROW_POLICY_NAME_KEY) or "",
        "field_policy_name": orchestrator.get_session_data(FIELD_POLICY_NAME_KEY) or "",
        "row_policy_rules_json": json.dumps(row_policy_rules),
        "field_policies_json": json.dumps(field_policies),
        "row_policy_fields": [
            {"id": field_id, "title": field_titles.get(field_id, field_id)}
            for field_id in row_field_ids
        ],
        "field_policy_fields": [
            {
                "id": field_id,
                "title": field_titles.get(field_id, field_id),
            }
            for field_id in column_field_ids
        ],
    }


def ctx_global_permissions(request: HttpRequest, view, orchestrator: BaseStateOrchestrator):
    policy_model = _policy_model_for_view(view)
    return {
        "content_type_id": _policy_content_type_for_view(view).id,
        "permissions": _available_permissions(policy_model),
        "selected_permissions": orchestrator.get_session_data(GLOBAL_PERMISSIONS_KEY) or [],
    }


def pcs_global_permissions(request: HttpRequest, view, orchestrator: BaseStateOrchestrator):
    available_permissions = _available_permissions_by_codename(_policy_model_for_view(view))
    global_permissions = [
        permission
        for permission in request.POST.getlist("global_permissions")
        if permission in available_permissions
    ]

    if not global_permissions:
        return WizardError(
            message=_("Please select at least one global permission before continuing."),
            title=_("Permission required"),
            step=view.get_step_index_for_process(pcs_global_permissions),
        )

    orchestrator.set_session_data(GLOBAL_PERMISSIONS_KEY, global_permissions)
    _filter_builder_state_to_global_permissions(orchestrator, global_permissions)


def ctx_object_access_control(request: HttpRequest, view, orchestrator: BaseStateOrchestrator):
    context = _policy_builder_context(view, orchestrator)
    context["selected_global_permissions_json"] = json.dumps(
        orchestrator.get_session_data(GLOBAL_PERMISSIONS_KEY) or []
    )
    return context


def pcs_object_access_control(request: HttpRequest, view, orchestrator: BaseStateOrchestrator):
    try:
        row_policy_rules = json.loads(request.POST.get("row_policy_rules_json", "[]") or "[]")
    except json.JSONDecodeError:
        return WizardError(
            message=_("The row policy configuration could not be read. Please review this step and try again."),
            title=_("Invalid row policy"),
            step=view.get_step_index_for_process(pcs_object_access_control),
        )

    try:
        field_policies = json.loads(request.POST.get("field_policies_json", "{}") or "{}")
    except json.JSONDecodeError:
        return WizardError(
            message=_("The field policy configuration could not be read. Please review this step and try again."),
            title=_("Invalid field policy"),
            step=view.get_step_index_for_process(pcs_object_access_control),
        )

    global_permissions = set(orchestrator.get_session_data(GLOBAL_PERMISSIONS_KEY) or [])

    invalid_row_permissions = sorted(
        {
            permission
            for row_policy_rule in row_policy_rules
            for permission in row_policy_rule.get("permissions", [])
            if permission not in global_permissions
        }
    )
    if invalid_row_permissions:
        return WizardError(
            message=_("Row policies can only use permissions selected in the global access control step."),
            title=_("Row policy mismatch"),
            step=view.get_step_index_for_process(pcs_object_access_control),
        )

    policy_content_type = _policy_content_type_for_view(view)
    disallowed_row_policy_field_ids = {
        str(field_id)
        for field_id in ApplicationField.objects.filter(
            content_type=policy_content_type,
            field_type__in=ROW_POLICY_DISALLOWED_FIELD_TYPE_IDS,
        ).values_list("id", flat=True)
    }
    invalid_row_policy_field_ids = sorted(
        {
            application_field_id
            for row_policy_rule in row_policy_rules
            for condition in _get_row_policy_conditions(row_policy_rule)
            for application_field_id in [str(condition.get("application_field_id", "")).strip()]
            if application_field_id
            and application_field_id != "__all__"
            and application_field_id in disallowed_row_policy_field_ids
        }
    )
    if invalid_row_policy_field_ids:
        return WizardError(
            message=_("Properties and one-to-many fields cannot be used in row policies."),
            title=_("Invalid row policy field"),
            step=view.get_step_index_for_process(pcs_object_access_control),
        )

    invalid_field_permissions = sorted(
        {
            permission
            for permissions in field_policies.values()
            for permission in permissions
            if permission not in global_permissions
        }
    )
    if invalid_field_permissions:
        return WizardError(
            message=_("Field policies can only use permissions selected in the global access control step."),
            title=_("Field policy mismatch"),
            step=view.get_step_index_for_process(pcs_object_access_control),
        )

    orchestrator.set_session_data(ROW_POLICY_NAME_KEY, (request.POST.get("row_policy_name") or "").strip())
    orchestrator.set_session_data(FIELD_POLICY_NAME_KEY, (request.POST.get("field_policy_name") or "").strip())
    orchestrator.set_session_data(ROW_POLICY_RULES_KEY, row_policy_rules)
    orchestrator.set_session_data(FIELD_POLICIES_KEY, field_policies)


def ctx_policy_details(request: HttpRequest, view, orchestrator: BaseStateOrchestrator):
    return {
        "policy_name": orchestrator.get_session_data(POLICY_NAME_KEY) or "",
        "policy_description": orchestrator.get_session_data(POLICY_DESCRIPTION_KEY) or "",
    }


def pcs_policy_details(request: HttpRequest, view, orchestrator: BaseStateOrchestrator):
    policy_name = (request.POST.get("policy_name") or "").strip()
    policy_description = (request.POST.get("policy_description") or "").strip()

    if not policy_name:
        return WizardError(
            message=_("Please give the policy a name before saving."),
            title=_("Name required"),
            step=view.get_step_index_for_process(pcs_policy_details),
        )

    orchestrator.set_session_data(POLICY_NAME_KEY, policy_name)
    orchestrator.set_session_data(POLICY_DESCRIPTION_KEY, policy_description)


@router.register(
    path="create",
    route_type="model",
    models=Policy,
    name="Create Policy",
    description="Create an access control policy",
    override=True,
)
class CreatePolicyView(WizardMixin, BaseBloomerpView, TemplateView):
    template_name = "views/base_wizard.html"
    model: type[Model] = None

    steps = [
        WizardStep(
            name=_("Choose content type"),
            description=_("Choose the content type for which you want to create a policy"),
            template_name="views/access_control/manage_permissions/wizard_content_type.html",
            context_func=ctx_content_type,
            process_func=pcs_content_type,
        ),
        WizardStep(
            name=_("Global access control"),
            description=_("Choose which model-level permissions this policy grants."),
            template_name="views/access_control/manage_permissions/wizard_global_permissions.html",
            context_func=ctx_global_permissions,
            process_func=pcs_global_permissions,
        ),
        WizardStep(
            name=_("Field based access control"),
            description=_("Configure row and field rules using only the selected global permissions."),
            template_name="views/access_control/manage_permissions/wizard_object_access_control.html",
            context_func=ctx_object_access_control,
            process_func=pcs_object_access_control,
        ),
        WizardStep(
            name=_("Policy details"),
            description=_("Give the policy a name and description before saving."),
            template_name="views/access_control/manage_permissions/wizard_policy_details.html",
            context_func=ctx_policy_details,
            process_func=pcs_policy_details,
        ),
    ]

    def setup(self, request: HttpRequest, *args, **kwargs):
        self.session_key = "access_control_create_policy_wizard"
        super().setup(request, *args, **kwargs)

    def get_policy_content_type(self) -> ContentType:
        return ContentType.objects.get(
            pk=self.orchestrator.get_session_data(CONTENT_TYPE_ID_KEY),
        )

    def get_policy_model(self) -> type[Model]:
        return self.get_policy_content_type().model_class()

    def get_step_index_for_process(self, process_func) -> int:
        return next(
            index
            for index, step in enumerate(self.steps)
            if step.process_func is process_func
        )

    def normalize_step_index(self, step: int) -> int:
        if step > 0:
            try:
                content_type = self.get_policy_content_type()
            except (ContentType.DoesNotExist, TypeError, ValueError):
                return 0
            if content_type.model_class() is None:
                return 0
        return super().normalize_step_index(step)

    def build_policy_payload(self) -> dict:
        return {
            "name": self.orchestrator.get_session_data(POLICY_NAME_KEY) or "",
            "description": self.orchestrator.get_session_data(POLICY_DESCRIPTION_KEY) or "",
            "content_type_id": self.get_policy_content_type().id,
            "global_permissions": self.orchestrator.get_session_data(GLOBAL_PERMISSIONS_KEY) or [],
            "row_policy": {
                "name": self.orchestrator.get_session_data(ROW_POLICY_NAME_KEY) or "Row Policy",
                "rules": self.orchestrator.get_session_data(ROW_POLICY_RULES_KEY) or [],
            },
            "field_policy": {
                "name": self.orchestrator.get_session_data(FIELD_POLICY_NAME_KEY) or "Field Policy",
                "rules": self.orchestrator.get_session_data(FIELD_POLICIES_KEY) or {},
            },
        }

    def serializer_error_to_wizard_error(self, serializer_errors) -> WizardError:
        if "global_permissions" in serializer_errors:
            return WizardError(
                message=str(serializer_errors["global_permissions"][0]),
                title=_("Global permissions error"),
                step=self.get_step_index_for_process(pcs_global_permissions),
            )
        if "row_policy" in serializer_errors or "field_policy" in serializer_errors:
            nested_error = serializer_errors.get("row_policy") or serializer_errors.get("field_policy")
            return WizardError(
                message=str(nested_error),
                title=_("Policy rules error"),
                step=self.get_step_index_for_process(pcs_object_access_control),
            )
        first_error = next(iter(serializer_errors.values()))[0]
        return WizardError(
            message=str(first_error),
            title=_("Could not save policy"),
            step=self.get_step_index_for_process(pcs_policy_details),
        )

    def save_policy(self, payload: dict) -> Policy | WizardError:
        serializer = PolicySerializer(data=payload)
        if not serializer.is_valid():
            return self.serializer_error_to_wizard_error(serializer.errors)

        return serializer.save(
            created_by=self.request.user,
            updated_by=self.request.user,
        )

    def done(self):
        payload = self.build_policy_payload()
        policy = self.save_policy(payload)
        if isinstance(policy, WizardError):
            return policy

        if self.request.htmx:
            return HttpResponseClientRedirect(policy.get_absolute_url())
        return redirect(policy.get_absolute_url())

    def has_permission(self):
        return self.request.user.is_superuser
