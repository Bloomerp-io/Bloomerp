from datetime import date, datetime
from unittest.mock import patch

from bloomerp.tests.base import BaseBloomerpModelTestCase
from django.urls import reverse
from django.utils import timezone

from bloomerp.models import ApplicationField
from bloomerp.models.project_management.todo import Todo
from bloomerp.models.project_management.todo_label import TodoLabel
from bloomerp.utils.filters import filter_model
from bloomerp.tests.utils.dynamic_models import create_test_models
from django.db import models

# TODO: Review tests thoroughly

class TestFilterComponent(BaseBloomerpModelTestCase):
    create_foreign_models = True

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.EventModel = create_test_models(
            app_label="bloomerp",
            model_defs={
                "FilterEvent": {
                    "starts_at": models.DateTimeField(),
                    "starts_on": models.DateField(),
                }
            },
            use_bloomerp_base=True,
        )["FilterEvent"]

    def test_value_input_renders_full_width_text_input_for_plain_char_field(self):
        application_field = ApplicationField.get_by_field(self.CustomerModel, "first_name")
        url = reverse(
            "components_filters_value_input",
            kwargs={
                "content_type_id": application_field.content_type_id,
                "application_field_id": application_field.id,
            },
        )

        response = self.client.get(url, {"lookup_value": "equals"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<input', html=False)
        self.assertContains(response, 'class="input w-full"', html=False)

    def test_value_input_renders_select_for_choice_backed_application_field(self):
        application_field = ApplicationField.get_by_field(self.CustomerModel, "first_name")
        application_field.meta = {
            "choices": [
                ["full_time", "Full Time"],
                ["part_time", "Part Time"],
            ]
        }
        application_field.save(update_fields=["meta"])

        url = reverse(
            "components_filters_value_input",
            kwargs={
                "content_type_id": application_field.content_type_id,
                "application_field_id": application_field.id,
            },
        )

        response = self.client.get(url, {"lookup_value": "equals"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<select', html=False)
        self.assertContains(response, 'class="select w-full"', html=False)
        self.assertContains(response, 'Full Time', html=False)

    def test_value_input_renders_boolean_select_for_is_null_lookup(self):
        application_field = ApplicationField.get_by_field(self.CustomerModel, "first_name")
        url = reverse(
            "components_filters_value_input",
            kwargs={
                "content_type_id": application_field.content_type_id,
                "application_field_id": application_field.id,
            },
        )

        response = self.client.get(url, {"lookup_value": "is_null"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<select', html=False)
        self.assertContains(response, 'class="select w-full"', html=False)
        self.assertContains(response, '<option value="true">True</option>', html=False)
        self.assertContains(response, '<option value="false">False</option>', html=False)

    def test_value_input_renders_datetime_local_input_for_datetime_field(self):
        application_field = ApplicationField.get_by_field(self.EventModel, "starts_at")
        url = reverse(
            "components_filters_value_input",
            kwargs={
                "content_type_id": application_field.content_type_id,
                "application_field_id": application_field.id,
            },
        )

        response = self.client.get(url, {"lookup_value": "equals"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<input', html=False)
        self.assertContains(response, 'type="datetime-local"', html=False)
        self.assertContains(response, 'class="input w-full"', html=False)

    def test_lookup_operators_include_is_null_for_foreign_key_fields(self):
        application_field = ApplicationField.get_by_field(self.CustomerModel, "country")
        url = reverse(
            "components_filters_lookup_operators",
            kwargs={
                "content_type_id": application_field.content_type_id,
                "application_field_id": application_field.id,
            },
        )

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="is_null"', html=False)

    def test_lookup_operators_include_relative_date_options_for_date_fields(self):
        application_field = ApplicationField.get_by_field(self.EventModel, "starts_on")
        url = reverse(
            "components_filters_lookup_operators",
            kwargs={
                "content_type_id": application_field.content_type_id,
                "application_field_id": application_field.id,
            },
        )

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="today"', html=False)
        self.assertContains(response, 'value="this_week"', html=False)
        self.assertContains(response, 'value="last_month"', html=False)
        self.assertContains(response, 'value="this_quarter"', html=False)
        self.assertContains(response, 'value="this_year"', html=False)
        self.assertContains(response, 'value="year"', html=False)
        self.assertContains(response, 'value="month"', html=False)
        self.assertContains(response, 'value="day"', html=False)
        self.assertContains(response, 'value="week"', html=False)

    def test_value_input_renders_hidden_input_for_relative_date_lookup(self):
        application_field = ApplicationField.get_by_field(self.EventModel, "starts_on")
        url = reverse(
            "components_filters_value_input",
            kwargs={
                "content_type_id": application_field.content_type_id,
                "application_field_id": application_field.id,
            },
        )

        response = self.client.get(url, {"lookup_value": "this_week"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'type="hidden"', html=False)
        self.assertContains(response, 'name="starts_on"', html=False)
        self.assertContains(response, 'value="true"', html=False)
        self.assertContains(response, "Uses the current week automatically.", html=False)

    def test_value_input_renders_number_input_for_year_lookup(self):
        application_field = ApplicationField.get_by_field(self.EventModel, "starts_on")
        url = reverse(
            "components_filters_value_input",
            kwargs={
                "content_type_id": application_field.content_type_id,
                "application_field_id": application_field.id,
            },
        )

        response = self.client.get(url, {"lookup_value": "year"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'type="number"', html=False)
        self.assertContains(response, 'min="1"', html=False)

    def test_value_input_renders_month_select_for_month_lookup(self):
        application_field = ApplicationField.get_by_field(self.EventModel, "starts_on")
        url = reverse(
            "components_filters_value_input",
            kwargs={
                "content_type_id": application_field.content_type_id,
                "application_field_id": application_field.id,
            },
        )

        response = self.client.get(url, {"lookup_value": "month"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<select', html=False)
        self.assertContains(response, 'class="select w-full"', html=False)
        self.assertContains(response, '<option value="1">January</option>', html=False)
        self.assertContains(response, '<option value="12">December</option>', html=False)

    def test_value_input_renders_bounded_number_input_for_day_lookup(self):
        application_field = ApplicationField.get_by_field(self.EventModel, "starts_on")
        url = reverse(
            "components_filters_value_input",
            kwargs={
                "content_type_id": application_field.content_type_id,
                "application_field_id": application_field.id,
            },
        )

        response = self.client.get(url, {"lookup_value": "day"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'type="number"', html=False)
        self.assertContains(response, 'min="1"', html=False)
        self.assertContains(response, 'max="31"', html=False)

    def test_value_input_renders_bounded_number_input_for_week_lookup(self):
        application_field = ApplicationField.get_by_field(self.EventModel, "starts_on")
        url = reverse(
            "components_filters_value_input",
            kwargs={
                "content_type_id": application_field.content_type_id,
                "application_field_id": application_field.id,
            },
        )

        response = self.client.get(url, {"lookup_value": "week"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'type="number"', html=False)
        self.assertContains(response, 'min="1"', html=False)
        self.assertContains(response, 'max="53"', html=False)

    def test_filter_model_filters_many_to_many_labels_by_id(self):
        backend_label = TodoLabel.objects.create(name="Backend", color="#000000")
        frontend_label = TodoLabel.objects.create(name="Frontend", color="#ffffff")

        todo_with_backend = Todo.objects.create(title="Fix labels filter")
        todo_with_backend.labels.add(backend_label)

        todo_with_frontend = Todo.objects.create(title="Polish filters UI")
        todo_with_frontend.labels.add(frontend_label)

        todo_with_both = Todo.objects.create(title="Ship both")
        todo_with_both.labels.add(backend_label, frontend_label)

        filtered_qs = filter_model(Todo, {"labels": [str(backend_label.id)]})

        self.assertCountEqual(
            filtered_qs.values_list("id", flat=True),
            [todo_with_backend.id, todo_with_both.id],
        )

    def test_filter_model_filters_many_to_many_labels_with_exact_lookup_alias(self):
        backend_label = TodoLabel.objects.create(name="Backend", color="#000000")
        frontend_label = TodoLabel.objects.create(name="Frontend", color="#ffffff")

        todo_with_backend = Todo.objects.create(title="Fix labels filter")
        todo_with_backend.labels.add(backend_label)

        todo_with_frontend = Todo.objects.create(title="Polish filters UI")
        todo_with_frontend.labels.add(frontend_label)

        filtered_qs = filter_model(Todo, {"labels__exact": [str(backend_label.id)]})

        self.assertCountEqual(
            filtered_qs.values_list("id", flat=True),
            [todo_with_backend.id],
        )

    @patch("bloomerp.utils.filters.timezone.localdate", return_value=date(2026, 5, 18))
    def test_filter_model_filters_date_fields_for_today_lookup(self, _mock_localdate):
        current_timezone = timezone.get_current_timezone()
        today_event = self.EventModel.objects.create(
            starts_on=date(2026, 5, 18),
            starts_at=timezone.make_aware(datetime(2026, 5, 18, 9, 0, 0), current_timezone),
        )
        yesterday_event = self.EventModel.objects.create(
            starts_on=date(2026, 5, 17),
            starts_at=timezone.make_aware(datetime(2026, 5, 17, 9, 0, 0), current_timezone),
        )

        filtered_qs = filter_model(self.EventModel, {"starts_on__today": "true"})

        self.assertCountEqual(
            filtered_qs.values_list("id", flat=True),
            [today_event.id],
        )
        self.assertNotIn(yesterday_event.id, filtered_qs.values_list("id", flat=True))

    @patch("bloomerp.utils.filters.timezone.localdate", return_value=date(2026, 5, 18))
    def test_filter_model_filters_date_fields_for_last_month_lookup(self, _mock_localdate):
        current_timezone = timezone.get_current_timezone()
        april_event = self.EventModel.objects.create(
            starts_on=date(2026, 4, 5),
            starts_at=timezone.make_aware(datetime(2026, 4, 5, 9, 0, 0), current_timezone),
        )
        may_event = self.EventModel.objects.create(
            starts_on=date(2026, 5, 5),
            starts_at=timezone.make_aware(datetime(2026, 5, 5, 9, 0, 0), current_timezone),
        )

        filtered_qs = filter_model(self.EventModel, {"starts_on__last_month": "true"})

        self.assertCountEqual(
            filtered_qs.values_list("id", flat=True),
            [april_event.id],
        )
        self.assertNotIn(may_event.id, filtered_qs.values_list("id", flat=True))

    @patch("bloomerp.utils.filters.timezone.localdate", return_value=date(2026, 5, 18))
    def test_filter_model_filters_datetime_fields_for_this_week_lookup(self, _mock_localdate):
        current_timezone = timezone.get_current_timezone()
        in_week_event = self.EventModel.objects.create(
            starts_on=date(2026, 5, 18),
            starts_at=timezone.make_aware(datetime(2026, 5, 18, 9, 0, 0), current_timezone),
        )
        previous_week_event = self.EventModel.objects.create(
            starts_on=date(2026, 5, 10),
            starts_at=timezone.make_aware(datetime(2026, 5, 10, 18, 0, 0), current_timezone),
        )

        filtered_qs = filter_model(self.EventModel, {"starts_at__this_week": "true"})

        self.assertCountEqual(
            filtered_qs.values_list("id", flat=True),
            [in_week_event.id],
        )
        self.assertNotIn(previous_week_event.id, filtered_qs.values_list("id", flat=True))

    @patch("bloomerp.utils.filters.timezone.localdate", return_value=date(2026, 5, 18))
    def test_filter_model_filters_date_fields_for_last_year_lookup(self, _mock_localdate):
        current_timezone = timezone.get_current_timezone()
        last_year_event = self.EventModel.objects.create(
            starts_on=date(2025, 7, 4),
            starts_at=timezone.make_aware(datetime(2025, 7, 4, 9, 0, 0), current_timezone),
        )
        this_year_event = self.EventModel.objects.create(
            starts_on=date(2026, 2, 1),
            starts_at=timezone.make_aware(datetime(2026, 2, 1, 9, 0, 0), current_timezone),
        )

        filtered_qs = filter_model(self.EventModel, {"starts_on__last_year": "true"})

        self.assertCountEqual(
            filtered_qs.values_list("id", flat=True),
            [last_year_event.id],
        )
        self.assertNotIn(this_year_event.id, filtered_qs.values_list("id", flat=True))
