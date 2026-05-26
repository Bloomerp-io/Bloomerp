from django.test import SimpleTestCase

from bloomerp.field_types import NULL_FIELD_OPTION


class FieldOptionTestCase(SimpleTestCase):
    def test_field_options_can_be_used_in_sets(self):
        self.assertEqual({NULL_FIELD_OPTION}, {NULL_FIELD_OPTION})
