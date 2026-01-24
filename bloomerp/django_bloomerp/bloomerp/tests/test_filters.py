from bloomerp.utils.filters import dynamic_filterset_factory
from django.test import TestCase
from django.test.utils import override_settings
from django.conf import settings


@override_settings(
    INSTALLED_APPS=[*settings.INSTALLED_APPS, "bloomerp_tests"],
    MIGRATION_MODULES={"bloomerp_tests": None},
)
class EmployeeFilterTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        from bloomerp_tests.models import Parent, Child

        cls.Parent = Parent
        cls.Child = Child

        cls.parent_1 = Parent.objects.create(name="Foo", age=30, is_active=True)
        cls.parent_2 = Parent.objects.create(name="Bar", age=40, is_active=False)

        cls.child_1 = Child.objects.create(name="John", age=10, parent=cls.parent_1, date="2021-01-01")
        cls.child_2 = Child.objects.create(name="Jane", age=20, parent=cls.parent_2, date="2021-01-02")
        cls.child_3 = Child.objects.create(name="Jack", age=30, parent=cls.parent_1, date="2021-01-03")

        cls.ParentFilter = dynamic_filterset_factory(cls.Parent)
        cls.ChildFilter = dynamic_filterset_factory(cls.Child)


    def test_char_field_equals(self):
        # 1. char field filter with exact lookup
        parent_filter = self.ParentFilter(data={'name':'Foo'}, queryset=self.Parent.objects.all())
        parent_filter_qs = parent_filter.qs
        self.assertEqual(parent_filter_qs.count(), 1)


        # 2. char field filter with iexact lookup
        parent_filter = self.ParentFilter(data={'name__iexact':'foo'}, queryset=self.Parent.objects.all())
        parent_filter_qs = parent_filter.qs
        self.assertEqual(parent_filter_qs.count(), 1)
        
    def test_char_field_contains(self):
        parent_filter = self.ParentFilter(data={'name__icontains':'FOO'}, queryset=self.Parent.objects.all())
        parent_filter_qs = parent_filter.qs
        self.assertEqual(parent_filter_qs.count(), 1)

    def test_char_field_startswith(self):
        # 1. char field filter with startswith lookup (case-sensitive)
        parent_filter = self.ParentFilter(data={'name__startswith':'F'}, queryset=self.Parent.objects.all())
        parent_filter_qs = parent_filter.qs
        self.assertEqual(parent_filter_qs.count(), 1)


    def test_char_field_endswith(self):
        # 1. char field filter with endswith lookup (case-sensitive)
        parent_filter = self.ParentFilter(data={'name__endswith':'o'}, queryset=self.Parent.objects.all())
        parent_filter_qs = parent_filter.qs
        self.assertEqual(parent_filter_qs.count(), 1)

    def test_foreign_key(self):
        # 1. foreign key filter with exact lookup
        child_filter = self.ChildFilter(data={'parent':self.parent_1.pk}, queryset=self.Child.objects.all())
        child_filter_qs = child_filter.qs
        self.assertEqual(child_filter_qs.count(), 2)


    def test_foreign_key_char_field_equals(self):
        # 1. foreign key char field filter with exact lookup
        child_filter = self.ChildFilter(data={'parent__name':'Foo'}, queryset=self.Child.objects.all())
        child_filter_qs = child_filter.qs
        self.assertEqual(child_filter_qs.count(), 2)

    def test_foreign_key_char_field_contains(self):
        # 1. foreign key char field filter with contains lookup
        child_filter = self.ChildFilter(data={'parent__name__contains':'Fo'}, queryset=self.Child.objects.all())
        child_filter_qs = child_filter.qs
        self.assertEqual(child_filter_qs.count(), 2)

    
    def test_foreign_key_date_field_equals(self):
        # 1. foreign key date field filter with exact lookup
        child_filter = self.ChildFilter(data={'parent__date':'2021-01-01'}, queryset=self.Child.objects.all())
        child_filter_qs = child_filter.qs
        self.assertEqual(child_filter_qs.count(), 1)
