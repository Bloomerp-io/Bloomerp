from django.test import SimpleTestCase

from bloomerp.automation.flows.for_each import ForEachExecutor
from bloomerp.automation.schema import WorkflowIOFlowKind, WorkflowValueType, WorkflowIOSchema, WorkflowValueField
from bloomerp.automation.triggers.human_trigger import HumanTrigger


class TestHumanTriggerOutputSchema(SimpleTestCase):
    def test_get_output_schema_recurses_through_nested_json(self):
        schema = HumanTrigger.get_output_schema(
            {
                "parameters": {
                    "data": {
                        "user": {
                            "name": "Ada",
                            "age": 37,
                            "active": True,
                            "addresses": [
                                {
                                    "city": "London",
                                    "postcode": "N1",
                                }
                            ],
                        }
                    }
                }
            }
        )

        self.assertEqual(schema.value_type, WorkflowValueType.OBJECT)
        self.assertEqual(schema.fields[0].path, "user")
        self.assertEqual(schema.fields[0].value_type, "object")

        user_children = {field.path: field for field in schema.fields[0].children}
        self.assertEqual(user_children["user.name"].value_type, "string")
        self.assertEqual(user_children["user.age"].value_type, "number")
        self.assertEqual(user_children["user.active"].value_type, "boolean")
        self.assertEqual(user_children["user.addresses"].value_type, "list")

        address_children = {field.path: field for field in user_children["user.addresses"].children}
        self.assertIn("user.addresses.0.city", address_children)
        self.assertIn("user.addresses.0.postcode", address_children)

    def test_get_output_schema_returns_none_when_data_missing(self):
        schema = HumanTrigger.get_output_schema({"parameters": {}})

        self.assertEqual(schema.value_type, WorkflowValueType.NONE)
        self.assertEqual(schema.fields, [])

    def test_get_output_schema_supports_scalar_json_root(self):
        schema = HumanTrigger.get_output_schema({"parameters": {"data": "hello"}})

        self.assertEqual(schema.value_type, WorkflowValueType.ANY)
        self.assertEqual(schema.fields[0].path, "input")
        self.assertEqual(schema.fields[0].value_type, "string")
        self.assertEqual(schema.fields[0].template_token, "{{ input }}")

    def test_for_each_schema_uses_object_value_type_with_fanout_flow_kind(self):
        schema = ForEachExecutor.get_output_schema(
            input_schema=WorkflowIOSchema(
                value_type=WorkflowValueType.LIST,
                label="Employees",
                fields=[
                    WorkflowValueField("input", "Employees", "list"),
                    WorkflowValueField("input.0.email", "Email", "string"),
                ],
            )
        )

        self.assertEqual(schema.value_type, WorkflowValueType.OBJECT)
        self.assertEqual(schema.flow_kind, WorkflowIOFlowKind.FANOUT)
        self.assertIn("input.item.email", [field.path for field in schema.fields[0].children])
