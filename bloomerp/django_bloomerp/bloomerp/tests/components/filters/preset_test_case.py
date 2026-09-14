from django.contrib.contenttypes.models import ContentType

from bloomerp.filters.definition import Filter, FilterCondition
from bloomerp.models.filters.filter import SavedFilter
from bloomerp.models.workspaces.workspace import Workspace
from bloomerp.tests.base import BloomerpComponentTestCase


class PresetComponentTestCase(BloomerpComponentTestCase):
    auto_create_customers = False

    def extendedSetup(self):
        self.identifier = str(ContentType.objects.get_for_model(self.CustomerModel).pk)
        self.workspace = Workspace.objects.create(user=self.admin_user, name="Preset workspace")
        self.groups = [Filter(connector="AND", conditions=[FilterCondition(field_path="first_name", lookup_id="equals", value="David")]).model_dump()]
        self.preset = SavedFilter.objects.create(scope="model", identifier=self.identifier, name="Original", filters=self.groups)
        self.workspace_preset = SavedFilter.objects.create(scope="workspace", identifier=str(self.workspace.pk), name="Workspace", filters=[])

    def model_scope(self):
        return {"scope": "model", "identifier": self.identifier}

    def saved_count_and_name(self, count, name, same_id=None):
        def validate(response):
            data = response.json()
            self.assertEqual(SavedFilter.objects.count(), count)
            self.assertEqual(data["name"], name)
            if same_id:
                self.assertEqual(data["id"], str(same_id))
            self.assertEqual(SavedFilter.objects.get(pk=data["id"]).filters, data["filters"])
            return True
        return validate
