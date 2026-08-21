from django.test import SimpleTestCase

from bloomerp.field_types.lookups import Lookup
from bloomerp.permissions.compilers import (
    BasePermissionCompiler,
    DjangoQPermissionCompiler,
    PythonPermissionCompiler,
    SqlPermissionCompiler,
)


class TestPermissionCompilers(SimpleTestCase):
    def test_concrete_compilers_share_the_base_compiler(self):
        self.assertTrue(issubclass(DjangoQPermissionCompiler, BasePermissionCompiler))
        self.assertTrue(issubclass(PythonPermissionCompiler, BasePermissionCompiler))
        self.assertTrue(issubclass(SqlPermissionCompiler, BasePermissionCompiler))

    def test_every_evaluable_lookup_has_a_python_evaluator(self):
        without_evaluator = {
            lookup
            for lookup in Lookup
            if lookup.value.python_eval is None
        }
        self.assertEqual(
            without_evaluator,
            {
                Lookup.ADDRESS_ADVANCED,
                Lookup.FOREIGN_ADVANCED,
                Lookup.ONE_TO_MANY_ADVANCED,
            },
        )
