from bs4 import BeautifulSoup
from django.http import QueryDict

from bloomerp.models.workspaces.sidebar_item import SidebarItem
from bloomerp.tests.base import BaseBloomerpTestCaseWithModels
from bloomerp.widgets.one_to_many_field_widget import OneToManyFieldWidget


class TestCreateView(BaseBloomerpTestCaseWithModels):
    create_foreign_models = True
    
    # --------------------------------------
    # TESTS
    # --------------------------------------
    def test_widget_skips_some_fields(self):
        """
        UC: We don't want particular fields to be rendered for the one-to-many widget
        Expected result: some fields are skipped
        """
        
        # 0. Set the skipped fields
        SKIPPED_FIELDS = ["created_by", "updated_by", "datetime_created", "datetime_updated"]
        
        # 1. Create the widget using the related model and parent model
        widget = OneToManyFieldWidget(attrs={
            "related_model" : self.CountryModel,
            "parent_model" : self.PlanetModel,
        })
        
        # 2. Render the widget to get the columns
        widget_html = widget.render(name="test_widget", value=None, attrs={})
        
        # 3. Check that the skipped fields are not present in the widget HTML
        for field_name in SKIPPED_FIELDS:
            self.assertNotIn(field_name, widget_html)
            
    def test_widget_renders_fields_given_as_config(self):
        """
        UC: We want widgets with a specific layout config to render the necessary fields
        Expected result: the fields specified in the config are rendered
        """
        
        # 0. Set the fields to be rendered
        RENDERED_FIELDS = ["first_name", "last_name"]
        
        # 1. Create the widget using the related model and parent model, and specify the fields to render
        widget = OneToManyFieldWidget(attrs={
            "related_model" : self.CustomerModel,
            "parent_model" : self.CountryModel,
            "layout_config" : {
                "inline_fields" : RENDERED_FIELDS
            }
        })
        
        # 2. Render the widget to get the columns
        widget_html = widget.render(name="test_widget", value=None, attrs={})
        
        # 3. Check that the specified fields are present in the widget HTML
        for field_name in RENDERED_FIELDS:
            self.assertIn(field_name, widget_html)
            
        self.assertNotIn(
            "test_widget____prefix____age",
            widget_html,
        )  # Ensure that a field not specified is not rendered.

    def test_widget_renders_column_defaults_for_new_rows(self):
        """
        Use case: Render a one-to-many widget whose related model has a field default.
        Expected result: The default is exposed as column metadata and fills missing rows.
        """
        # 1. Configure a default for the related model's age field.
        model_field = self.CustomerModel._meta.get_field("age")
        original_default = model_field.default
        model_field.default = 42

        try:
            # 2. Render a prefilled row that omits the defaulted field.
            widget = OneToManyFieldWidget(
                attrs={
                    "related_model": self.CustomerModel,
                    "parent_model": self.CountryModel,
                    "layout_config": {"inline_fields": ["first_name", "age"]},
                }
            )
            soup = BeautifulSoup(
                widget.render(
                    name="customers",
                    value=[{"first_name": "Draft customer"}],
                    attrs={},
                ),
                "html.parser",
            )

            # 3. Verify both the column metadata and row/template inputs use the default.
            age_column = soup.select_one('[data-one-to-many-column="age"]')
            self.assertIsNotNone(age_column)
            self.assertEqual(age_column["data-column-default-value"], "42")
            age_inputs = soup.select(
                '[data-one-to-many-cell="age"] input[name*="__age"]'
            )
            self.assertEqual([input_element.get("value") for input_element in age_inputs], ["42", "42"])
        finally:
            model_field.default = original_default

    def test_widget_closes_open_dropdowns_when_horizontal_scroller_moves(self):
        """
        Use case: Scroll a one-to-many widget after opening a fixed-position column menu.
        Expected result: The scroll container closes open dropdown menus.
        """
        widget = OneToManyFieldWidget(
            attrs={
                "related_model": self.CustomerModel,
                "parent_model": self.CountryModel,
                "layout_config": {"inline_fields": ["first_name"]},
            }
        )
        widget_html = widget.render(name="customers", value=None, attrs={})

        self.assertIn(
            "@scroll=\"$el.querySelectorAll('.bloomerp-dropdown-menu').forEach((menu) => menu.dispatchEvent(new CustomEvent('dropdown-close', { bubbles: true })))\"",
            widget_html,
        )

    def test_widget_renders_text_editors_with_compact_height(self):
        """
        Use case: Render a text editor as an inline one-to-many column.
        Expected result: The inline editor is shorter than a standalone editor.
        """
        # 1. Render the optional customer description as an inline column.
        widget = OneToManyFieldWidget(
            attrs={
                "related_model": self.CustomerModel,
                "parent_model": self.CountryModel,
                "layout_config": {"inline_fields": ["description"]},
            }
        )
        soup = BeautifulSoup(
            widget.render(name="customers", value=None, attrs={}),
            "html.parser",
        )

        # 2. Verify the row template's editor uses only the compact minimum height.
        editor = soup.select_one(
            '[data-one-to-many-row-template] [bloomerp-component="bloomerp-text-editor"]'
        )
        self.assertIsNotNone(editor)
        self.assertIn("min-h-36", editor.get("class", []))
        self.assertNotIn("min-h-72", editor.get("class", []))

    def test_widget_renders_boolean_inline_fields(self):
        """
        Use case: Render a boolean field as an inline one-to-many column.
        Expected result: The boolean input is present and reflects each row value.
        """
        # 1. Render child rows containing both checked and unchecked values.
        widget = OneToManyFieldWidget(
            attrs={
                "related_model": SidebarItem,
                "parent_model": SidebarItem,
                "layout_config": {"inline_fields": ["name", "is_folder"]},
            }
        )
        soup = BeautifulSoup(
            widget.render(
                name="children",
                value=[
                    {"name": "Folder", "is_folder": True},
                    {"name": "Item", "is_folder": False},
                ],
                attrs={},
            ),
            "html.parser",
        )

        # 2. Verify each row includes a checkbox with the submitted state.
        boolean_inputs = soup.select(
            '[data-one-to-many-body] > tr[data-one-to-many-row] '
            '[data-one-to-many-cell="is_folder"] input[type="checkbox"]'
        )
        self.assertEqual(len(boolean_inputs), 2)
        self.assertIn("checked", boolean_inputs[0].attrs)
        self.assertNotIn("checked", boolean_inputs[1].attrs)
        self.assertIn("text-primary", boolean_inputs[0].get("class", []))
        self.assertNotIn("bg-transparent", boolean_inputs[0].get("class", []))
        self.assertEqual(
            soup.select_one('[data-one-to-many-column="is_folder"]')["data-column-kind"],
            "boolean",
        )

    def test_widget_collects_nested_rows_for_form_cleaning(self):
        widget = OneToManyFieldWidget()
        data = QueryDict(mutable=True)
        data.update(
            {
                "contracts__1__id": "20",
                "contracts__1__status": "draft",
                "contracts__0__id": "10",
                "contracts__0__status": "active",
                "contracts__0__DELETE": "1",
                "unrelated": "ignored",
            }
        )

        self.assertEqual(
            widget.value_from_datadict(data, {}, "contracts"),
            [
                {"id": "10", "status": "active", "DELETE": "1"},
                {"id": "20", "status": "draft"},
            ],
        )

    def test_widget_discards_empty_sentinel_beside_foreign_key(self) -> None:
        """An inline foreign key selection must replace its stale empty sentinel."""
        widget = OneToManyFieldWidget()
        data = QueryDict(mutable=True)
        data.setlist(
            "contracts__0__account",
            ["", "9011f77c-d73e-4d65-8457-168c426af65f"],
        )

        self.assertEqual(
            widget.value_from_datadict(data, {}, "contracts"),
            [{"account": "9011f77c-d73e-4d65-8457-168c426af65f"}],
        )

    def test_row_preview_action_is_only_available_for_persisted_rows(self):
        """
        Use case: Render persisted and draft rows in the same one-to-many widget.
        Expected result: Only the persisted row links to its detail view and preview.
        """
        # 1. Render one saved customer and one draft customer row.
        customer = self.CustomerModel.objects.first()
        widget = OneToManyFieldWidget(
            attrs={
                "related_model": self.CustomerModel,
                "parent_model": self.CountryModel,
                "layout_config": {"inline_fields": ["first_name"]},
            }
        )
        widget_html = widget.render(
            name="customers",
            value=[customer, {"first_name": "Draft customer"}],
            attrs={},
        )

        # 2. Inspect the persisted, draft, and row-template preview actions.
        preview_actions = BeautifulSoup(widget_html, "html.parser").select(
            "tr[data-one-to-many-row] [data-one-to-many-view-row]"
        )
        self.assertEqual(len(preview_actions), 3)
        persisted_action, draft_action, template_action = preview_actions

        # 3. Verify only the saved row has an object ID and navigation URL.
        self.assertEqual(persisted_action["data-object-id"], str(customer.pk))
        self.assertEqual(persisted_action["href"], customer.get_absolute_url())
        self.assertNotIn("hidden", persisted_action.get("class", []))
        for action in (draft_action, template_action):
            self.assertEqual(action["data-object-id"], "")
            self.assertNotIn("href", action.attrs)
            self.assertIn("hidden", action.get("class", []))
        
    
