from datetime import date, datetime, time
from decimal import Decimal
from unittest.mock import patch
import uuid

from django.db import models
from django.utils import timezone

from bloomerp.field_types.types import FieldType
from bloomerp.model_fields.week_field import WeekField
from bloomerp.tests.base import BaseBloomerpModelTestCase
from bloomerp.tests.utils.dynamic_models import create_test_models
from bloomerp.utils.filters import dynamic_filterset_factory, filter_model


class TestFilterUtil(BaseBloomerpModelTestCase):
    auto_create_customers = False
    auto_create_users = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        models_by_name = create_test_models(
            app_label="bloomerp",
            model_defs={
                "FilterTag": {
                    "name": models.CharField(max_length=100),
                    "__str__": lambda self: self.name,
                },
                "FilterPrimary": {
                    "char_field": models.CharField(max_length=100, null=True, blank=True),
                    "text_field": models.TextField(null=True, blank=True),
                    "integer_field": models.IntegerField(null=True, blank=True),
                    "decimal_field": models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True),
                    "date_field": models.DateField(null=True, blank=True),
                    "datetime_field": models.DateTimeField(null=True, blank=True),
                    "time_field": models.TimeField(null=True, blank=True),
                    "boolean_field": models.BooleanField(null=True, blank=True),
                    "uuid_field": models.UUIDField(default=uuid.uuid4, null=True, blank=True),
                    "week_field": WeekField(null=True, blank=True),
                    "foreign_key_field": models.ForeignKey(
                        "FilterTag",
                        on_delete=models.SET_NULL,
                        null=True,
                        blank=True,
                        related_name="primary_records",
                    ),
                    "many_to_many_field": models.ManyToManyField(
                        "FilterTag",
                        blank=True,
                        related_name="many_primary_records",
                    ),
                },
                "FilterLine": {
                    "primary": models.ForeignKey(
                        "FilterPrimary",
                        on_delete=models.CASCADE,
                        related_name="lines",
                    ),
                    "description": models.CharField(max_length=100, blank=True),
                    "week": models.IntegerField(null=True, blank=True),
                },
            },
            use_bloomerp_base=True,
        )
        cls.TagModel = models_by_name["FilterTag"]
        cls.PrimaryModel = models_by_name["FilterPrimary"]
        cls.LineModel = models_by_name["FilterLine"]

    def setUp(self):
        super().setUp()
        self.PrimaryModel.objects.all().delete()
        self.TagModel.objects.all().delete()
        self.LineModel.objects.all().delete()

    def create_primary(self, **kwargs):
        defaults = {
            "char_field": "Alpha",
            "text_field": "The quick brown fox",
            "integer_field": 10,
            "decimal_field": Decimal("10.50"),
            "date_field": date(2026, 5, 18),
            "datetime_field": timezone.make_aware(
                datetime(2026, 5, 18, 9, 0, 0),
                timezone.get_current_timezone(),
            ),
            "time_field": time(9, 30),
            "boolean_field": True,
            "week_field": "2026-W21",
        }
        defaults.update(kwargs)
        return self.PrimaryModel.objects.create(**defaults)

    def assert_filtered_ids(self, filters: dict, expected_ids: list[int]):
        filtered_qs = filter_model(self.PrimaryModel, filters)
        self.assertCountEqual(filtered_qs.values_list("id", flat=True), expected_ids)

    def expected_filter_names(self, field_name: str, field_type: FieldType) -> set[str]:
        names = set()
        for lookup in field_type.lookups:
            if not lookup.value.filter_class_funcs:
                continue
            for alias in lookup.value.aliases:
                names.add(f"{field_name}{alias}")
        return names

    def test_filterset_generates_filters_from_field_type_lookups(self):
        FilterSet = dynamic_filterset_factory(self.PrimaryModel)

        field_expectations = {
            "char_field": FieldType.CHAR_FIELD,
            "text_field": FieldType.TEXT_FIELD,
            "integer_field": FieldType.INTEGER_FIELD,
            "decimal_field": FieldType.DECIMAL_FIELD,
            "date_field": FieldType.DATE_FIELD,
            "datetime_field": FieldType.DATE_TIME_FIELD,
            "time_field": FieldType.TIME_FIELD,
            "boolean_field": FieldType.BOOLEAN_FIELD,
            "uuid_field": FieldType.UUID_FIELD,
            "week_field": FieldType.WEEK_FIELD,
            "foreign_key_field": FieldType.FOREIGN_KEY,
            "many_to_many_field": FieldType.MANY_TO_MANY_FIELD,
            "lines": FieldType.ONE_TO_MANY_FIELD,
        }

        for field_name, field_type in field_expectations.items():
            with self.subTest(field_name=field_name):
                self.assertTrue(
                    self.expected_filter_names(field_name, field_type).issubset(FilterSet.base_filters.keys())
                )

        self.assertNotIn("time_field__today", FilterSet.base_filters)
        self.assertNotIn("foreign_key_field__foreign_advanced", FilterSet.base_filters)

    def test_text_lookup_filters_use_declared_aliases(self):
        alpha = self.create_primary(char_field="Alpha")
        beta = self.create_primary(char_field="Beta")
        alphabet = self.create_primary(char_field="alphabet")

        self.assert_filtered_ids({"char_field__equals": "Alpha"}, [alpha.id])
        self.assert_filtered_ids({"char_field__iexact": "alpha"}, [alpha.id])
        self.assert_filtered_ids({"char_field__icontains": "alph"}, [alpha.id, alphabet.id])
        self.assert_filtered_ids({"char_field__contains": "alph"}, [alpha.id, alphabet.id])
        self.assert_filtered_ids({"char_field__startswith": "Al"}, [alpha.id, alphabet.id])
        self.assert_filtered_ids({"char_field__endswith": "ta"}, [beta.id])
        self.assert_filtered_ids({"char_field__in": "Alpha,Beta"}, [alpha.id, beta.id])
        self.assert_filtered_ids({"char_field__ne": "Alpha"}, [beta.id, alphabet.id])
        self.assert_filtered_ids({"char_field__not_equals": "Alpha"}, [beta.id, alphabet.id])

    def test_numeric_lookup_filters_use_declared_aliases(self):
        small = self.create_primary(integer_field=5)
        medium = self.create_primary(integer_field=10)
        large = self.create_primary(integer_field=15)

        self.assert_filtered_ids({"integer_field__equals": "10"}, [medium.id])
        self.assert_filtered_ids({"integer_field__gt": "10"}, [large.id])
        self.assert_filtered_ids({"integer_field__gte": "10"}, [medium.id, large.id])
        self.assert_filtered_ids({"integer_field__lt": "10"}, [small.id])
        self.assert_filtered_ids({"integer_field__lte": "10"}, [small.id, medium.id])
        self.assert_filtered_ids({"integer_field__in": "5,15"}, [small.id, large.id])
        self.assert_filtered_ids({"integer_field__ne": "10"}, [small.id, large.id])

    @patch("bloomerp.field_types.lookups.timezone.localdate", return_value=date(2026, 5, 18))
    def test_date_lookup_filters_use_declared_aliases(self, _mock_localdate):
        monday = self.create_primary(date_field=date(2026, 5, 18))
        sunday = self.create_primary(date_field=date(2026, 5, 24))
        previous_month = self.create_primary(date_field=date(2026, 4, 30))

        self.assert_filtered_ids({"date_field__today": "true"}, [monday.id])
        self.assert_filtered_ids({"date_field__this_week": "true"}, [monday.id, sunday.id])
        self.assert_filtered_ids({"date_field__last_month": "true"}, [previous_month.id])
        self.assert_filtered_ids({"date_field__year": "2026"}, [monday.id, sunday.id, previous_month.id])
        self.assert_filtered_ids({"date_field__month": "5"}, [monday.id, sunday.id])
        self.assert_filtered_ids({"date_field__day": "18"}, [monday.id])
        self.assert_filtered_ids({"date_field__week": "21"}, [monday.id, sunday.id])
        self.assert_filtered_ids({"date_field__day_of_week": "0"}, [monday.id])
        self.assert_filtered_ids({"date_field__day_of_week_in": "0,6"}, [monday.id, sunday.id])
        self.assert_filtered_ids({"date_field__ne": "2026-05-18"}, [sunday.id, previous_month.id])

    def test_time_lookup_filters_do_not_include_date_relative_lookups(self):
        morning = self.create_primary(time_field=time(9, 30))
        afternoon = self.create_primary(time_field=time(15, 0))

        self.assert_filtered_ids({"time_field__equals": "09:30"}, [morning.id])
        self.assert_filtered_ids({"time_field__gt": "12:00"}, [afternoon.id])
        self.assert_filtered_ids({"time_field__ne": "09:30"}, [afternoon.id])

    def test_boolean_and_uuid_filters_use_declared_aliases(self):
        true_record = self.create_primary(boolean_field=True, uuid_field=uuid.uuid4())
        false_record = self.create_primary(boolean_field=False, uuid_field=uuid.uuid4())
        null_record = self.create_primary(boolean_field=None, uuid_field=None)

        self.assert_filtered_ids({"boolean_field__equals": "true"}, [true_record.id])
        self.assert_filtered_ids({"boolean_field__exact": "false"}, [false_record.id])
        self.assert_filtered_ids({"boolean_field__isnull": "true"}, [null_record.id])
        self.assert_filtered_ids(
            {"uuid_field__in": f"{true_record.uuid_field},{false_record.uuid_field}"},
            [true_record.id, false_record.id],
        )

    def test_foreign_key_filters_keep_relation_specific_behavior(self):
        backend = self.TagModel.objects.create(name="Backend")
        frontend = self.TagModel.objects.create(name="Frontend")
        backend_record = self.create_primary(foreign_key_field=backend)
        frontend_record = self.create_primary(foreign_key_field=frontend)
        null_record = self.create_primary(foreign_key_field=None)

        self.assert_filtered_ids({"foreign_key_field": str(backend.id)}, [backend_record.id])
        self.assert_filtered_ids({"foreign_key_field__equals": str(frontend.id)}, [frontend_record.id])
        self.assert_filtered_ids(
            {"foreign_key_field__in": f"{backend.id},{frontend.id}"},
            [backend_record.id, frontend_record.id],
        )
        self.assert_filtered_ids({"foreign_key_field__isnull": "true"}, [null_record.id])
        self.assert_filtered_ids({"foreign_key_field__name__icontains": "back"}, [backend_record.id])

    def test_many_to_many_filters_keep_relation_specific_behavior(self):
        backend = self.TagModel.objects.create(name="Backend")
        frontend = self.TagModel.objects.create(name="Frontend")
        backend_record = self.create_primary()
        backend_record.many_to_many_field.add(backend)
        frontend_record = self.create_primary()
        frontend_record.many_to_many_field.add(frontend)
        both_record = self.create_primary()
        both_record.many_to_many_field.add(backend, frontend)

        self.assert_filtered_ids({"many_to_many_field": [str(backend.id)]}, [backend_record.id, both_record.id])
        self.assert_filtered_ids({"many_to_many_field__equals": [str(frontend.id)]}, [frontend_record.id, both_record.id])
        self.assert_filtered_ids({"many_to_many_field__in": [str(backend.id)]}, [backend_record.id, both_record.id])
        self.assert_filtered_ids({"many_to_many_field__name__icontains": "front"}, [frontend_record.id, both_record.id])

    def test_one_to_many_count_filters_use_declared_aliases(self):
        no_lines = self.create_primary()
        one_line = self.create_primary()
        two_lines = self.create_primary()

        self.LineModel.objects.create(primary=one_line, description="One")
        self.LineModel.objects.create(primary=two_lines, description="Two A")
        self.LineModel.objects.create(primary=two_lines, description="Two B")

        self.assert_filtered_ids({"lines__count": "1"}, [one_line.id])
        self.assert_filtered_ids({"lines__count_equals": "2"}, [two_lines.id])
        self.assert_filtered_ids({"lines__count__gt": "1"}, [two_lines.id])
        self.assert_filtered_ids({"lines__count_greater_than": "0"}, [one_line.id, two_lines.id])
        self.assert_filtered_ids({"lines__count__gte": "1"}, [one_line.id, two_lines.id])
        self.assert_filtered_ids({"lines__count__lt": "1"}, [no_lines.id])
        self.assert_filtered_ids({"lines__count__lte": "1"}, [no_lines.id, one_line.id])

    def test_one_to_many_advanced_related_field_filters(self):
        week_one = self.create_primary()
        week_two = self.create_primary()
        duplicate_matches = self.create_primary()

        self.LineModel.objects.create(primary=week_one, description="Billable", week=1)
        self.LineModel.objects.create(primary=week_two, description="Billable", week=2)
        self.LineModel.objects.create(primary=duplicate_matches, description="Billable A", week=1)
        self.LineModel.objects.create(primary=duplicate_matches, description="Billable B", week=1)

        self.assert_filtered_ids({"lines__week__equals": "1"}, [week_one.id, duplicate_matches.id])
        self.assert_filtered_ids({"lines__week__gt": "1"}, [week_two.id])
        self.assert_filtered_ids({"lines__description__icontains": "billable"}, [
            week_one.id,
            week_two.id,
            duplicate_matches.id,
        ])
