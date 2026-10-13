from bloomerp.mcp.definition import McpResource
from bloomerp.permissions.definition import BloomerpPermission, RowPolicyRuleContent
from bloomerp.router import router
from bloomerp.views.mcp.authoring_references import packaged_guide
from django.core.exceptions import PermissionDenied

from django.http import HttpRequest


import json


@router.register(
    name="Permissions and policy authoring reference",
    description="Current global, row and field grants, policy creation and user/group assignment.",
    mcp=McpResource(uri="bloomerp://guides/create-policy", mime_type="text/markdown"),
)
def policy_resource(request: HttpRequest) -> str:
    """Return policy guidance and authoritative permission/filter metadata without records."""
    if not request.user.is_authenticated:
        raise PermissionDenied(
            "Authentication is required to read authoring references."
        )
    permissions = [
        {
            "action": permission.value.codename,
            "description": permission.value.description,
            "scopes": [scope.value for scope in permission.value.scopes],
        }
        for permission in BloomerpPermission
    ]
    metadata = {
        "model_permissions": permissions,
        "row_rule_schema": RowPolicyRuleContent.model_json_schema(),
    }
    return (
        packaged_guide("create-policy.md")
        + "\n\n## Current permission and row-rule definitions\n\n```json\n"
        + json.dumps(metadata, indent=2)
        + "\n```\n"
    )