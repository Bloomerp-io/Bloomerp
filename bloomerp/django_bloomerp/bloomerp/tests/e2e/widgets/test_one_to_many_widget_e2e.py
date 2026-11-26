from urllib.parse import urlencode

from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from playwright.sync_api import Locator, expect

from bloomerp.models import ApplicationField
from bloomerp.models import FieldLayout, LayoutItem, LayoutRow
from bloomerp.models.users.user_object_layout_preference import (
    UserObjectLayoutPreference,
)
from bloomerp.services.preference_services import PreferenceManager
from bloomerp.tests.base import E2EAction, E2ERequestScenario, e2e_test_case
from bloomerp.tests.e2e.generic.test_crud_mixin import TestCrudE2EMixin
from bloomerp.utils.models import get_create_view_url


class TestOneToManyWidgetE2E(TestCrudE2EMixin, e2e_test_case.BloomerpE2ETestCase):
    create_foreign_models = True
    inline_fields = [
        "first_name",
        "customer_type",
        "age",
        "date_joined",
        "description",
    ]

    def extendedE2ESetup(self) -> None:
        """Expose Country.customers as an editable one-to-many test widget."""
        content_type = ContentType.objects.get_for_model(self.CountryModel)
        customers_field = ApplicationField.get_for_model(self.CountryModel).get(
            field="customers"
        )
        name_field = ApplicationField.get_for_model(self.CountryModel).get(field="name")
        preference = PreferenceManager(self.admin_user).get_or_create_selected(
            UserObjectLayoutPreference,
            scope={"content_type_id": content_type.pk},
        )
        preference.layout = FieldLayout(
            rows=[
                LayoutRow(
                    columns=1,
                    title="Customers",
                    items=[
                        LayoutItem(
                            id=customers_field.pk,
                            config={
                                "inline_fields": self.inline_fields,
                                "show_totals": True,
                            },
                        ),
                        LayoutItem(id=name_field.pk, colspan=1),
                    ],
                )
            ]
        ).model_dump()
        preference.save(update_fields=["layout"])
        self.customer_type = self.CustomerTypeModel.objects.get(name="Retail")
        self.CustomerModel._meta.get_field("age").default = 42
        self._authenticate_browser(self.admin_user)

    def get_test_scenarios(self) -> list[E2ERequestScenario]:
        """Cover horizontal scrolling in a detail form with a wide inline table."""
        country = self.CountryModel.objects.get(name="Belgium")
        self.create_customer("Ada", "Lovelace", 30, country=country)
        return [
            E2ERequestScenario(
                name="Wide inline table scrolls inside the detail field",
                user=self.admin_user,
                url=country.get_absolute_url(),
                actions=[
                    E2EAction(
                        name="Scroll to the last column in a narrow viewport",
                        execute=self.scroll_wide_table,
                    ),
                ],
            )
        ]

    def scroll_wide_table(self) -> None:
        """Reach the row actions without making the parent field overflow."""
        self.page.set_viewport_size({"width": 480, "height": 900})
        widget = self.get_widget()
        expect(widget).to_be_visible()
        table = widget.get_by_role("table")
        scroll_offset: int = table.evaluate(
            """table => {
                const scroller = table.parentElement;
                scroller.scrollLeft = scroller.scrollWidth;
                return scroller.scrollLeft;
            }"""
        )
        self.assertGreater(scroll_offset, 0)
        row_actions = self.get_rows().first.get_by_role("button", name="Clone row")
        row_actions.scroll_into_view_if_needed()
        expect(row_actions).to_be_in_viewport()
        overflow: int = widget.evaluate(
            """widget => {
                const field = widget.closest("[data-layout-item-id]");
                return field.scrollWidth - field.clientWidth;
            }"""
        )
        self.assertEqual(overflow, 0)

    def get_base_url(self) -> str:
        return reverse(get_create_view_url(model=self.CountryModel))

    def get_url_with_rows(self, rows: list[dict[str, object]]) -> str:
        query = {
            f"customers__{row_index}__{field_name}": value
            for row_index, row in enumerate(rows)
            for field_name, value in row.items()
        }
        return f"{self.get_base_url()}?{urlencode(query)}"

    def get_widget(self) -> Locator:
        return self.page.locator('[data-one-to-many-name="customers"]')

    def get_rows(self, *, visible: bool = False) -> Locator:
        selector = "[data-one-to-many-row]:not([data-one-to-many-deleted])"
        if visible:
            selector += ":visible"
        return self.get_widget().locator(selector)

    def get_column_values(self, field_name: str) -> list[str]:
        controls = self.get_rows().locator(
            f'[data-one-to-many-cell="{field_name}"] input'
        )
        return [control.input_value() for control in controls.all()]

    def open_column_actions(self, field_name: str) -> Locator:
        actions = self.get_widget().locator(
            f'[data-one-to-many-column-actions="{field_name}"]'
        )
        actions.get_by_role("button", name="Column actions").click()
        return actions

    def test_insert_existing_customer(self) -> None:
        """Exercise the foreign-field picker and persist a pending link on Save."""
        self.insertion_country = self.CountryModel.objects.get(name="Belgium")
        other_country = self.CountryModel.objects.get(name="Netherlands")
        self.create_customer("Already assigned", "Example", 28, country=other_country)
        self.create_customer("Other available", "Example", 20)
        self.insertable_customer = self.create_customer("Available customer", "Example", 28)
        scenario = E2ERequestScenario(
            name="Insert an existing customer through the dataview",
            user=self.admin_user,
            url=self.insertion_country.get_absolute_url(),
            actions=[
                E2EAction(name="Stage, discard, and save an existing row", execute=self.verify_existing_insertion),
            ],
        )
        self._run_request_scenario(scenario, scenario.name)

    def test_insert_existing_customer_on_create(self) -> None:
        """Stage the relation before the new parent has a database row."""
        self.insertable_customer = self.create_customer("Available customer", "Example", 28)
        planet = self.PlanetModel.objects.get(name="Earth")
        scenario = E2ERequestScenario(
            name="Insert an existing customer when creating a parent",
            user=self.admin_user,
            url=f"{self.get_base_url()}?{urlencode({'planet': str(planet.pk)})}",
            actions=[
                E2EAction(name="Create the parent and link the customer", execute=self.save_new_parent_with_existing_row),
            ],
        )
        self._run_request_scenario(scenario, scenario.name)

    def save_new_parent_with_existing_row(self) -> None:
        """Save a new parent and verify that its pending row retained its identity."""
        self.stage_existing_customer()
        form = self.get_widget().locator("xpath=ancestor::form[1]")
        form.locator('[name="name"]').fill("Country from existing row")
        with self.expect_response_for(self.get_base_url(), method="POST") as response:
            form.get_by_role("button", name="Save", exact=True).click()
        self.assertEqual(response.value.status, 302)
        self.insertable_customer.refresh_from_db()
        self.assertEqual(self.insertable_customer.country.name, "Country from existing row")

    def stage_existing_customer(self, *, filter_by_age: bool = False) -> Locator:
        """Select an unassigned customer from the standard foreign-field picker."""
        self.get_widget().get_by_role("button", name="Insert existing").click()
        picker = self.page.get_by_role("dialog", name="Insert existing")
        dataview = picker.locator('[bloomerp-component="foreign-field-dataview"]')
        available = dataview.get_by_role("cell", name="Available customer", exact=True)
        assigned = dataview.get_by_role("cell", name="Already assigned", exact=True)
        expect(available).to_be_visible()
        expect(assigned).to_have_count(0)
        if filter_by_age:
            other = dataview.get_by_role("cell", name="Other available", exact=True)
            expect(other).to_be_visible()
            filter_button = dataview.get_by_role("button", name="Filter", exact=True)
            filter_button.click()
            editor = dataview.locator('[data-filter-host-editor] [bloomerp-component="unified-filter-container"]')
            editor.get_by_label("Field", exact=True).select_option(label="Age")
            editor.get_by_label("Lookup", exact=True).select_option("equals")
            editor.locator('.filter-value-editor input:not([type="hidden"])').fill("28")
            editor.get_by_role("button", name="Apply", exact=True).click()
            expect(available).to_be_visible()
            expect(other).to_have_count(0)
            expect(assigned).to_have_count(0)
            filter_button.click()
        available.dblclick()
        expect(picker).to_be_hidden()
        pending = self.get_widget().locator("[data-one-to-many-pending]")
        expect(pending).to_contain_text("Available customer")
        self.insertable_customer.refresh_from_db()
        self.assertIsNone(self.insertable_customer.country_id)
        return pending

    def verify_existing_insertion(self) -> None:
        """Discard a staged link, then link the same record with its values intact."""
        pending = self.stage_existing_customer(filter_by_age=True)
        pending.get_by_role("button", name="Remove row").click()
        expect(pending).to_have_count(0)
        self.insertable_customer.refresh_from_db()
        self.assertIsNone(self.insertable_customer.country_id)

        self.stage_existing_customer()
        with self.expect_response_for(self.insertion_country.get_absolute_url(), method="POST") as response:
            self.page.get_by_role("button", name="Save", exact=True).click()
        self.assertEqual(response.value.status, 200)
        expect(self.get_rows()).to_have_count(1)
        expect(self.get_rows().first.locator('input[name$="__id"]')).to_have_value(
            str(self.insertable_customer.pk),
        )
        expect(self.get_rows().first.locator('[data-one-to-many-cell="age"] input')).to_have_value("28")
        self.insertable_customer.refresh_from_db()
        self.assertEqual(self.insertable_customer.country_id, self.insertion_country.pk)
        self.assertEqual(self.insertion_country.customers.count(), 1)

    # ---------------------------------------
    # Test row Actions
    # ---------------------------------------
    def test_trash_icon_removes_row(self):
        """
        Use case: Remove an individual row using its trash action.
        Expected result: The selected row disappears and the empty state is shown.
        """
        # 1. Open a country form with one unsaved customer row.
        self.goto(self.get_url_with_rows([{"first_name": "Ada"}]))
        expect(self.get_rows()).to_have_count(1)

        # 2. Verify row hover does not expose every action tooltip.
        row = self.get_rows().first
        remove_tooltip = row.get_by_text("Remove row", exact=True)
        row.locator('[data-one-to-many-cell="first_name"] input').hover()
        expect(remove_tooltip).to_be_hidden()

        # 3. Hover the trash icon, then remove the row.
        remove_button = row.get_by_role("button", name="Remove row")
        remove_button.hover()
        expect(remove_tooltip).to_be_visible()
        remove_button.click()

        # 4. Verify the row was removed and the empty state replaced it.
        expect(self.get_rows()).to_have_count(0)
        expect(self.get_widget().get_by_text("No related objects found.")).to_be_visible()

    def test_saved_row_update_after_htmx_response_does_not_create_duplicate(self):
        """
        Use case: Update the same persisted one-to-many row across consecutive HTMX saves.
        Expected result: The existing child is updated and no duplicate child is created.
        """
        # 1. Open a persisted parent that has no related rows.
        country = self.CountryModel.objects.get(name="Belgium")
        country.customers.all().update(country=None)
        self.goto(country.get_absolute_url())
        expect(self.get_rows()).to_have_count(0)

        # 2. Add a child and persist it through the first HTMX save.
        self.get_widget().get_by_role("button", name="Add row").click()
        row = self.get_rows().first
        row.locator('[data-one-to-many-cell="first_name"] input').fill(
            "HTMX Customer"
        )
        row.locator('[data-one-to-many-cell="age"] input').fill("21")
        with self.expect_response_for(
            country.get_absolute_url(), method="POST"
        ) as response_info:
            self.page.get_by_role("button", name="Save", exact=True).click()
        self.assertEqual(response_info.value.status, 200)
        expect(self.get_rows()).to_have_count(1)
        customer = country.customers.get(first_name="HTMX Customer")
        expect(
            self.get_rows().first.locator('input[name$="__id"]')
        ).to_have_value(str(customer.pk))

        # 3. Update the server-rendered row again and save through HTMX.
        self.get_rows().first.locator(
            '[data-one-to-many-cell="age"] input'
        ).fill("22")
        with self.expect_response_for(
            country.get_absolute_url(), method="POST"
        ) as response_info:
            self.page.get_by_role("button", name="Save", exact=True).click()
        self.assertEqual(response_info.value.status, 200)

        # 4. Verify the same child was updated instead of creating a duplicate.
        expect(self.get_rows()).to_have_count(1)
        self.assertEqual(country.customers.count(), 1)
        customer.refresh_from_db()
        self.assertEqual(customer.age, 22)

    def test_deleted_rows_disappear_from_htmx_save_response(self):
        """
        Use case: Delete persisted one-to-many rows and save through HTMX.
        Expected result: The returned detail form immediately renders the empty state.
        """
        # 1. Attach two persisted customers to a country and open its detail form.
        country = self.CountryModel.objects.get(name="Belgium")
        customers = list(self.CustomerModel.objects.all()[:2])
        for customer in customers:
            customer.country = country
            customer.save(update_fields=["country"])
        self.goto(country.get_absolute_url())
        expect(self.get_rows()).to_have_count(2)

        # 2. Remove both rows and save through HTMX.
        for _ in customers:
            self.get_rows().first.get_by_role("button", name="Remove row").click()
        expect(self.get_rows()).to_have_count(0)
        with self.expect_response_for(
            country.get_absolute_url(), method="POST"
        ) as response_info:
            self.page.get_by_role("button", name="Save", exact=True).click()
        self.assertEqual(response_info.value.status, 200)

        # 3. Verify the HTMX response and database both contain no related rows.
        expect(self.get_rows()).to_have_count(0)
        expect(
            self.get_widget().get_by_text("No related objects found.")
        ).to_be_visible()
        self.assertEqual(country.customers.count(), 0)

    def test_clone_icon_clones_row(self):
        """
        Use case: Clone an individual row using its clone action.
        Expected result: A new unsaved row preserves native and foreign-key values.
        """
        # 1. Open a country form with one complete customer row.
        self.goto(
            self.get_url_with_rows(
                [
                    {
                        "first_name": "Ada",
                        "customer_type": self.customer_type.pk,
                        "age": 30,
                        "date_joined": "2026-08-04",
                    }
                ]
            )
        )

        # 2. Clone the row.
        self.get_rows().get_by_role("button", name="Clone row").click()

        # 3. Verify a second row exists with copied values.
        expect(self.get_rows()).to_have_count(2)
        self.assertEqual(self.get_column_values("first_name"), ["Ada", "Ada"])
        self.assertEqual(self.get_column_values("age"), ["30", "30"])
        self.assertEqual(
            self.get_column_values("date_joined"),
            ["2026-08-04", "2026-08-04"],
        )
        customer_type_inputs = self.get_rows().locator(
            '[data-one-to-many-cell="customer_type"] '
            'input[type="hidden"][data-generated="true"]'
        )
        expect(customer_type_inputs).to_have_count(2)
        self.assertEqual(
            [control.input_value() for control in customer_type_inputs.all()],
            [str(self.customer_type.pk), str(self.customer_type.pk)],
        )
        expect(
            self.get_rows().nth(1).locator(
                '[data-one-to-many-cell="customer_type"] .foreign-field-selected'
            )
        ).to_contain_text("Retail")

    def test_add_and_clone_rows_use_column_defaults(self):
        """
        Use case: Add and clone rows when a related column has a model default.
        Expected result: New rows use the default while clones preserve explicit values.
        """
        # 1. Open a form with a prefilled row that omits the defaulted age.
        self.goto(self.get_url_with_rows([{"first_name": "Ada"}]))
        self.assertEqual(self.get_column_values("age"), ["42"])

        # 2. Add a row and verify the default is applied to it.
        self.get_widget().get_by_role("button", name="Add row").click()
        self.assertEqual(self.get_column_values("age"), ["42", "42"])

        # 3. Change the first value and clone the row.
        self.get_rows().nth(0).locator('[data-one-to-many-cell="age"] input').fill("30")
        self.get_rows().nth(0).get_by_role("button", name="Clone row").click()

        # 4. Verify cloning preserves the explicit value and does not replace it with the default.
        self.assertEqual(self.get_column_values("age"), ["30", "42", "30"])

    def test_query_prefill_keeps_hidden_columns_without_duplicate_visible_values(self):
        """
        Use case: Submit one-to-many query-prefilled data when one column is not rendered.
        Expected result: Visible values submit once and hidden values remain as prefill inputs.
        """
        # 1. Hide the description column while keeping the numeric age column visible.
        preference = PreferenceManager(self.admin_user).get_or_create_selected(
            UserObjectLayoutPreference,
            scope={
                "content_type_id": ContentType.objects.get_for_model(
                    self.CountryModel
                ).pk
            },
        )
        planet_field = ApplicationField.get_for_model(self.CountryModel).get(
            field="planet"
        )
        layout = preference.layout
        layout["rows"][0]["items"][0]["config"]["inline_fields"] = [
            "first_name",
            "last_name",
            "age",
        ]
        layout["rows"][0]["items"].append(
            LayoutItem(id=planet_field.pk, colspan=1).model_dump()
        )
        preference.layout = layout
        preference.save(update_fields=["layout"])
        planet = self.PlanetModel.objects.first()

        # 2. Open the full create form with both visible and hidden row values.
        self.goto(
            self.get_url_with_rows(
                [{
                    "first_name": "Ada",
                    "last_name": "Lovelace",
                    "age": 30,
                    "description": "Preserved description",
                }]
            )
            + f"&planet={planet.pk}"
        )
        self.assertEqual(self.get_column_values("age"), ["30"])
        expect(
            self.get_widget().locator('[data-one-to-many-cell="description"]')
        ).to_have_count(0)

        # 3. Confirm only the hidden description is carried as a hidden input.
        form = self.page.locator("form").filter(
            has=self.page.locator('input[name="customers__0__age"]')
        )
        expect(
            form.locator('input[type="hidden"][name="customers__0__age"]')
        ).to_have_count(0)
        expect(
            form.locator('input[type="hidden"][name="customers__0__description"]')
        ).to_have_count(1)

        # 4. Submit the form and verify the visible row value was persisted.
        self.page.locator("#id_name").fill("Query Prefilled Country")
        create_path = reverse(get_create_view_url(model=self.CountryModel))
        save_button = self.page.get_by_role("button", name="Save", exact=True)
        with self.expect_response_for(create_path, method="POST") as response_info:
            save_button.click()
        self.assertEqual(response_info.value.status, 302)

        country = self.CountryModel.objects.get(name="Query Prefilled Country")
        customer = country.customers.get(first_name="Ada")
        self.assertEqual(customer.age, 30)

    def test_text_editors_update_their_own_one_to_many_rows(self):
        """
        Use case: Edit text-editor fields in two server-rendered one-to-many rows.
        Expected result: Each editor updates only the hidden input in its own row.
        """
        # 1. Open a country form with two text-editor rows already rendered.
        self.goto(
            self.get_url_with_rows(
                [
                    {"description": "First customer description"},
                    {"description": "Second customer description"},
                ]
            )
        )
        expect(self.get_rows()).to_have_count(2)

        # 2. Enter different content in each row's text editor.
        first_editor = self.get_rows().nth(0).locator(
            '[data-one-to-many-cell="description"] .bloomerp-text-editor'
        )
        second_editor = self.get_rows().nth(1).locator(
            '[data-one-to-many-cell="description"] .bloomerp-text-editor'
        )
        first_editor.focus()
        expect(first_editor).to_be_focused()
        second_editor_wrapper = self.get_rows().nth(1).locator(
            '[data-one-to-many-cell="description"] '
            '[bloomerp-component="bloomerp-text-editor"]'
        )
        second_editor_wrapper.dispatch_event("click")
        expect(second_editor).to_be_focused()
        expect(first_editor).not_to_be_focused()
        first_editor.fill("Updated first customer description")
        second_editor.fill("Updated second customer description")

        # 3. Verify each editor synchronized its own row's form input.
        first_value = self.get_rows().nth(0).locator(
            '[data-one-to-many-cell="description"] [data-text-editor-input="true"]'
        ).input_value()
        second_value = self.get_rows().nth(1).locator(
            '[data-one-to-many-cell="description"] [data-text-editor-input="true"]'
        ).input_value()
        self.assertIn("Updated first customer description", first_value)
        self.assertNotIn("Updated second customer description", first_value)
        self.assertIn("Updated second customer description", second_value)
        self.assertNotIn("Updated first customer description", second_value)

    def test_preview_icon_previews_and_opens_persisted_row(self):
        """
        Use case: Hover and click the preview action for a saved related object.
        Expected result: Hovering loads its object preview and clicking opens its detail view.
        """
        # 1. Attach an existing customer to a country and open the country form.
        country = self.CountryModel.objects.get(name="Belgium")
        customer = self.CustomerModel.objects.first()
        customer.country = country
        customer.save(update_fields=["country"])
        self.goto(country.get_absolute_url())

        # 2. Hover the saved row's magnifying glass.
        preview_link = self.get_rows().first.get_by_role("link", name="View row")
        expect(preview_link).to_be_visible()
        preview_link.hover()

        # 3. Verify the shared object-preview component is loaded.
        preview = self.page.locator(".foreign-field-preview-tooltip")
        expect(preview).to_be_visible(timeout=5_000)
        expect(preview).to_contain_text(customer.first_name, timeout=5_000)

        # 4. Click the magnifying glass and verify navigation to the customer.
        expect(preview_link).to_have_attribute("href", customer.get_absolute_url())
        preview_link.click()
        self.assertTrue(
            self.page.url.endswith(customer.get_absolute_url()),
            self.page.url,
        )

    def test_navigate_button_when_one_to_many_row_has_id(self):
        """
        UC: We want to be able to navigate to a row when a one-to-many widget has a row with an ID
        
        Expected Result: 
            - Hovering over the row launches the object preview
            - Clicking the navigate button takes you to the object detail view
        """
        #1. step_1
    
    #---------------------------------------
    # Test Pagination
    #---------------------------------------
    def test_pagination(self):
        """
        Use case: Navigate a one-to-many widget containing more than ten rows.
        Expected result: Ten rows are shown per page and the next page is reachable.
        """
        # 1. Open a country form with twenty customer rows.
        rows = [{"first_name": f"Customer {index}"} for index in range(20)]
        self.goto(self.get_url_with_rows(rows))

        # 2. Verify the first page shows ten rows and the correct page status.
        expect(self.get_rows()).to_have_count(20)
        expect(self.get_rows(visible=True)).to_have_count(10)
        expect(self.get_widget().locator("[data-one-to-many-page-status]")).to_have_text(
            "1 / 2"
        )
        expect(
            self.get_rows(visible=True).first.locator(
                '[data-one-to-many-cell="first_name"] input'
            )
        ).to_have_value("Customer 0")

        # 3. Move to page two and verify the next ten rows are displayed.
        self.get_widget().locator("[data-one-to-many-next-page]").click()
        expect(self.get_rows(visible=True)).to_have_count(10)
        expect(self.get_widget().locator("[data-one-to-many-page-status]")).to_have_text(
            "2 / 2"
        )
        expect(
            self.get_rows(visible=True).first.locator(
                '[data-one-to-many-cell="first_name"] input'
            )
        ).to_have_value("Customer 10")

    #---------------------------------------
    # Test Sorting
    #---------------------------------------
    def test_sorting_on_non_numeric_column(self):
        """
        Use case: Sort a text column from its column actions menu.
        Expected result: Rows can be sorted ascending and then descending by text.
        """
        # 1. Open three rows in an intentionally unsorted order.
        self.goto(
            self.get_url_with_rows(
                [{"first_name": "B"}, {"first_name": "A"}, {"first_name": "C"}]
            )
        )

        # 2. Sort the first-name column ascending.
        self.open_column_actions("first_name").get_by_role(
            "button", name="Sort ascending"
        ).click()
        self.assertEqual(self.get_column_values("first_name"), ["A", "B", "C"])

        # 3. Sort the same column descending.
        self.open_column_actions("first_name").get_by_role(
            "button", name="Sort descending"
        ).click()
        self.assertEqual(self.get_column_values("first_name"), ["C", "B", "A"])

    def test_sorting_on_numeric_column(self):
        """
        Use case: Sort a numeric inline column from its column actions menu.
        Expected result: Numeric values are ordered by magnitude rather than as text.
        """
        # 1. Open three customer rows with unsorted ages.
        self.goto(self.get_url_with_rows([{"age": 30}, {"age": 20}, {"age": 40}]))

        # 2. Sort ages ascending and verify numeric order.
        self.open_column_actions("age").get_by_role(
            "button", name="Sort ascending"
        ).click()
        self.assertEqual(self.get_column_values("age"), ["20", "30", "40"])

        # 3. Sort ages descending and verify the reverse order.
        self.open_column_actions("age").get_by_role(
            "button", name="Sort descending"
        ).click()
        self.assertEqual(self.get_column_values("age"), ["40", "30", "20"])

    #---------------------------------------
    # Test Autofill
    #---------------------------------------
    def test_autofill_non_numeric_column(self):
        """
        Use case: Autofill a text column from the value in its first row.
        Expected result: Every subsequent row receives the first text value.
        """
        # 1. Open three rows where only the first name is populated.
        self.goto(
            self.get_url_with_rows(
                [{"first_name": "Ada"}, {"first_name": ""}, {"first_name": ""}]
            )
        )

        # 2. Use the direct Autofill action for the text column.
        self.open_column_actions("first_name").get_by_role(
            "button", name="Autofill", exact=True
        ).click()

        # 3. Verify the first value was copied to the remaining rows.
        self.assertEqual(self.get_column_values("first_name"), ["Ada", "Ada", "Ada"])

    def test_autofill_numeric_column_increment(self):
        """
        Use case: Autofill a numeric column by incrementing its first value.
        Expected result: Each subsequent row increases the first value by one.
        """
        # 1. Open three rows where only the first age is populated.
        self.goto(self.get_url_with_rows([{"age": 20}, {"age": ""}, {"age": ""}]))

        # 2. Open the numeric Autofill submenu and choose increment.
        actions = self.open_column_actions("age")
        actions.get_by_role("button", name="Autofill", exact=True).click()
        self.page.get_by_role("button", name="Increment first value").click()

        # 3. Verify the generated numeric sequence.
        self.assertEqual(self.get_column_values("age"), ["20", "21", "22"])

    def test_autofill_date_column_increment(self):
        """
        Use case: Autofill a date column by incrementing its first value.
        Expected result: Each subsequent row advances the first date by one day.
        """
        # 1. Open three rows where only the first join date is populated.
        self.goto(
            self.get_url_with_rows(
                [
                    {"date_joined": "2026-08-04"},
                    {"date_joined": ""},
                    {"date_joined": ""},
                ]
            )
        )

        # 2. Open the date Autofill submenu and choose increment.
        actions = self.open_column_actions("date_joined")
        actions.get_by_role("button", name="Autofill", exact=True).click()
        self.page.get_by_role("button", name="Increment first value").click()

        # 3. Verify the generated daily sequence.
        self.assertEqual(
            self.get_column_values("date_joined"),
            ["2026-08-04", "2026-08-05", "2026-08-06"],
        )

    #---------------------------------------
    # Test Totals
    #---------------------------------------
    def test_totals_on_numeric_column(self):
        """
        Use case: Display totals when the one-to-many layout enables them.
        Expected result: The footer shows the sum of every numeric column value.
        """
        # 1. Open three rows while show_totals is enabled in the field layout.
        self.goto(self.get_url_with_rows([{"age": 30}, {"age": 20}, {"age": 40}]))

        # 2. Verify the age total is rendered beneath the widget.
        expect(self.get_widget().locator('[data-one-to-many-total="age"]')).to_have_text(
            "90"
        )

    #---------------------------------------
    # Test Reset Button
    #---------------------------------------
    def test_reset_button_preserves_foreign_keys_if_initial_state(self):
        """
        Use case: Reset an edited one-to-many row containing a foreign key.
        Expected result: Native and foreign-key values return to their initial state.
        """
        # 1. Open a row containing both a native value and a foreign key.
        self.goto(
            self.get_url_with_rows(
                [
                    {
                        "first_name": "Ada",
                        "customer_type": self.customer_type.pk,
                    }
                ]
            )
        )

        # 2. Change a value inside the one-to-many row.
        first_name = self.get_rows().first.locator(
            '[data-one-to-many-cell="first_name"] input'
        )
        first_name.fill("Changed")
        expect(first_name).to_have_value("Changed")

        # 3. Click the reset button.
        self.press_reset_button()

        # 4. Verify both the native and foreign-key values were restored.
        expect(self.get_rows()).to_have_count(1)
        expect(
            self.get_rows().first.locator(
                '[data-one-to-many-cell="first_name"] input'
            )
        ).to_have_value("Ada")
        customer_type_cell = self.get_rows().first.locator(
            '[data-one-to-many-cell="customer_type"]'
        )
        expect(
            customer_type_cell.locator(
                'input[type="hidden"][data-generated="true"]'
            )
        ).to_have_value(str(self.customer_type.pk))
        expect(customer_type_cell.locator(".foreign-field-selected")).to_contain_text(
            "Retail"
        )
        
    #---------------------------------------
    # Test Reset Button
    #---------------------------------------
