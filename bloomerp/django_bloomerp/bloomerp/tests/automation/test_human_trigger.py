from django.test import SimpleTestCase

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

        self.assertEqual(schema.kind, "object")
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

        self.assertEqual(schema.kind, "none")
        self.assertEqual(schema.fields, [])