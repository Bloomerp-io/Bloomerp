"""Exercise reference navigation and physical browsing with real scoped querysets."""

import json
from types import SimpleNamespace
from typing import Any

from bs4 import BeautifulSoup
from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models import QuerySet
from django.test import RequestFactory
from django.urls import reverse

from bloomerp.dataviews.file_browser.config import FileBrowserDataview
from bloomerp.dataviews.file_browser.renderer import FileBrowserRenderer
from bloomerp.filters.definition import Filter, FilterCondition
from bloomerp.models.files.file_node import FileNode
from bloomerp.models.files.file_reference import FileReference
from bloomerp.models.project_management.todo import Todo
from bloomerp.modules.definition import module_registry
from bloomerp.permissions.definition import RowPolicyRuleContent
from bloomerp.permissions.manager import PolicyManager
from bloomerp.tests.base import BaseBloomerpTestCaseWithModels


class TestFileBrowserRenderer(BaseBloomerpTestCaseWithModels):
    """Verify navigation never widens file scope or exposes inaccessible owners."""

    auto_create_customers = False

    def extendedSetup(self) -> None:
        """Create two object references to one immutable file and an unassigned file."""
        self.customer = self.create_customer("Visible", "Customer", 30)
        self.todo = Todo.objects.create(title="Private task")
        self.shared = self.create_node("Shared.pdf")
        FileReference.objects.create(file=self.shared, content_object=self.customer)
        FileReference.objects.create(file=self.shared, content_object=self.todo)
        self.unassigned = self.create_node("Unassigned.pdf")
        self.ct = ContentType.objects.get_for_model(FileNode)

    def create_node(self, name: str, parent: FileNode | None = None) -> FileNode:
        """Store a small node with metadata and an optional physical parent."""
        return FileNode.objects.create(
            name=name, kind="FILE", parent=parent,
            content=SimpleUploadedFile(name, b"content"),
        )

    def renderer(self, *, params: dict[str, str] | None = None, queryset: QuerySet | None = None,
                 filters: list[Filter] | None = None, user: Any = None) -> FileBrowserRenderer:
        """Build the same renderer state used by the dataview component."""
        request = RequestFactory().get("/files/", params or {})
        request.user = user or self.admin_user
        state = SimpleNamespace(
            request=request, queryset=queryset if queryset is not None else FileNode.objects.all(),
            model=FileNode, content_type=self.ct, content_type_id=self.ct.pk,
            options=FileBrowserDataview(), filters=filters or [], query=None,
            preference=SimpleNamespace(view_type="file_browser"), render_fields=[],
            context={}, avatar_field=None, object_actions=[],
        )
        return FileBrowserRenderer(state)

    def test_virtual_module_model_object_navigation(self) -> None:
        """Show reference-derived folders, shared files in both scopes, and breadcrumbs."""
        module = module_registry.get_module_for_model(Todo)
        root = self.renderer().render()
        self.assertIn(module.localized_name, BeautifulSoup(root, "html.parser").get_text())
        self.assertIn(module_registry.get_module_for_model(self.CustomerModel).localized_name, root)
        self.assertIn("Unassigned", root)
        self.assertNotIn('data-file-id=', root)
        for obj, module_id in [(self.todo, module.full_id or module.code), (self.customer, module_registry.get_module_for_model(self.CustomerModel).full_id or module_registry.get_module_for_model(self.CustomerModel).code)]:
            ct = ContentType.objects.get_for_model(obj)
            path = [module_id, str(ct.pk), str(obj.pk)]
            for depth, label in [(1, str(obj._meta.verbose_name_plural)), (2, str(obj)), (3, self.shared.name)]:
                with self.subTest(object=obj, depth=depth):
                    html = self.renderer(params={"virtual_path": json.dumps(path[:depth])}).render()
                    self.assertIn(label, html)
                    if depth == 3:
                        self.assertEqual(html.count(f'data-file-id="{self.shared.pk}"'), 1)
                        self.assertNotIn(f'data-file-id="{self.unassigned.pk}"', html)
                        self.assertIn(f'data-upload-object-id="{obj.pk}"', html)
                    else:
                        self.assertNotIn('data-file-browser-upload-input', html)
        unassigned = self.renderer(params={"virtual_path": '["__unassigned__"]'}).render()
        self.assertIn(f'data-file-id="{self.unassigned.pk}"', unassigned)
        self.assertNotIn(f'data-file-id="{self.shared.pk}"', unassigned)

    def test_physical_navigation_keeps_filtered_scope(self) -> None:
        """Browse nested physical parents while preserving search/filter candidate files."""
        parent = FileNode.objects.create(name="Parent", kind="FOLDER")
        child = FileNode.objects.create(name="Child", kind="FOLDER", parent=parent)
        matching = self.create_node("Needle.txt", child)
        excluded = self.create_node("Excluded.txt", child)
        queryset = FileNode.objects.filter(pk=matching.pk)
        root = self.renderer(params={"folder_type": "physical"}, queryset=queryset).render()
        self.assertIn("Parent", root)
        self.assertNotIn("Child", root)
        html = self.renderer(params={"folder_type": "physical", "folder_id": str(child.pk)}, queryset=queryset).render()
        self.assertIn("Parent", html)
        self.assertIn("Child", html)
        self.assertIn(f'data-file-id="{matching.pk}"', html)
        self.assertNotIn(excluded.name, html)
        self.assertNotIn("create_folder", html)
        self.assertNotIn("draggable", html)
        self.assertNotIn("data-file-browser-upload-input", html)
        invalid = self.renderer(params={"folder_type": "physical", "folder_id": "invalid"}, queryset=queryset).render()
        self.assertNotIn('data-file-id=', invalid)

    def test_object_detail_is_flat_and_uses_cached_size(self) -> None:
        """Show matching files directly when a reference filter identifies one object."""
        ct = ContentType.objects.get_for_model(self.customer)
        filters = [Filter(connector="AND", conditions=[
            FilterCondition(field_path="references__content_type", lookup_id="equals", value=ct.pk),
            FilterCondition(field_path="references__object_id", lookup_id="equals", value=str(self.customer.pk)),
        ])]
        html = self.renderer(queryset=FileNode.objects.filter(pk=self.shared.pk), filters=filters).render()
        self.assertIn(f'data-file-id="{self.shared.pk}"', html)
        self.assertIn("7", html)
        self.assertIsNone(BeautifulSoup(html, "html.parser").select_one("tbody [data-browser-path]"))
        self.assertIn(f'data-upload-object-id="{self.customer.pk}"', html)

    def test_private_reference_does_not_leak_through_shared_file(self) -> None:
        """An accessible customer reference must not disclose a private task folder or label."""
        policy = PolicyManager.create_policy(
            model_or_content_type=self.CustomerModel,
            field_permissions={"files": ["view"]},
            row_permissions=[RowPolicyRuleContent(permissions=["view"], conditions=[])],
        )
        policy.users.add(self.normal_user)
        root = self.renderer(user=self.normal_user).render()
        self.assertIn(module_registry.get_module_for_model(self.CustomerModel).localized_name, root)
        self.assertNotIn("Private task", root)
        module = module_registry.get_module_for_model(Todo)
        ct = ContentType.objects.get_for_model(Todo)
        forged = self.renderer(user=self.normal_user, params={
            "virtual_path": json.dumps([module.full_id or module.code, str(ct.pk), str(self.todo.pk)])
        }).render()
        self.assertNotIn('data-file-id=', forged)
        self.assertNotIn("Private task", forged)
        physical = self.renderer(user=self.normal_user, params={"folder_type": "physical"}).render()
        self.assertIn(self.shared.name, physical)
        self.assertNotIn("Private task", physical)
        self.assertNotIn(self.unassigned.name, physical)

    def test_options_form_and_real_dataview_navigation(self) -> None:
        """Expose both modes in persisted options and reserve navigation parameters at the endpoint."""
        form_class = FileBrowserDataview.form_factory(self.renderer().state)
        form = form_class(data={"folder_type": "physical"})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["folder_type"], "physical")
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse("components_dataview", kwargs={"content_type_id": self.ct.pk}), {
            "folder_type": "virtual", "virtual_path": '["__unassigned__"]',
        })
        self.assertEqual(response.status_code, 200)
        document = BeautifulSoup(response.content, "html.parser")
        self.assertIsNotNone(document.select_one('[data-folder-type-select]'))
        self.assertIsNotNone(document.select_one(f'[data-file-id="{self.unassigned.pk}"]'))
