"""Shared permission-scoped document template selection."""

from bloomerp.models.document_templates import DocumentTemplate
from bloomerp.models.users.user import AbstractBloomerpUser
from bloomerp.permissions.manager import UserPolicyManager


def readable_document_templates(user: AbstractBloomerpUser, query: str = "") -> list[DocumentTemplate]:
    """Return readable templates of every content type, optionally searching names."""
    manager = UserPolicyManager(user)
    if not manager.has_global_permission(DocumentTemplate, "view"):
        return []
    queryset = manager.get_accessible_queryset(DocumentTemplate, "view")
    if query:
        queryset = queryset.filter(name__icontains=query)
    return [
        template for template in queryset.distinct().order_by("name", "pk")
        if manager.has_access_to_object(
            template, "view", fields=["name", "template", "content_types", "free_variables"],
        )
    ]
