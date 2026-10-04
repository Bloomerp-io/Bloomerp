"""Regression coverage for user/group selections in the agent access inline table."""

from collections.abc import Mapping
from typing import Any
from unittest.mock import patch

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import QueryDict
from django.test import TestCase

from bloomerp.form_fields.one_to_many_field import OneToManyCleanedData, OneToManyField
from bloomerp.models import ApplicationField, Initiative, Todo, TodoLabel
from bloomerp.models.agents import AIAgent, AIAgentAccess
from bloomerp.tests.base import (
    BloomerpFormFieldTestCase,
    ExpectedFormFieldException,
    FormFieldScenario,
)
from bloomerp.widgets.one_to_many_field_widget import OneToManyFieldWidget


def legacy_row_form_data(
    row: dict[str, Any], form_fields: Mapping[str, forms.Field]
) -> dict[str, Any]:
    """Reproduce the original child-form binding without changing production code."""
    return row


class AgentAccessInlineTests(BloomerpFormFieldTestCase[OneToManyField], TestCase):
    """Validate and save browser-shaped inline rows with single or multiple selections."""

    field_class = OneToManyField

    def setUp(self) -> None:
        """Prepare a real agent relation, its field metadata, and selection candidates."""
        self.agent = AIAgent.objects.create(
            name="Inline agent", provider="openai", model_identifier="example"
        )
        self.user = get_user_model().objects.create_user(username="inline-user")
        self.other = get_user_model().objects.create_user(username="inline-other")
        self.group = Group.objects.create(name="Inline team")
        self.application_field = ApplicationField.objects.create(
            content_type=ContentType.objects.get_for_model(AIAgent),
            field="access",
            field_type="OneToManyField",
            related_model=ContentType.objects.get_for_model(AIAgentAccess),
        )
        self.widget = OneToManyFieldWidget(
            attrs={"related_model": AIAgentAccess, "parent_model": AIAgent}
        )
        for name in ("name", "users", "groups"):
            ApplicationField.objects.create(
                content_type=ContentType.objects.get_for_model(AIAgentAccess),
                field=name,
                field_type=AIAgentAccess._meta.get_field(name).get_internal_type(),
            )
        self.field = OneToManyField(
            application_field=self.application_field, widget=self.widget
        )
        self.field.bind_parent(self.agent)

    def get_field_kwargs(self) -> dict[str, Any]:
        """Construct the real inline field with its related model metadata and widget."""
        return {"application_field": self.application_field, "widget": self.widget}

    def bind_scenario_parent(self, field: OneToManyField) -> None:
        """Bind standalone cleaning to the agent without saving child rows."""
        field.bind_parent(self.agent)

    def single_selection_is_clean(self, value: OneToManyCleanedData) -> bool:
        """Return list-shaped user and group identities without database mutations."""
        rows = value.serialize()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["users"], [str(self.user.pk)])
        self.assertEqual(rows[0]["groups"], [str(self.group.pk)])
        self.assertFalse(self.agent.access.exists())
        return True

    def get_test_scenarios(self) -> list[FormFieldScenario[OneToManyField]]:
        """Describe standalone cleaning while keeping full save regressions as integration tests."""
        return [
            FormFieldScenario(
                name="Single inline selections clean as lists without saving",
                constructor_kwargs=self.get_field_kwargs,
                post_construction=self.bind_scenario_parent,
                clean_value=[
                    {
                        "name": "Clean only",
                        "users": str(self.user.pk),
                        "groups": str(self.group.pk),
                    }
                ],
                clean_result_validators=self.single_selection_is_clean,
            ),
            FormFieldScenario(
                name="Unknown selected user fails field cleaning",
                constructor_kwargs=self.get_field_kwargs,
                post_construction=self.bind_scenario_parent,
                clean_value=[
                    {"name": "Invalid", "users": "invalid-user-id", "groups": ""}
                ],
                expected_exceptions=[
                    ExpectedFormFieldException("clean", ValidationError)
                ],
            ),
        ]

    def test_single_user_and_group_save_as_multiple_choice_values(self) -> None:
        """Accept one selected user/group instead of raising 'Enter a list of values'."""
        data = QueryDict(mutable=True)
        data["access__0__name"] = "Single selections"
        data.setlist("access__0__users", ["", str(self.user.pk)])
        data.setlist("access__0__groups", [str(self.group.pk)])
        cleaned = self.field.clean(self.widget.value_from_datadict(data, {}, "access"))
        cleaned.save(self.agent)
        grant = self.agent.access.get()
        self.assertEqual(list(grant.users.all()), [self.user])
        self.assertEqual(list(grant.groups.all()), [self.group])

    def test_multiple_users_and_empty_groups_remain_supported(self) -> None:
        """Keep repeated selections intact and allow optional empty group membership."""
        data = QueryDict(mutable=True)
        data["access__0__name"] = "Multiple selections"
        data.setlist("access__0__users", [str(self.user.pk), str(self.other.pk)])
        data["access__0__groups"] = ""
        cleaned = self.field.clean(self.widget.value_from_datadict(data, {}, "access"))
        cleaned.save(self.agent)
        grant = self.agent.access.get()
        self.assertEqual(set(grant.users.all()), {self.user, self.other})
        self.assertFalse(grant.groups.exists())

    def test_existing_access_row_updates_and_rejects_invalid_selections(self) -> None:
        """Update selected users without duplicating grants or saving invalid row changes."""
        grant = AIAgentAccess.objects.create(model=self.agent, name="Existing grant")
        grant.users.add(self.user)
        grant.groups.add(self.group)
        data = QueryDict(mutable=True)
        data.update(
            {
                "access__0__id": str(grant.pk),
                "access__0__name": "Changed grant",
                "access__0__groups": "",
            }
        )
        data.setlist("access__0__users", [str(self.other.pk)])
        self.field.clean(self.widget.value_from_datadict(data, {}, "access")).save(
            self.agent
        )
        grant.refresh_from_db()
        self.assertEqual(grant.name, "Changed grant")
        self.assertEqual(list(grant.users.all()), [self.other])
        self.assertFalse(grant.groups.exists())
        self.assertEqual(self.agent.access.count(), 1)
        data["access__0__name"] = "Must not save"
        data["access__0__users"] = "invalid-user-id"
        with self.assertRaises(ValidationError):
            self.field.clean(self.widget.value_from_datadict(data, {}, "access"))
        grant.refresh_from_db()
        self.assertEqual(grant.name, "Changed grant")
        self.assertEqual(list(grant.users.all()), [self.other])

    def test_default_access_columns_use_requested_order(self) -> None:
        """Configure the access inline table as Name, Users, Groups."""
        items = (
            AIAgent.bloomerp_config.detail_view_settings.get_default_layout()
            .rows[0]
            .items
        )
        access = next(item for item in items if item.id == "access")
        self.assertEqual(access.config["inline_fields"], ["name", "users", "groups"])

    def test_saved_layout_without_column_override_uses_model_default(self) -> None:
        """Apply the new default ordering to existing layouts without resetting preferences."""
        widget = self.application_field.get_widget(layout_config={})
        self.assertEqual(
            [column.field for column in widget.get_columns()],
            ["name", "users", "groups"],
        )
        widget = self.application_field.get_widget(
            layout_config={"inline_fields": ["groups", "name"]}
        )
        self.assertEqual(
            [column.field for column in widget.get_columns()], ["groups", "name"]
        )

    def test_todo_single_label_still_uses_list_binding(self) -> None:
        """Verify the working to-do label path retains its normal QueryDict selection list."""
        label = TodoLabel.objects.create(name="Reference", color="#123456")
        data = QueryDict(mutable=True)
        data.setlist("labels", [str(label.pk)])
        form = forms.modelform_factory(Todo, fields=["labels"])(data=data)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(list(form.cleaned_data["labels"]), [label])

    def test_label_binding_has_same_single_value_requirement_as_users(self) -> None:
        """Show that nested labels also require list-shaped values at child-form binding."""
        label = TodoLabel.objects.create(name="Nested reference", color="#123456")
        form_class = forms.modelform_factory(Todo, fields=["labels"])
        scalar_row = {"labels": str(label.pk)}
        broken = form_class(data=scalar_row)
        self.assertFalse(broken.is_valid())
        self.assertIn("Enter a list of values.", broken.errors["labels"])
        already_list = form_class(data={"labels": [str(label.pk)]})
        self.assertTrue(already_list.is_valid(), already_list.errors)
        fixed = form_class(
            data=OneToManyField._row_form_data(scalar_row, form_class.base_fields)
        )
        self.assertTrue(fixed.is_valid(), fixed.errors)

    def test_old_binding_reproduces_users_error(self) -> None:
        """Reproduce the reported error through the actual nested widget and child form."""
        data = QueryDict(mutable=True)
        data["access__0__name"] = "Old binding"
        data.setlist("access__0__users", [str(self.user.pk)])
        rows = self.widget.value_from_datadict(data, {}, "access")
        self.assertEqual(rows[0]["users"], str(self.user.pk))
        with (
            patch.object(
                OneToManyField, "_row_form_data", staticmethod(legacy_row_form_data)
            ),
            self.assertRaisesMessage(ValidationError, "Enter a list of values"),
        ):
            self.field.clean(rows)
        self.assertFalse(self.agent.access.exists())

    def test_existing_nested_todo_single_label_old_and_new_binding(self) -> None:
        """Compare the initiative's nested label path and preserve existing child identity."""
        initiative = Initiative.objects.create(name="Nested reference")
        todo = Todo.objects.create(title="Existing row", initiative=initiative)
        label = TodoLabel.objects.create(name="One label", color="#123456")
        todo.labels.add(label)
        application_field = ApplicationField.objects.create(
            content_type=ContentType.objects.get_for_model(Initiative),
            field="todos",
            field_type="OneToManyField",
            related_model=ContentType.objects.get_for_model(Todo),
        )
        for name in ("title", "status", "priority", "labels"):
            ApplicationField.objects.create(
                content_type=ContentType.objects.get_for_model(Todo),
                field=name,
                field_type=Todo._meta.get_field(name).get_internal_type(),
            )
        widget = OneToManyFieldWidget(
            attrs={
                "related_model": Todo,
                "parent_model": Initiative,
                "layout_config": {
                    "inline_fields": ["title", "status", "priority", "labels"]
                },
            }
        )
        field = OneToManyField(application_field=application_field, widget=widget)
        field.bind_parent(initiative)
        data = QueryDict(mutable=True)
        data.update(
            {
                "todos__0__id": str(todo.pk),
                "todos__0__title": "Changed title",
                "todos__0__status": todo.status,
                "todos__0__priority": todo.priority,
            }
        )
        data.setlist("todos__0__labels", [str(label.pk)])
        rows = widget.value_from_datadict(data, {}, "todos")
        self.assertEqual(rows[0]["labels"], str(label.pk))
        with (
            patch.object(
                OneToManyField, "_row_form_data", staticmethod(legacy_row_form_data)
            ),
            self.assertRaisesMessage(ValidationError, "Enter a list of values"),
        ):
            field.clean(rows)
        todo.refresh_from_db()
        self.assertEqual(todo.title, "Existing row")
        field.clean(rows).save(initiative)
        todo.refresh_from_db()
        self.assertEqual(todo.title, "Changed title")
        self.assertEqual(list(todo.labels.all()), [label])
        self.assertEqual(initiative.todos.count(), 1)
        data["todos__0__labels"] = ""
        field.clean(widget.value_from_datadict(data, {}, "todos")).save(initiative)
        self.assertFalse(todo.labels.exists())

    def test_normalization_preserves_non_multiple_choice_values(self) -> None:
        """Keep JSON arrays, uploads, booleans, integers, and foreign keys unchanged."""
        upload = SimpleUploadedFile("example.txt", b"payload")
        row = {
            "json": ["first", {"nested": [1, 2]}],
            "name": "Example",
            "enabled": False,
            "count": "0",
            "user": str(self.user.pk),
            "file": upload,
            "choices": "a",
        }
        fields = {
            "json": forms.JSONField(),
            "name": forms.CharField(),
            "enabled": forms.BooleanField(required=False),
            "count": forms.IntegerField(),
            "user": forms.ModelChoiceField(queryset=get_user_model().objects.all()),
            "file": forms.FileField(),
            "choices": forms.MultipleChoiceField(choices=[("a", "A")]),
        }
        normalized = OneToManyField._row_form_data(row, fields)
        self.assertEqual(row["choices"], "a")
        self.assertEqual(normalized["choices"], ["a"])
        for name in fields.keys() - {"choices"}:
            self.assertIs(normalized[name], row[name])
        form = forms.Form(data=normalized, files=OneToManyField._uploaded_files(row))
        form.fields = fields
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["json"], row["json"])
        self.assertEqual(form.cleaned_data["count"], 0)
        self.assertFalse(form.cleaned_data["enabled"])
        self.assertEqual(form.cleaned_data["user"], self.user)
        self.assertIs(form.cleaned_data["file"], upload)
