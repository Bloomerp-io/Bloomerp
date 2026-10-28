"""Exercise read-only object previews using the selected, permission-filtered layout."""
from dataclasses import replace
from functools import partial
from unittest.mock import patch

from bs4 import BeautifulSoup
from django.db.models import Model
from django.http import HttpResponse

from bloomerp.field_types.registry import FIELD_TYPE_REGISTRY, FieldTypeDefinition
from bloomerp.filters.definition import FilterCondition
from bloomerp.models import ApplicationField
from bloomerp.models.users.user_object_layout_preference import (
    UserObjectLayoutPreference,
)
from bloomerp.permissions.definition import BloomerpPermission, RowPolicyRuleContent
from bloomerp.permissions.manager import PolicyManager
from bloomerp.tests.base import (
    BloomerpComponentTestCase,
    ExpectedResult,
    RequestScenario,
)


class TestObjectPreviewComponent(BloomerpComponentTestCase):
    """Cover rendered values, layout selection, copy controls, and isolated failures."""

    view_name = "components_object_preview"
    create_foreign_models = True

    def setUp(self) -> None:
        """Create a selected four-column layout and representative field values."""
        super().setUp()
        self.customer = self.CustomerModel.objects.first()
        self.customer.description = "<p>Preview <strong>description</strong></p>"
        self.customer.age = 0
        self.customer.country = self.CountryModel.objects.first()
        self.customer.save()
        self.content_type = self.get_content_type_for_model(self.CustomerModel)
        self.fields = {
            field.field: field
            for field in ApplicationField.get_for_model(self.CustomerModel)
        }
        UserObjectLayoutPreference.objects.create(
            user=self.admin_user, content_type=self.content_type,
            name="Unselected layout", selected=False,
            layout={"rows": [{"columns": 1, "title": "Not selected", "items": [
                {"id": self.fields["last_name"].pk},
            ]}]},
        )
        self.layout = {"rows": [{"columns": 4, "title": "Preview details", "items": [
            {"id": self.fields["description"].pk, "colspan": 4},
            {"id": self.fields["first_name"].pk, "colspan": 3},
            {"id": self.fields["age"].pk, "colspan": 1},
            {"id": self.fields["country"].pk, "colspan": 2},
        ]}]}
        UserObjectLayoutPreference.objects.create(
            user=self.admin_user, content_type=self.content_type,
            name="Selected layout", selected=True, layout=self.layout,
        )

    def get_test_scenarios(self) -> list[RequestScenario]:
        """Declare preview HTTP contracts without exercising unrelated CRUD endpoints."""
        route = {"content_type_id": self.content_type.pk, "object_id": self.customer.pk}
        return [
            RequestScenario(
                name="Renders values without input widgets", user=self.admin_user,
                view_kwargs=route, expected=ExpectedResult(response_validators=self._readonly_values),
            ),
            RequestScenario(
                name="Preserves selected layout order and column spans", user=self.admin_user,
                view_kwargs=route, expected=ExpectedResult(response_validators=self._selected_layout),
            ),
            RequestScenario(
                name="Each visible value has a copy button beside its label", user=self.admin_user,
                view_kwargs=route, expected=ExpectedResult(response_validators=self._copy_controls),
            ),
            RequestScenario(
                name="Denied object exposes only the permitted object label", user=self.normal_user,
                view_kwargs=route, expected=ExpectedResult(response_validators=self._denied_object),
            ),
            RequestScenario(
                name="Denied fields have neither values nor copy controls", user=self.normal_user,
                view_kwargs=route, prepare=self._grant_name_only,
                expected=ExpectedResult(response_validators=self._denied_fields),
            ),
            RequestScenario(
                name="A field granted on another row remains denied on this object", user=self.normal_user,
                view_kwargs=route, prepare=self._grant_other_row_description,
                expected=ExpectedResult(response_validators=self._denied_fields),
            ),
            RequestScenario(
                name="Plain text remains escaped and rich text removes active content", user=self.admin_user,
                view_kwargs=route, prepare=self._hostile_values,
                expected=ExpectedResult(response_validators=self._safe_values),
            ),
            RequestScenario(
                name="Legacy URL renderer retains safe clickable links", user=self.admin_user,
                view_kwargs=route, prepare=self._url_value, cleanup=self._restore_field_renderer,
                expected=ExpectedResult(response_validators=self._safe_link),
            ),
            RequestScenario(
                name="Legacy URL renderer rejects executable protocols", user=self.admin_user,
                view_kwargs=route, prepare=self._unsafe_url_value, cleanup=self._restore_field_renderer,
                expected=ExpectedResult(response_validators=self._unsafe_link),
            ),
            *[
                RequestScenario(
                    name=f"{field_type} advanced preview {mode}", user=self.admin_user,
                    view_kwargs=route,
                    prepare=partial(self._advanced_preview, field_type_id=field_type, mode=mode),
                    cleanup=self._restore_field_renderer,
                    expected=ExpectedResult(response_validators=partial(
                        self._advanced_preview_result, mode=mode,
                    )),
                )
                for field_type in ("TextField", "EmailField", "URLField", "FileField")
                for mode in ("styled", "empty", "invalid", "runtime_failure")
            ],
            RequestScenario(
                name="One broken field preserves the other values and layout", user=self.admin_user,
                view_kwargs=route, prepare=self._break_field_renderer,
                cleanup=self._restore_field_renderer,
                expected=ExpectedResult(response_validators=self._isolated_failure),
            ),
        ]

    def _readonly_values(self, response: HttpResponse) -> bool:
        """Verify field renderers produce rich text and related links, never widgets."""
        soup = BeautifulSoup(response.content, "html.parser")
        self.assertFalse(soup.select("input, select, textarea, [contenteditable], [bloomerp-component]"))
        self.assertEqual(soup.select_one("[data-preview-value] strong").text, "description")
        related = soup.select_one(f'[data-preview-field="{self.fields["country"].pk}"] a')
        self.assertEqual(related["href"], self.customer.country.get_absolute_url())
        age = soup.select_one(f'[data-preview-field="{self.fields["age"].pk}"] [data-preview-value]')
        self.assertEqual(age.get_text(strip=True), "0")
        return True

    def _selected_layout(self, response: HttpResponse) -> bool:
        """Assert span styles belong to direct grid children in saved item order."""
        soup = BeautifulSoup(response.content, "html.parser")
        grid = soup.select_one('[style="grid-template-columns: repeat(4, minmax(0, 1fr));"]')
        self.assertIsNotNone(grid)
        items = grid.find_all(recursive=False)
        expected = self.layout["rows"][0]["items"]
        self.assertEqual([item["data-preview-field"] for item in items], [str(item["id"]) for item in expected])
        for item, config in zip(items, expected):
            self.assertEqual(item["style"], f'grid-column: span {config["colspan"]} / span {config["colspan"]};')
        self.assertNotIn("Not selected", soup.get_text())
        self.assertIn("Preview details", soup.get_text())
        return True

    def _copy_controls(self, response: HttpResponse) -> bool:
        """Ensure copy controls are labelled buttons adjacent to field labels."""
        soup = BeautifulSoup(response.content, "html.parser")
        for field in soup.select("[data-preview-field]"):
            button = field.select_one("button[data-preview-copy]")
            self.assertEqual(button["type"], "button")
            label = button.parent.select_one("[data-preview-label]").get_text(strip=True)
            self.assertEqual(button["aria-label"], f"Copy {label}")
            self.assertIsNotNone(field.select_one('[data-preview-copy-status][aria-live="polite"]'))
        self.assertEqual(len(soup.select("[data-preview-copy]")), 4)
        return True

    def _denied_object(self, response: HttpResponse) -> bool:
        """Keep the explanatory denial and object label without field data."""
        soup = BeautifulSoup(response.content, "html.parser")
        self.assertIn(str(self.customer), soup.get_text())
        self.assertIn("You do not have direct access to this object.", soup.get_text())
        self.assertFalse(soup.select("[data-preview-field], [data-preview-copy]"))
        self.assertNotIn("Preview description", soup.get_text())
        return True

    def _grant_name_only(self, scenario: RequestScenario) -> None:
        """Grant row access and one viewable field through the real policy manager."""
        policy = PolicyManager.create_policy(
            model_or_content_type=self.CustomerModel,
            field_permissions={"first_name": [BloomerpPermission.VIEW]},
            row_permissions=[RowPolicyRuleContent(
                connector="AND", permissions=[BloomerpPermission.VIEW], conditions=[],
            )],
        )
        policy.users.add(self.normal_user)
        UserObjectLayoutPreference.objects.create(
            user=self.normal_user, content_type=self.content_type,
            name="Restricted layout", selected=True, layout=self.layout,
        )

    def _grant_other_row_description(self, scenario: RequestScenario) -> None:
        """Grant the description only on another row, retaining access to this object's name."""
        self._grant_name_only(scenario)
        PolicyManager.create_policy(
            model_or_content_type=self.CustomerModel,
            field_permissions={"description": [BloomerpPermission.VIEW]},
            row_permissions=[RowPolicyRuleContent(
                connector="AND", permissions=[BloomerpPermission.VIEW],
                conditions=[FilterCondition(
                    field_path="first_name", lookup_id="equals", value="OTHER-ROW",
                )],
            )],
        ).assign_user(self.normal_user)

    def _denied_fields(self, response: HttpResponse) -> bool:
        """Check restricted HTML contains no hidden values, links, or copy metadata."""
        soup = BeautifulSoup(response.content, "html.parser")
        self.assertEqual([item["data-preview-field"] for item in soup.select("[data-preview-field]")],
                         [str(self.fields["first_name"].pk)])
        self.assertEqual(len(soup.select("[data-preview-copy]")), 1)
        self.assertNotIn("Preview description", soup.get_text())
        self.assertFalse(soup.select("a, input, select, textarea"))
        return True

    def _hostile_values(self, scenario: RequestScenario) -> None:
        """Store untrusted values that must never become active tooltip DOM."""
        self.customer.first_name = '<img src=x onerror="alert(1)">'
        self.customer.description = (
            '<p onclick="alert(1)">Readable <strong>description</strong></p>'
            '<script>alert(1)</script><input value="unexpected">'
            '<a href="javascript:alert(1)">Unsafe link</a>'
        )
        self.customer.save()

    def _safe_values(self, response: HttpResponse) -> bool:
        """Preserve literal text and rich formatting while rejecting active markup."""
        soup = BeautifulSoup(response.content, "html.parser")
        name = soup.select_one(f'[data-preview-field="{self.fields["first_name"].pk}"] [data-preview-value]')
        self.assertEqual(name.get_text(), self.customer.first_name)
        self.assertFalse(soup.select("img, script, input, select, textarea, [onclick], [onerror]"))
        self.assertEqual(soup.select_one("[data-preview-value] strong").text, "description")
        self.assertFalse(soup.select('[href^="javascript:"]'))
        return True

    def _url_value(self, scenario: RequestScenario) -> None:
        """Exercise the legacy URL renderer through the preview endpoint."""
        original_get_field_type = ApplicationField.get_field_type

        def get_field_type(field: ApplicationField) -> FieldTypeDefinition:
            """Use the shipped URL renderer for this one test field only."""
            if field.pk == self.fields["first_name"].pk:
                return FIELD_TYPE_REGISTRY.from_id("URLField")
            return original_get_field_type(field)

        self.renderer_patch = patch.object(ApplicationField, "get_field_type", get_field_type)
        self.renderer_patch.start()
        self.customer.first_name = "https://example.test/?a=1&b=2"
        self.customer.save(update_fields=["first_name"])

    def _safe_link(self, response: HttpResponse) -> bool:
        """Keep the renderer's safe URL and readable text after sanitization."""
        soup = BeautifulSoup(response.content, "html.parser")
        link = soup.select_one(f'[data-preview-field="{self.fields["first_name"].pk}"] a')
        self.assertIsNotNone(link)
        self.assertEqual(link["href"], self.customer.first_name)
        self.assertEqual(link.get_text(), self.customer.first_name)
        return True

    def _unsafe_url_value(self, scenario: RequestScenario) -> None:
        """Model an unvalidated stored URL without allowing its executable scheme."""
        self._url_value(scenario)
        self.customer.first_name = "javascript:alert(1)"
        self.customer.save(update_fields=["first_name"])

    def _unsafe_link(self, response: HttpResponse) -> bool:
        """Keep unsafe URL text visible while stripping the executable destination."""
        soup = BeautifulSoup(response.content, "html.parser")
        value = soup.select_one(f'[data-preview-field="{self.fields["first_name"].pk}"] [data-preview-value]')
        self.assertIn("javascript:alert(1)", value.get_text())
        self.assertFalse(value.select("a[href]"))
        return True

    def _break_field_renderer(self, scenario: RequestScenario) -> None:
        """Break only the rich-text field renderer to verify failure isolation."""
        original_get_field_type = ApplicationField.get_field_type

        def broken_renderer(field: ApplicationField, instance: Model) -> str:
            """Simulate a field-specific rendering exception after type resolution."""
            raise RuntimeError("broken preview field")

        def get_field_type(field: ApplicationField) -> FieldTypeDefinition:
            """Replace only the description renderer, leaving other fields unchanged."""
            definition = original_get_field_type(field)
            if field.pk == self.fields["description"].pk:
                return replace(definition, render_value=broken_renderer)
            return definition

        self.renderer_patch = patch.object(ApplicationField, "get_field_type", get_field_type)
        self.renderer_patch.start()

    def _restore_field_renderer(self, scenario: RequestScenario) -> None:
        """Restore the renderer after this scenario, including failed assertions."""
        self.renderer_patch.stop()

    def _isolated_failure(self, response: HttpResponse) -> bool:
        """Keep the failed field's span while rendering unaffected fields normally."""
        self._selected_layout(response)
        soup = BeautifulSoup(response.content, "html.parser")
        failed = soup.select_one(f'[data-preview-field="{self.fields["description"].pk}"]')
        self.assertIn("Preview is not available for this field.", failed.get_text())
        self.assertIsNone(failed.select_one("[data-preview-copy]"))
        self.assertEqual(len(soup.select("[data-preview-copy]")), 3)
        self.assertNotIn("Preview is not available for this object type.", soup.get_text())
        return True

    def _advanced_preview(
        self, scenario: RequestScenario, *, field_type_id: str, mode: str,
    ) -> None:
        """Configure each legacy HTML type with trusted markup or a failing override."""
        original_get_field_type = ApplicationField.get_field_type

        def legacy_renderer(field: ApplicationField, instance: Model) -> str:
            """Return unsafe legacy markup that must be sanitized after fallback."""
            return '<p onclick="alert(1)">Legacy fallback</p><script>alert(1)</script>'

        def get_field_type(field: ApplicationField) -> FieldTypeDefinition:
            """Exercise all legacy HTML sanitization branches on one preview field."""
            if field.pk == self.fields["description"].pk:
                return replace(
                    FIELD_TYPE_REGISTRY.from_id(field_type_id), render_value=legacy_renderer,
                )
            return original_get_field_type(field)

        self.renderer_patch = patch.object(ApplicationField, "get_field_type", get_field_type)
        self.renderer_patch.start()
        self.customer.description = '<img src=x onerror="alert(1)">'
        self.customer.save(update_fields=["description"])
        templates = {
            "styled": '<span class="text-red-600">{{ value }}</span>',
            "empty": '{% if False %}hidden{% endif %}',
            "invalid": '{% if value %}',
            "runtime_failure": '{% include "missing-advanced-preview-template.html" %}',
        }
        # Simulate legacy invalid storage without bypassing validation in normal saves.
        ApplicationField.objects.filter(pk=self.fields["description"].pk).update(
            advanced_rendering=templates[mode],
        )

    def _advanced_preview_result(self, response: HttpResponse, *, mode: str) -> bool:
        """Keep trusted template styling, escape values, and sanitize only fallbacks."""
        soup = BeautifulSoup(response.content, "html.parser")
        value = soup.select_one(
            f'[data-preview-field="{self.fields["description"].pk}"] [data-preview-value]',
        )
        self.assertIsNotNone(value)
        self.assertFalse(value.select("script, img, [onclick], [onerror]"))
        if mode == "styled":
            styled = value.select_one("span.text-red-600")
            self.assertIsNotNone(styled)
            self.assertEqual(styled.get_text(), self.customer.description)
        elif mode == "empty":
            self.assertEqual(value.get_text(), "")
        else:
            self.assertEqual(value.get_text(), "Legacy fallback")
            self.assertIsNotNone(value.select_one("p"))
        return True
