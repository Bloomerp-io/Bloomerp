from datetime import date, datetime
from unittest.mock import patch

from django.db import models
from django.utils import timezone

from bloomerp.models.project_management.todo import Todo
from bloomerp.models.project_management.todo_label import TodoLabel
from bloomerp.tests.base import BaseBloomerpTestCaseWithModels
from bloomerp.tests.utils.dynamic_models import create_test_models
from bloomerp.filters.manager import ModelFilterManager


class TestFilterModelRegressions(BaseBloomerpTestCaseWithModels):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        models_by_name = create_test_models(
            app_label="bloomerp",
            model_defs={
                "FilterRegressionEvent": {
                    "starts_at": models.DateTimeField(),
                    "starts_on": models.DateField(),
                    "is_active": models.BooleanField(default=False),
                },
                "FilterRegressionEmployee": {
                    "name": models.CharField(max_length=100),
                    "manager": models.ForeignKey(
                        "self",
                        null=True,
                        blank=True,
                        on_delete=models.SET_NULL,
                        related_name="direct_reports",
                    ),
                },
            },
            use_bloomerp_base=True,
        )
        cls.EventModel = models_by_name["FilterRegressionEvent"]
        cls.EmployeeModel = models_by_name["FilterRegressionEmployee"]

    def create_event(self, starts_on, hour=9, **kwargs):
        return self.EventModel.objects.create(
            starts_on=starts_on,
            starts_at=timezone.make_aware(
                datetime.combine(starts_on, datetime.min.time()).replace(hour=hour),
                timezone.get_current_timezone(),
            ),
            **kwargs,
        )

    def assert_filtered_ids(self, model, filters, expected_ids):
        self.assertCountEqual(
            ModelFilterManager(model).filter(filters, queryset=model.objects.all()).values_list("id", flat=True),
            expected_ids,
        )

    def test_many_to_many_labels_filter_by_id(self):
        backend = TodoLabel.objects.create(name="Backend", color="#000000")
        frontend = TodoLabel.objects.create(name="Frontend", color="#ffffff")
        backend_todo = Todo.objects.create(title="Fix labels filter")
        backend_todo.labels.add(backend)
        frontend_todo = Todo.objects.create(title="Polish filters UI")
        frontend_todo.labels.add(frontend)
        both_todo = Todo.objects.create(title="Ship both")
        both_todo.labels.add(backend, frontend)

        self.assert_filtered_ids(
            Todo,
            {"labels": [str(backend.id)]},
            [backend_todo.id, both_todo.id],
        )

    def test_many_to_many_labels_support_exact_lookup_alias(self):
        backend = TodoLabel.objects.create(name="Backend", color="#000000")
        frontend = TodoLabel.objects.create(name="Frontend", color="#ffffff")
        backend_todo = Todo.objects.create(title="Fix labels filter")
        backend_todo.labels.add(backend)
        frontend_todo = Todo.objects.create(title="Polish filters UI")
        frontend_todo.labels.add(frontend)

        self.assert_filtered_ids(
            Todo,
            {"labels__exact": [str(backend.id)]},
            [backend_todo.id],
        )

    @patch("bloomerp.field_types.lookups.timezone.localdate", return_value=date(2026, 5, 18))
    def test_date_relative_lookups(self, _mock_localdate):
        today = self.create_event(date(2026, 5, 18))
        last_month = self.create_event(date(2026, 4, 5))
        last_year = self.create_event(date(2025, 7, 4))

        self.assert_filtered_ids(self.EventModel, {"starts_on__today": "true"}, [today.id])
        self.assert_filtered_ids(self.EventModel, {"starts_on__last_month": "true"}, [last_month.id])
        self.assert_filtered_ids(self.EventModel, {"starts_on__last_year": "true"}, [last_year.id])

    @patch("bloomerp.field_types.lookups.timezone.localdate", return_value=date(2026, 5, 18))
    def test_datetime_this_week_lookup(self, _mock_localdate):
        in_week = self.create_event(date(2026, 5, 18))
        self.create_event(date(2026, 5, 10), hour=18)

        self.assert_filtered_ids(
            self.EventModel,
            {"starts_at__this_week": "true"},
            [in_week.id],
        )

    def test_boolean_exact_lookup(self):
        active = self.create_event(date(2026, 5, 18), is_active=True)
        inactive = self.create_event(date(2026, 5, 19), is_active=False)

        self.assert_filtered_ids(self.EventModel, {"is_active__exact": "true"}, [active.id])
        self.assert_filtered_ids(self.EventModel, {"is_active__exact": "false"}, [inactive.id])

    def test_unknown_filter_field_is_ignored(self):
        event = self.create_event(date(2026, 5, 18))

        self.assert_filtered_ids(
            self.EventModel,
            {"address_0__contains": "Brussels"},
            [event.id],
        )

    def test_level_five_relationship_nesting(self):
        ceo = self.EmployeeModel.objects.create(name="CEO")
        level_1 = self.EmployeeModel.objects.create(name="Level 1", manager=ceo)
        level_2 = self.EmployeeModel.objects.create(name="Level 2", manager=level_1)
        level_3 = self.EmployeeModel.objects.create(name="Level 3", manager=level_2)
        level_4 = self.EmployeeModel.objects.create(name="Level 4", manager=level_3)
        level_5 = self.EmployeeModel.objects.create(name="Level 5", manager=level_4)
        self.EmployeeModel.objects.create(name="Unrelated")

        self.assert_filtered_ids(
            self.EmployeeModel,
            {"manager__manager__manager__manager__manager": str(ceo.id)},
            [level_5.id],
        )

    def test_day_of_week_lookup_uses_monday_zero(self):
        monday = self.create_event(date(2026, 5, 18))
        sunday = self.create_event(date(2026, 5, 24))

        self.assert_filtered_ids(self.EventModel, {"starts_on__day_of_week": "0"}, [monday.id])
        self.assert_filtered_ids(self.EventModel, {"starts_on__day_of_week": "6"}, [sunday.id])
