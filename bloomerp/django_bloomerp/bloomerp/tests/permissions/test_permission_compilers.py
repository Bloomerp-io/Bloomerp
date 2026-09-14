from django.test import SimpleTestCase
from bloomerp.lookups import builtins as lookups


class TestPermissionCompilers(SimpleTestCase):

    def test_every_evaluable_lookup_has_a_python_evaluator(self):
        """
        This test checks whether every evaluable lookup has a python compiler
        """
        without_evaluator = {
            lookup
            for lookup in lookups.BUILTIN_LOOKUPS
            if lookup.python_evaluator is None
        }
        self.assertEqual(
            without_evaluator,
            {lookup for lookup in lookups.BUILTIN_LOOKUPS if lookup.nested},
        )
