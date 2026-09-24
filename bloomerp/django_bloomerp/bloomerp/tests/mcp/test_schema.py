from django.test import SimpleTestCase
from jsonschema import Draft202012Validator
from rest_framework import serializers

from bloomerp.mcp.schema import serializer_input_schema, serializer_output_schema


class NestedSerializer(serializers.Serializer):
    enabled = serializers.BooleanField()


class ExampleSerializer(serializers.Serializer):
    name = serializers.CharField(min_length=2, max_length=50, help_text="A name.")
    operation = serializers.ChoiceField(choices=("create", "update"))
    count = serializers.IntegerField(required=False, min_value=1, default=10)
    secret = serializers.CharField(write_only=True)
    identifier = serializers.UUIDField(read_only=True)
    metadata = serializers.DictField(child=serializers.CharField(), required=False)
    nested = NestedSerializer(required=False, allow_null=True)


class SerializerSchemaTests(SimpleTestCase):
    def test_builds_input_schema(self):
        schema = serializer_input_schema(ExampleSerializer)
        Draft202012Validator.check_schema(schema)

        self.assertEqual(schema["type"], "object")
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["required"], ["name", "operation", "secret"])
        self.assertNotIn("identifier", schema["properties"])
        self.assertEqual(
            schema["properties"]["operation"],
            {"enum": ["create", "update"], "type": "string"},
        )
        self.assertEqual(schema["properties"]["name"]["minLength"], 2)
        self.assertEqual(schema["properties"]["count"]["default"], 10)
        self.assertEqual(
            schema["properties"]["metadata"]["additionalProperties"],
            {"type": "string"},
        )

    def test_builds_output_schema(self):
        schema = serializer_output_schema(ExampleSerializer)
        Draft202012Validator.check_schema(schema)

        self.assertNotIn("secret", schema["properties"])
        self.assertIn("identifier", schema["properties"])
        self.assertEqual(
            schema["properties"]["nested"]["anyOf"][1],
            {"type": "null"},
        )

    def test_rejects_non_serializer_classes(self):
        with self.assertRaisesRegex(TypeError, "DRF serializer class"):
            serializer_input_schema(object)
