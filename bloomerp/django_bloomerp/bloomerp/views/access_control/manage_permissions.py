import json

from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.db.models import Model
from django.http import HttpRequest
from django.shortcuts import redirect
from django_htmx.http import HttpResponseClientRedirect
from django.utils.translation import gettext_lazy as _
from django.views.generic import TemplateView

from bloomerp.field_types import FieldType
from bloomerp.models.access_control.policy import Policy
from bloomerp.models.application_field import ApplicationField
from bloomerp.router import router
from bloomerp.serializers.access_control import PolicySerializer
from bloomerp.views.mixins import HtmxMixin
from bloomerp.views.view_mixins.wizard import BaseStateOrchestrator, WizardError, WizardMixin, WizardStep

GLOBAL_PERMISSIONS_KEY = "global_permissions"
ROW_POLICY_NAME_KEY = "row_policy_name"
ROW_POLICY_RULES_KEY = "row_policy_rules"
FIELD_POLICY_NAME_KEY = "field_policy_name"
FIELD_POLICIES_KEY = "field_policies"
POLICY_NAME_KEY = "policy_name"
POLICY_DESCRIPTION_KEY = "policy_description"


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


def _policy_builder_context(view, orchestrator: BaseStateOrchestrator) -> dict:
    policy_model = _policy_model_for_view(view)
    application_fields = ApplicationField.get_for_model(policy_model).exclude(
        field_type__in=[FieldType.ONE_TO_MANY_FIELD.id, FieldType.PROPERTY.id]
    )
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
        application_field_id = str(row_policy_rule.get("rule", {}).get("application_field_id", "")).strip()
        if application_field_id and application_field_id not in row_field_ids:
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
            step=0,
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
            message=_("The row policy configuration could not be read. Please review step 2 and try again."),
            title=_("Invalid row policy"),
            step=1,
        )

    try:
        field_policies = json.loads(request.POST.get("field_policies_json", "{}") or "{}")
    except json.JSONDecodeError:
        return WizardError(
            message=_("The field policy configuration could not be read. Please review step 2 and try again."),
            title=_("Invalid field policy"),
            step=1,
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
            message=_("Row policies can only use permissions selected in step 1."),
            title=_("Row policy mismatch"),
            step=1,
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
            message=_("Field policies can only use permissions selected in step 1."),
            title=_("Field policy mismatch"),
            step=1,
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
            step=2,
        )

    orchestrator.set_session_data(POLICY_NAME_KEY, policy_name)
    orchestrator.set_session_data(POLICY_DESCRIPTION_KEY, policy_description)


@router.register(
    path="access-control",
    route_type="model",
    models="__all__",
    name="Create Policy for {model}",
    description="Create an access control policies for {model}",
)
class ManageAccessControlForModelView(WizardMixin, HtmxMixin, TemplateView):
    template_name = "base_wizard.html"
    model: type[Model] = None

    steps = [
        WizardStep(
            name=_("Global access control"),
            description=_("Choose which model-level permissions this policy grants."),
            template_name="access_control_views/manage_permissions/wizard_global_permissions.html",
            context_func=ctx_global_permissions,
            process_func=pcs_global_permissions,
        ),
        WizardStep(
            name=_("Field based access control"),
            description=_("Configure row and field rules using only the global permissions selected in step 1."),
            template_name="access_control_views/manage_permissions/wizard_object_access_control.html",
            context_func=ctx_object_access_control,
            process_func=pcs_object_access_control,
        ),
        WizardStep(
            name=_("Policy details"),
            description=_("Give the policy a name and description before saving."),
            template_name="access_control_views/manage_permissions/wizard_policy_details.html",
            context_func=ctx_policy_details,
            process_func=pcs_policy_details,
        ),
    ]

    def setup(self, request: HttpRequest, *args, **kwargs):
        self.session_key = f"access_control_wizard_{self.model._meta.label_lower}"
        super().setup(request, *args, **kwargs)

    def get_policy_content_type(self) -> ContentType:
        return _content_type_for_model(self.model)

    def get_policy_model(self) -> type[Model]:
        return self.model

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
                step=0,
            )
        if "row_policy" in serializer_errors or "field_policy" in serializer_errors:
            nested_error = serializer_errors.get("row_policy") or serializer_errors.get("field_policy")
            return WizardError(
                message=str(nested_error),
                title=_("Policy rules error"),
                step=1,
            )
        first_error = next(iter(serializer_errors.values()))[0]
        return WizardError(
            message=str(first_error),
            title=_("Could not save policy"),
            step=2,
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
