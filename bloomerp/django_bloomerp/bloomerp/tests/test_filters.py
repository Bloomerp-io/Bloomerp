from bloomerp.utils.filters import dynamic_filterset_factory
from django.db import models
from django.test import TestCase
from django.test.utils import isolate_apps
from bloomerp_tests.models import Parent, Child


class EmployeeFilterTestCase(TestCase):
    def setUp(self):
        # Create the models that will be used in the tests
        self.Parent = Parent
        self.Child = Child

        # Create test data that will be used across all tests
        self.parent_1 = Parent.objects.create(name="Foo", age=30, is_active=True)
        self.parent_2 = Parent.objects.create(name="Bar", age=40, is_active=False)

        self.child_1 = Child.objects.create(name="John", age=10, parent=self.parent_1, date="2021-01-01")
        self.child_2 = Child.objects.create(name="Jane", age=20, parent=self.parent_2, date="2021-01-02")
        self.child_3 = Child.objects.create(name="Jack", age=30, parent=self.parent_1, date="2021-01-03")

        # Create the filters that will be used in the tests
        self.ParentFilter = dynamic_filterset_factory(self.Parent)
        self.ChildFilter = dynamic_filterset_factory(self.Child)

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
