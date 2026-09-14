import json
from types import SimpleNamespace

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import RequestFactory

from bloomerp.filters.definition import Filter, FilterCondition
from bloomerp.models.application_field import ApplicationField
from bloomerp.permissions.editor import editor_rules
from bloomerp.tests.base import BaseBloomerpTestCaseWithModels
from bloomerp.views.access_control.create_policy import pcs_object_access_control, _policy_builder_context
from bloomerp.views.mixins.wizard_mixin import WizardError


class TestPermissionEditor(BaseBloomerpTestCaseWithModels):
    create_foreign_models = True
    auto_create_customers = False

    def extendedSetup(self):
        self.content_type = ContentType.objects.get_for_model(self.CustomerModel)
        self.view = SimpleNamespace(get_policy_content_type=lambda: self.content_type,
                                    get_step_index_for_process=lambda process: 2)
        self.state = {"global_permissions": ["view_customer"]}
        self.orchestrator = SimpleNamespace(get_session_data=lambda key: self.state.get(key),
                                            set_session_data=lambda key, value: self.state.update({key: value}))

    def entry(self, connector="AND", field="age", value=12):
        return {"rule": Filter(connector=connector, conditions=[FilterCondition(field_path=field, lookup_id="equals", value=value)]).model_dump(),
                "permissions": ["view_customer"]}

    def test_grouped_create_and_restore(self):
        """UC: Submit AND/OR rules. Expected Result: Groups, values and grants survive normalization."""
        entries = [self.entry(), self.entry("OR", "first_name", "David")]
        self.assertEqual(editor_rules(entries, self.content_type, user=self.admin_user), entries)

    def test_nested_restore(self):
        """UC: Edit a nested condition. Expected Result: Its complete terminal path is retained."""
        entries = [self.entry("OR", "country__name", "Belgium")]
        self.assertEqual(editor_rules(entries, self.content_type, user=self.admin_user), entries)

    def test_conditions_group_within_separate_grants(self):
        """UC: Combine an AND entry and an OR entry. Expected Result: Entries are ORed without flattening conditions."""
        from bloomerp.permissions.compilers.django_q_permission_compiler import DjangoQPermissionCompiler
        from bloomerp.permissions.definition import AccessRule, RowPolicyRuleContent
        rows = [self.CustomerModel.objects.create(first_name=name, last_name="Example", age=age)
                for name, age in [("David", 12), ("Other", 12), ("Other", 18), ("Emma", 8)]]
        first, second = self.entry("AND", value=12), self.entry("OR", value=18)
        first["rule"]["conditions"].append(FilterCondition(field_path="first_name", lookup_id="equals", value="David").model_dump())
        second["rule"]["conditions"].append(FilterCondition(field_path="first_name", lookup_id="equals", value="Emma").model_dump())
        entries = editor_rules([first, second], self.content_type, user=self.admin_user)
        access = AccessRule(row_permissions=[RowPolicyRuleContent(**entry["rule"], permissions=["view"]) for entry in entries])
        compiled = DjangoQPermissionCompiler([access], model=self.CustomerModel).compile("view")
        self.assertEqual(set(self.CustomerModel.objects.filter(compiled.row_filter).values_list("pk", flat=True)),
                         {rows[0].pk, rows[2].pk, rows[3].pk})

    def test_legacy_normalization_and_scope(self):
        """UC: Restore legacy field IDs and operators. Expected Result: Canonical conditions without scope loss."""
        field = ApplicationField.objects.get(content_type=self.content_type, field="first_name")
        legacy = {"rule": {"connector": "OR", "conditions": [{"application_field_id": str(field.pk), "operator": "exact", "value": "David"}]}, "permissions": ["view_customer"]}
        self.assertEqual(editor_rules([legacy], self.content_type), [self.entry("OR", "first_name", "David")])
        single = {"rule": legacy["rule"]["conditions"][0], "permissions": legacy["permissions"]}
        self.assertEqual(editor_rules([single], self.content_type), [self.entry("AND", "first_name", "David")])
        with self.assertRaises(ValidationError):
            editor_rules([legacy], ContentType.objects.get_for_model(self.CountryModel))

    def test_unconditional_legacy_and_empty_or(self):
        """UC: Restore all-rows and no-rows rules. Expected Result: Empty AND and OR remain distinct."""
        entries = [{"rule": {"conditions": [{"field": "__all__"}]}, "permissions": []},
                   {"rule": {"connector": "OR", "conditions": []}, "permissions": []}]
        result = editor_rules(entries, self.content_type)
        self.assertEqual([row["rule"] for row in result], [{"connector": "AND", "conditions": []}, {"connector": "OR", "conditions": []}])

    def test_invalid_values_and_inaccessible_fields_rejected(self):
        """UC: Bypass the editor with invalid or unauthorized conditions. Expected Result: Submission fails."""
        with self.assertRaises(ValidationError):
            editor_rules([self.entry(value="not a number")], self.content_type, user=self.admin_user)
        with self.assertRaises(PermissionDenied):
            editor_rules([self.entry()], self.content_type, user=self.normal_user)
        with self.assertRaises(ValidationError):
            editor_rules([{"rule": {}, "permissions": "view_customer"}], self.content_type)
        with self.assertRaises(ValidationError):
            editor_rules([{"rule": {"unknown": "value"}, "permissions": []}], self.content_type)

    def test_widget_bridge_and_wizard_submission(self):
        """UC: Render and submit the table. Expected Result: Scoped unified widget and canonical session payload."""
        context = _policy_builder_context(self.view, self.orchestrator)
        html = context["row_policy_filter_widget"]
        self.assertIn('bloomerp-component="unified-filter-container"', html)
        self.assertIn(f'data-scope-id="{self.content_type.pk}"', html)
        self.assertIn('data-max-groups="1"', html)
        self.assertIn('data-include-controls="false"', html)
        entries = [self.entry("OR")]
        request = RequestFactory().post("/", {"row_policy_rules_json": json.dumps(entries), "field_policies_json": "{}"})
        request.user = self.admin_user
        self.assertNotIsInstance(pcs_object_access_control(request, self.view, self.orchestrator), WizardError)
        self.assertEqual(self.state["row_policy_rules"], entries)
        request = RequestFactory().post("/", {"row_policy_rules_json": json.dumps([self.entry(value="invalid")])})
        request.user = self.admin_user
        self.assertIsInstance(pcs_object_access_control(request, self.view, self.orchestrator), WizardError)
        self.assertEqual(self.state["row_policy_rules"], entries)
