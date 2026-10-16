"""Exercise record-scoped file-node filters through generated view scenarios."""

from urllib.parse import urlsplit

from bs4 import BeautifulSoup
from django.contrib.contenttypes.models import ContentType
from django.http import HttpResponse, QueryDict
from django.urls import reverse

from bloomerp.filters.manager import ModelFilterManager
from bloomerp.models.files.file_node import FileNode
from bloomerp.models.files.file_reference import FileReference
from bloomerp.models.project_management.todo import Todo
from bloomerp.permissions.definition import RowPolicyRuleContent
from bloomerp.permissions.manager import PolicyManager, UserPolicyManager
from bloomerp.tests.base import (
    BloomerpDetailViewTestCase,
    ExpectedResult,
    ModelRequestScenario,
    RequestScenario,
)


class TestBloomerpDetailFileListView(BloomerpDetailViewTestCase):
    """Verify the embedded dataview receives an executable record scope."""

    view_name = "files"
    model = None
    auto_create_customers = False

    def dataview_query(self, response: HttpResponse) -> QueryDict:
        """Extract the actual rendered file-node component's query parameters."""
        endpoint = reverse(
            "components_dataview",
            kwargs={"content_type_id": ContentType.objects.get_for_model(FileNode).pk},
        )
        document = BeautifulSoup(response.content, "html.parser")
        element = document.select_one(f'div[hx-get^="{endpoint}?"]')
        self.assertIsNotNone(element)
        return QueryDict(urlsplit(element["hx-get"]).query)

    def get_test_scenarios(self) -> list[RequestScenario]:
        """Check serialization, both reference identifiers, and object access."""
        customer = self.CustomerModel.objects.create(
            first_name="File", last_name="Owner", age=30
        )
        other_customer = self.CustomerModel.objects.create(
            first_name="Other", last_name="Owner", age=31
        )
        self.file_owner = customer
        same_id_todo = Todo.objects.create(id=customer.pk, title="Same key, other model")
        linked = FileNode.objects.create(
            name="Linked.txt", kind="FILE", content="legacy/linked.txt"
        )
        unrelated = FileNode.objects.create(
            name="Unrelated.txt", kind="FILE", content="legacy/unrelated.txt"
        )
        self.private_unreferenced = FileNode.objects.create(
            name="Private unreferenced.txt", kind="FILE", content="legacy/private.txt",
            created_by=self.admin_user,
        )
        self.linked_file = linked
        FileReference.objects.create(file=linked, content_object=customer)
        # Neither reference matches both identifiers on the same record.
        FileReference.objects.create(file=unrelated, content_object=other_customer)
        FileReference.objects.create(file=unrelated, content_object=same_id_todo)
        return [
            ModelRequestScenario(
                name="Rendered filter selects only files referencing this record",
                user=self.admin_user,
                model=self.CustomerModel,
                view_kwargs={"pk": customer.pk},
                expected=ExpectedResult(
                    response_validators=self.reference_scope_matches,
                ),
            ),
            ModelRequestScenario(
                name="Readable files field delegates file browsing without file-node policies",
                user=self.normal_user,
                model=self.CustomerModel,
                view_kwargs={"pk": customer.pk},
                prepare=self.grant_record_files,
                expected=ExpectedResult(response_validators=self.token_browses_only_record_files),
            ),
            ModelRequestScenario(
                name="Files permission on another row cannot issue a token for this row",
                user=self.normal_user,
                model=self.CustomerModel,
                view_kwargs={"pk": other_customer.pk},
                prepare=self.grant_record_files,
                expected=ExpectedResult(status_code=403),
            ),
            ModelRequestScenario(
                name="User without record access cannot open its files page",
                user=self.normal_user,
                model=self.CustomerModel,
                view_kwargs={"pk": customer.pk},
                expected=ExpectedResult(status_code=403),
            ),
        ]

    def reference_scope_matches(self, response: HttpResponse) -> bool:
        """Keep both reference identifiers correlated when applying the embedded filter."""
        query = self.dataview_query(response)
        return list(ModelFilterManager(FileNode).filter(
            {"filter": query["filter"]}, FileNode.objects.all(),
        ).values_list("pk", flat=True)) == [self.linked_file.pk]

    def grant_record_files(self, scenario: RequestScenario) -> None:
        """Grant parent-row viewing broadly but files access only for the selected owner."""
        PolicyManager.create_policy(
            self.CustomerModel, global_permissions=["view"],
            field_permissions={"first_name": ["view"]},
            row_permissions=[RowPolicyRuleContent(permissions=["view"])],
        ).assign_user(self.normal_user)
        PolicyManager.create_policy(
            self.CustomerModel, global_permissions=["view"],
            field_permissions={"files": ["view"]},
            row_permissions=[RowPolicyRuleContent(permissions=["view"], conditions=[
                {"field_path": "id", "lookup_id": "equals", "value": str(self.file_owner.pk)},
            ])],
        ).assign_user(self.normal_user)

    def token_browses_only_record_files(self, response: HttpResponse) -> bool:
        """Exercise the real file dataview, its action token, and removal of the visible filter."""
        self.assertFalse(UserPolicyManager(self.normal_user).has_global_permission(FileNode, "view"))
        query = self.dataview_query(response)
        endpoint = reverse("components_dataview", kwargs={
            "content_type_id": ContentType.objects.get_for_model(FileNode).pk,
        })
        browser = self.client.get(endpoint, query)
        self.assertContains(browser, self.linked_file.name)
        action_url = reverse("components_objects_actions", kwargs={
            "content_type_id": ContentType.objects.get_for_model(FileNode).pk,
            "object_id": self.linked_file.pk, "action_id": "view_file",
        })
        action = BeautifulSoup(browser.content, "html.parser").select_one(f'button[hx-post^="{action_url}?"]')
        self.assertIsNotNone(action)
        self.assertEqual(QueryDict(urlsplit(action["hx-post"]).query)["_permission_token"], query["_permission_token"])
        self.assertEqual(list(browser.context["queryset"].values_list("pk", flat=True)), [self.linked_file.pk])
        unfiltered = self.client.get(endpoint, {"_permission_token": query["_permission_token"]})
        self.assertEqual(unfiltered.status_code, 200)
        self.assertEqual(list(unfiltered.context["queryset"].values_list("pk", flat=True)), [self.linked_file.pk])
        manager = UserPolicyManager(self.normal_user, token=query["_permission_token"])
        self.assertFalse(manager.has_global_permission(FileNode, "change"))
        self.assertFalse(manager.has_global_permission(FileNode, "delete"))
        from unittest.mock import patch

        from django.test import RequestFactory

        from bloomerp.files.access import FileAccessManager

        request = RequestFactory().get("/files/", {"_permission_token": query["_permission_token"]})
        request.user = self.normal_user
        with patch("bloomerp.middleware.current_request", return_value=request):
            self.assertFalse(FileAccessManager(self.normal_user).can_read_file_node(self.private_unreferenced))
        return True
