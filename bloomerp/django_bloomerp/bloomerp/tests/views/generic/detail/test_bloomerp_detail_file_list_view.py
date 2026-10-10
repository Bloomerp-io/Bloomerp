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
        same_id_todo = Todo.objects.create(id=customer.pk, title="Same key, other model")
        linked = FileNode.objects.create(
            name="Linked.txt", kind="FILE", content="legacy/linked.txt"
        )
        unrelated = FileNode.objects.create(
            name="Unrelated.txt", kind="FILE", content="legacy/unrelated.txt"
        )
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
                    response_validators=lambda response: list(
                        ModelFilterManager(FileNode)
                        .filter(self.dataview_query(response), FileNode.objects.all())
                        .values_list("pk", flat=True)
                    ) == [linked.pk],
                ),
            ),
            ModelRequestScenario(
                name="User without record access cannot open its files page",
                user=self.normal_user,
                model=self.CustomerModel,
                view_kwargs={"pk": customer.pk},
                expected=ExpectedResult(status_code=403),
            ),
        ]
