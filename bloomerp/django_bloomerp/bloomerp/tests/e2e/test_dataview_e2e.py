from typing import Pattern

import pytest
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.urls import reverse
from playwright.sync_api import Locator, Page, expect

from bloomerp.dataviews.registry import DATAVIEW_REGISTRY
from bloomerp.management.commands import save_application_fields
from bloomerp.models import ApplicationField
from bloomerp.models.users.user_list_view_preference import UserListViewPreference
from bloomerp.models import ApplicationField, Sidebar, SidebarItem
from bloomerp.tests.base import BaseBloomerpTestCaseWithModels
from bloomerp.tests.utils.dynamic_models import create_test_models
from bloomerp.utils.models import get_list_view_url


# ------------------------------------
# Fixtures
# ------------------------------------
@pytest.fixture
def dataview_model(db):
    models_by_name = create_test_models(
        app_label="bloomerp",
        model_defs={
            "E2ECustomer": {
                "first_name": models.CharField(max_length=100),
                "last_name": models.CharField(max_length=100),
                "age": models.IntegerField(),
                "__str__": lambda self: f"{self.first_name} {self.last_name}",
            }
        },
        use_bloomerp_base=True,
    )
    Customer = models_by_name["E2ECustomer"]
    BaseBloomerpTestCaseWithModels._register_dynamic_model_routes([Customer])

    Customer.objects.all().delete()
    Customer.objects.create(first_name="Playwright", last_name="Target", age=41)
    Customer.objects.create(first_name="Filtered", last_name="Away", age=25)
    Customer.objects.create(first_name="Another", last_name="Away", age=31)

    save_application_fields.Command().handle(suppress_output=True)
    return Customer


@pytest.fixture
def dataview_admin(db):
    User = get_user_model()
    user, _created = User.objects.update_or_create(
        username="dataview-admin",
        defaults={
            "email": "dataview-admin@example.com",
            "is_staff": True,
            "is_superuser": True,
            "is_active": True,
        },
    )
    user.set_password("testpass123")
    user.save()
    return user


@pytest.fixture
def nested_relation_dataview(db):
    Project = create_test_models(
        app_label="bloomerp",
        model_defs={
            "E2EFilterProject": {
                "name": models.CharField(max_length=100),
                "__str__": lambda self: self.name,
            },
        },
        use_bloomerp_base=True,
    )["E2EFilterProject"]
    Employee = create_test_models(
        app_label="bloomerp",
        model_defs={
            "E2EFilterEmployee": {
                "name": models.CharField(max_length=100),
                "__str__": lambda self: self.name,
            },
        },
        use_bloomerp_base=True,
    )["E2EFilterEmployee"]
    EmployeeOnProject = create_test_models(
        app_label="bloomerp",
        model_defs={
            "E2EEmployeeOnProject": {
                "employee": models.ForeignKey(
                    Employee,
                    on_delete=models.CASCADE,
                    related_name="employee_on_project",
                ),
                "project": models.ForeignKey(Project, on_delete=models.CASCADE),
            },
        },
        use_bloomerp_base=True,
    )["E2EEmployeeOnProject"]
    BaseBloomerpTestCaseWithModels._register_dynamic_model_routes([Employee])

    selected_project = Project.objects.create(name="Selected project")
    other_project = Project.objects.create(name="Other project")
    selected_employee = Employee.objects.create(name="Selected employee")
    other_employee = Employee.objects.create(name="Other employee")
    EmployeeOnProject.objects.create(
        employee=selected_employee,
        project=selected_project,
    )
    EmployeeOnProject.objects.create(
        employee=other_employee,
        project=other_project,
    )

    save_application_fields.Command().handle(suppress_output=True)
    return Employee, selected_project


@pytest.fixture
def authenticated_dataview_page(
    page: Page,
    live_server_url: str,
    dataview_admin,
    dataview_model,
):
    content_type = ContentType.objects.get_for_model(dataview_model)
    UserListViewPreference.objects.filter(
        user=dataview_admin,
        content_type=content_type,
    ).delete()

    page.goto(f"{live_server_url}/login/")
    page.locator('input[name="username"]').fill(dataview_admin.username)
    page.locator('input[name="password"]').fill("testpass123")
    page.get_by_role("button", name="Login").click()
    page.wait_for_url(f"{live_server_url}/")

    page.goto(f"{live_server_url}{reverse(get_list_view_url(dataview_model))}")
    expect(page.locator("[bloomerp-component='dataview-container']")).to_be_visible()
    expect(page.locator("#data-view-data-section")).to_contain_text("Playwright")
    return page


@pytest.fixture
def authenticated_nested_relation_dataview_page(
    page: Page,
    live_server_url: str,
    dataview_admin,
    nested_relation_dataview,
):
    Employee, selected_project = nested_relation_dataview

    page.goto(f"{live_server_url}{reverse('login')}")
    page.locator('input[name="username"]').fill(dataview_admin.username)
    page.locator('input[name="password"]').fill("testpass123")
    page.get_by_role("button", name="Login").click()
    page.wait_for_url(f"{live_server_url}/")

    page.goto(f"{live_server_url}{reverse(get_list_view_url(Employee))}")
    expect(page.locator("[bloomerp-component='dataview-container']")).to_be_visible()
    return page, selected_project

#------------------------------------
# Utility Functions
#------------------------------------
def get_dataview_section(page: Page) -> Locator:
    return page.locator("[id='data-view-data-section']").last


def _apply_first_name_filter(page: Page, value: str, response_timeout: int = 30000) -> None:
    page.get_by_role("button", name="Filter").click()

    filter_container = page.locator("[bloomerp-component='filter-container']").first
    filter_container.locator("#field-selector-section select").select_option(label="First Name")
    expect(filter_container.locator("#lookup-operator-section select")).to_be_visible()

    filter_container.locator("#lookup-operator-section select").select_option(label="Equals")
    value_input = filter_container.locator("#value-input-section input[name='first_name']")
    expect(value_input).to_be_visible()
    value_input.fill(value)

    with page.expect_response(
        lambda response: "components/dataview" in response.url,
        timeout=response_timeout,
    ):
        page.locator("#apply-filters-button").click()

    expect(page.locator("#data-view-data-section").last).to_contain_text(value)


def apply_filter(page: Page, filter_key: str, filter_value: str, response_timeout: int = 30000) -> None:
    page.get_by_role("button", name="Filter").click()

    filter_container = page.locator("[bloomerp-component='filter-container']").first
    field_label = filter_key.replace("_", " ").title()
    filter_container.locator("#field-selector-section select").select_option(label=field_label)
    expect(filter_container.locator("#lookup-operator-section select")).to_be_visible()

    filter_container.locator("#lookup-operator-section select").select_option(label="Equals")
    value_input = filter_container.locator(f"#value-input-section input[name='{filter_key}']")
    expect(value_input).to_be_visible()
    value_input.fill(filter_value)

    with page.expect_response(
        lambda response: "components/dataview" in response.url,
        timeout=response_timeout,
    ):
        page.locator("#apply-filters-button").click()

    expect(page.locator("#data-view-data-section").last).to_contain_text(filter_value)

def _change_to_card_view_by_clicking_display_options(page: Page) -> None:
    page.get_by_role("button", name="Display").click()
    display_menu = page.locator("div[role='menu']:visible").filter(
        has=page.locator("button[data-display-options-values*='\"view_type\": \"card\"']")
    )

    with page.expect_response(
        lambda response: "change_data_view_preference" in response.url,
        timeout=5000,
    ):
        display_menu.locator("button[data-display-options-values*='\"view_type\": \"card\"']").click()

    expect(page.locator("[bloomerp-component='dataview-container']")).to_have_attribute(
        "data-view-type", "card"
    )
    expect(page.locator("[bloomerp-component='card-view']")).to_be_visible()


def search(
    query: str,
    page: Page,
    response_timeout: int = 30000,
    expected_result_text: str | None = None,
) -> None:
    search_input = page.locator("[id^='data-view-search-input-']")
    expect(search_input).to_be_visible()

    search_input.fill("")
    search_input.click()

    with page.expect_response(
        lambda response: "components/dataview" in response.url and f"q={query}" in response.url,
        timeout=response_timeout,
    ):
        page.keyboard.type(query, delay=20)

    expect(search_input).to_have_value(query)
    expect(get_dataview_section(page)).to_contain_text(
        expected_result_text or query,
        timeout=response_timeout,
    )


def change_view_type(view_type, page: Page) -> None:
    page.get_by_role("button", name="Display").click()
    display_menu = page.locator("div[role='menu']:visible").filter(
        has=page.locator(f"button[data-display-options-values*='\"view_type\": \"{view_type.value.key}\"']")
    )

    with page.expect_response(
        lambda response: "change_data_view_preference" in response.url,
        timeout=5000,
    ):
        display_menu.locator(f"button[data-display-options-values*='\"view_type\": \"{view_type.value.key}\"']").click()

    expect(page.locator("[bloomerp-component='dataview-container']")).to_have_attribute(
        "data-view-type", view_type.value.key
    )

def toggle_field_visibility(field_name: str, page: Page) -> None:
    page.get_by_role("button", name="Display").click()
    display_menu = page.locator("div[role='menu']:visible").filter(
        has=page.locator(f"button[data-display-options-values*='\"view_type\": \"table\"']")
    )

    with page.expect_response(
        lambda response: "change_data_view_preference" in response.url,
        timeout=5000,
    ):
        display_menu.get_by_role("button", name=field_name).click()


def get_display_options_menu(page: Page) -> Locator:
    page.get_by_role("button", name="Display").click()
    display_menu = page.locator("div[role='menu']:visible").filter(
        has=page.locator("button[data-display-options-values*='\"view_type\": \"table\"']")
    )
    return display_menu

def go_page_back(
    page: Page,
    *,
    expected_url: str | Pattern[str] | None = None,
    expected_selector: str | None = None,
    timeout: int = 5000,
) -> None:
    """
    Simulate pressing the browser back arrow.

    Use expected_url and/or expected_selector when the test needs to assert the
    destination after the browser history entry is restored.
    """
    page.go_back(wait_until="domcontentloaded", timeout=timeout)

    if expected_url is not None:
        expect(page).to_have_url(expected_url, timeout=timeout)

    if expected_selector is not None:
        expect(page.locator(expected_selector)).to_be_visible(timeout=timeout)


def refresh_page(page: Page, expected_selector: str, timeout: int = 5000) -> None:
    """
    Refresh the page and wait for the expected selector to be visible.

    This is useful to ensure that the page has fully reloaded before proceeding with further actions or assertions.
    """
    page.reload(wait_until="domcontentloaded", timeout=timeout)
    expect(page.locator(expected_selector)).to_be_visible(timeout=timeout)

@pytest.mark.django_db(transaction=True)
class TestDataViewE2E:
    
    # ------------------------------------
    # Filter Tests
    # ------------------------------------
    def test_dataview_filters_data(
        self,
        authenticated_dataview_page: Page,
    ):
        """
        Tests whether the dataview correctly filters the data based on the user input.
        """
        page = authenticated_dataview_page

        _apply_first_name_filter(page, "Playwright")

        data_section = page.locator("#data-view-data-section").last
        expect(data_section).to_contain_text("Playwright Target")
        expect(data_section).not_to_contain_text("Filtered Away")
        expect(page.locator("[data-filter-key='first_name__exact']").last).to_contain_text(
            "First Name is Playwright"
        )

    def test_nested_foreign_widget_filter_uses_nested_exact_operator(
        self,
        authenticated_nested_relation_dataview_page,
    ):
        """
        Use case: Filter a reverse relation through a nested foreign-key widget.
        Expected result: The full nested path is serialized with the nested Equals lookup.
        """
        page, selected_project = authenticated_nested_relation_dataview_page
        page.get_by_role("button", name="Filter").click()

        filter_container = page.locator("[bloomerp-component='filter-container']").first
        filter_container.locator("#field-selector-section select").select_option(
            label="Employee On Project"
        )
        outer_operator = filter_container.locator("#lookup-operator-section select")
        expect(outer_operator).to_be_visible()
        outer_operator.select_option(label="Advanced Lookup")

        related_field = filter_container.locator(
            'select[data-advanced-related-select][data-path-prefix="employee_on_project"]'
        )
        expect(related_field).to_be_visible()
        related_field.select_option(label="Project")

        nested_operator = filter_container.locator(
            'select[data-advanced-operator-select][data-field="employee_on_project__project"]'
        )
        expect(nested_operator).to_be_visible()
        nested_operator.select_option(label="Equals")

        project_widget = filter_container.locator(
            '[data-filter-value-provider][data-field-name="employee_on_project__project"]'
        )
        expect(project_widget).to_be_visible()
        project_widget.locator('input[type="text"]').focus()
        project_option = page.locator(
            ".foreign-field-results li",
            has_text=selected_project.name,
        )
        expect(project_option).to_be_visible()
        project_option.click()

        with page.expect_response(
            lambda response: "components/dataview" in response.url
            and "employee_on_project__project__exact=" in response.url,
            timeout=30000,
        ):
            page.locator("#apply-filters-button").click()

        data_section = page.locator("#data-view-data-section").last
        expect(data_section).to_contain_text("Selected employee")
        expect(data_section).not_to_contain_text("Other employee")

    def test_search(self, authenticated_dataview_page: Page):
        """
        Tests whether the dataview search functionality correctly filters the data based on the search query.
        """
        page = authenticated_dataview_page

        search("Playwright", page)

        data_section = page.locator("#data-view-data-section").last
        expect(data_section).to_contain_text("Playwright Target")
        expect(data_section).not_to_contain_text("Filtered Away")
        expect(page.locator("[id^='data-view-search-input-']")).to_have_value("Playwright")
    
    def test_dataview_filters_data_after_changing_display_options(
        self,
        authenticated_dataview_page: Page,
    ):
        """
        Tests whether the dataview correctly filters the data after changing display options.
        """
        page = authenticated_dataview_page

        _change_to_card_view_by_clicking_display_options(page)

        _apply_first_name_filter(page, "Playwright", response_timeout=5000)

        data_section = page.locator("#data-view-data-section").last
        expect(data_section).to_contain_text("Playwright Target")
        expect(data_section).not_to_contain_text("Filtered Away")
        expect(page.locator("[bloomerp-component='card-view-card']")).to_have_count(1)

    
    # ------------------------------------
    # Display Options Tests
    # ------------------------------------
    def test_pivot_selectors_persist_multiple_row_and_value_fields(
        self,
        authenticated_dataview_page: Page,
        dataview_admin,
        dataview_model,
    ):
        """
        Use case: A user selects multiple row dimensions and values for a pivot table.
        Expected result: Every selected field is submitted and persisted in selector order.
        """
        page = authenticated_dataview_page

        # 1. Switch to the pivot view and locate its native row-field selector.
        change_view_type(DATAVIEW_REGISTRY.get("pivot_table"), page)
        display_menu = page.locator("div[role='menu']:visible").filter(
            has=page.locator("select[name='row_field_ids']")
        )

        # 2. Select both row dimensions in one native multiple-select change.
        row_selector = display_menu.locator("select[name='row_field_ids']")
        with page.expect_response(
            lambda response: "change_data_view_preference" in response.url,
            timeout=5000,
        ):
            row_selector.select_option(label=["First Name", "Last Name"])

        # 3. Select two value fields after the display options re-render.
        display_menu = page.locator("div[role='menu']:visible").filter(
            has=page.locator("select[name='value_field_ids']")
        )
        value_selector = display_menu.locator("select[name='value_field_ids']")
        with page.expect_response(
            lambda response: "change_data_view_preference" in response.url,
            timeout=5000,
        ):
            value_selector.select_option(label=["First Name", "Age"])

        # 4. Verify both row and value field lists were persisted.
        content_type = ContentType.objects.get_for_model(dataview_model)
        preference = UserListViewPreference.objects.get(
            user=dataview_admin,
            content_type=content_type,
            selected=True,
        )
        assert preference.options["pivot_table"]["row_field_ids"] == [
            ApplicationField.get_by_field(dataview_model, "first_name").id,
            ApplicationField.get_by_field(dataview_model, "last_name").id,
        ]
        assert preference.options["pivot_table"]["value_field_ids"] == [
            ApplicationField.get_by_field(dataview_model, "first_name").id,
            ApplicationField.get_by_field(dataview_model, "age").id,
        ]

    def test_change_visible_fields(self, authenticated_dataview_page: Page):
        """
        Tests whether the dataview correctly changes the visible fields based on the user input.
        """
        # 1. Click the "Display" button to open the display options menu.
        page = authenticated_dataview_page
        page.get_by_role("button", name="Display").click()
        
        # 2. Fetch the display menu 
        display_menu = page.locator("div[role='menu']:visible").filter(
            has=page.locator("button[data-display-options-values*='\"view_type\": \"table\"']")
        )
        
        # 3. Click on one of the visible fields
        with page.expect_response(
            lambda response: "change_data_view_preference" in response.url,
            timeout=5000,
        ):
            display_menu.get_by_role("button", name="Datetime Created").click()
            
        # 4. Assert that this field is visible in the table
        expect(page.locator("[bloomerp-component='dataview-container']")).to_have_attribute(
            "data-view-type", "table"
        )
        
        # 5. Assert that the "Datetime Created" field is visible in the table
        expect(get_dataview_section(page)).to_contain_text("Datetime Created")
        
    
    def test_search_working_after_toggling_field(self, authenticated_dataview_page: Page):
        """
        Tests whether the dataview search functionality works after changing display options.
        """
        page = authenticated_dataview_page
        
        toggle_field_visibility("First Name", page)
        
        search("Playwright", page, response_timeout=5000, expected_result_text="Target")

        data_section = get_dataview_section(page)
        expect(data_section).to_contain_text("Target")
        expect(data_section).not_to_contain_text("Filtered Away")
        
        
    def test_split_view_toggle(self, authenticated_dataview_page: Page):
        """
        Tests whether the dataview split view toggle works correctly.
        """
        page = authenticated_dataview_page

        # 1. Fetch the display menu
        display_menu = get_display_options_menu(page)
        
        # 2. Click on the "Split View" option
        with page.expect_response(
            lambda response: "change_data_view_preference" in response.url,
            timeout=5000,
        ):
            display_menu.get_by_role("button", name="Split View").click()
            
        # 3. Assert that the split view is now active
        expect(page.locator("[bloomerp-component='dataview-container']")).to_have_attribute(
            "data-split-view-enabled", "True"
        )
        
        # 4. Check if the split view is really showing something
        expect(page.locator("[data-split-view-container]")).to_be_visible()
        
    
    def test_save_filters(self, authenticated_dataview_page: Page, dataview_admin, dataview_model):
        """
        Tests whether the dataview save filters functionality works correctly.
        """
        page = authenticated_dataview_page

        _apply_first_name_filter(page, "Playwright")

        # 1. Click the direct default-filter "Save" button
        with page.expect_response(
            lambda response: "change_data_view_preference" in response.url,
            timeout=5000,
        ):
            page.get_by_role("button", name="Save").click()

        # 2. Assert that the filter is saved on the selected preference
        content_type = ContentType.objects.get_for_model(dataview_model)
        preference = UserListViewPreference.objects.get(
            user=dataview_admin,
            content_type=content_type,
            selected=True,
        )
        assert preference.default_filters == {"first_name__exact": "Playwright"}

        # 3. The saved default filter is rendered as a non-removable applied filter.
        applied_filters = page.locator("[data-applied-filters-section]")
        expect(applied_filters.locator("[data-filter-key='first_name__exact']")).to_have_count(1)
        expect(applied_filters.locator("button", has_text="Save")).to_have_count(0)


    def test_default_filters_are_saved_and_applied_after_refresh(
        self,
        authenticated_dataview_page: Page,
        live_server_url: str,
        dataview_admin,
        dataview_model,
    ):
        """
        Tests whether saved default filters are persisted and applied on a clean page load.
        """
        page = authenticated_dataview_page

        # 1. User filters
        _apply_first_name_filter(page, "Playwright")

        data_section = get_dataview_section(page)
        expect(data_section).to_contain_text("Playwright Target")
        expect(data_section).not_to_contain_text("Filtered Away")

        # 2. User presses save
        with page.expect_response(
            lambda response: "change_data_view_preference" in response.url,
            timeout=5000,
        ):
            page.get_by_role("button", name="Save").click()

        # 3. Check in db if filter is saved
        content_type = ContentType.objects.get_for_model(dataview_model)
        preference = UserListViewPreference.objects.get(
            user=dataview_admin,
            content_type=content_type,
            selected=True,
        )
        assert preference.default_filters == {"first_name__exact": "Playwright"}

        # 4. User refreshes the page without queryparameters
        page.goto(f"{live_server_url}{reverse(get_list_view_url(dataview_model))}")

        # 5. Check if default filter is applied
        expect(page.locator("[bloomerp-component='dataview-container']")).to_be_visible()
        data_section = get_dataview_section(page)
        expect(data_section).to_contain_text("Playwright Target")
        expect(data_section).not_to_contain_text("Filtered Away")
        
    
    def test_search_after_saving_default_filter(self, authenticated_dataview_page: Page):
        """
        Tests whether the dataview search functionality works after saving a default filter.
        """
        page = authenticated_dataview_page

        apply_filter(page, "last_name", "Away", response_timeout=5000)

        # 2. Click the "Save" button
        with page.expect_response(
            lambda response: "change_data_view_preference" in response.url,
            timeout=5000,
        ):
            page.get_by_role("button", name="Save").click()
        
        # 3. Perform a search
        search("Another", page)

        # 4. Assert that the search results are correct
        data_section = get_dataview_section(page)
        expect(data_section).to_contain_text("Another Away")
        expect(data_section).not_to_contain_text("Filtered Away")
            
    
    def test_saving_default_filter_resolves_conflicts_with_existing_saved_filters(self, authenticated_dataview_page: Page):
        """
        Tests whether saving a default filter correctly resolves conflicts with existing saved filters.
        """
        page = authenticated_dataview_page

        apply_filter(page, "last_name", "Away", response_timeout=5000)

        # 2. Click the "Save" button
        with page.expect_response(
            lambda response: "change_data_view_preference" in response.url,
            timeout=5000,
        ):
            page.get_by_role("button", name="Save").click()
        
        # 3. Refresh page
        refresh_page(page, expected_selector="[bloomerp-component='dataview-container']")
        
        # 4.1 Last Name is Away should appear only ONCE in the applied filters section
        applied_filters = page.locator("[data-applied-filters-section]")
        expect(applied_filters.locator("[data-filter-key='last_name__exact']")).to_have_count(1)
        
        # 4.2 There should be NO save button as the default filter is already saved
        expect(applied_filters.locator("button", has_text="Save")).to_have_count(0)
        
        # 5. Filter again on a different value and save default filter again
        apply_filter(page, "first_name", "Another", response_timeout=5000)
        
        # 6. Assert that the save button appears
        expect(applied_filters.locator("button", has_text="Save")).to_be_visible()
        
        
    def test_clear_one_filter(self, authenticated_dataview_page: Page):
        """
        Tests whether the dataview clear filter functionality works correctly when clearing one filter.
        """
        page = authenticated_dataview_page

        _apply_first_name_filter(page, "Playwright")

        # 1. Click the "Clear" button for the applied filter
        aria_label = "Remove filter"
        page.get_by_role("button", name=aria_label).click()
        
        # 2. Assert that the filter is cleared and the data is updated accordingly
        expect(page.locator("[bloomerp-component='dataview-container']")).to_be_visible()
        
        # 3. Assert that the "Another Away" and "Filtered Away" entries are visible again
        data_section = page.locator("#data-view-data-section").last
        expect(data_section).to_contain_text("Another Away")
        expect(data_section).to_contain_text("Filtered Away")
        
        
    def test_clear_filter_and_go_back_has_full_dataview(self, authenticated_dataview_page: Page):
        """
        Tests whether the dataview clear filter functionality works correctly when clearing one filter and then going back in browser history.
        """
        page = authenticated_dataview_page

        _apply_first_name_filter(page, "Playwright")

        # 1. Click the "Clear" button for the applied filter
        page.get_by_role("button", name="Clear all").click()
        
        # 2. Go back in browser history
        go_page_back(page)
        
        # 3. Assert that the bloomerp-component="dataview-container" is still visible
        expect(page.locator("[bloomerp-component='dataview-container']")).to_be_visible()

    def test_mixed_htmx_and_href_history_restores_complete_pages(
        self,
        authenticated_dataview_page: Page,
        dataview_admin,
        dataview_model,
        live_server_url: str,
    ):
        """
        Use case: An HTMX sidebar navigation is followed by a normal href navigation and browser back actions.
        Expected result: History never restores a loader or an HTMX fragment as the complete document.
        """
        page = authenticated_dataview_page
        list_path = reverse(get_list_view_url(dataview_model))

        # 1. Add an internal sidebar link so the first navigation uses HTMX and the global loader.
        sidebar = Sidebar.objects.filter(user=dataview_admin, selected=True).first()
        if sidebar is None:
            sidebar = Sidebar.objects.create(user=dataview_admin, name="History", selected=True)
        SidebarItem.create_link(sidebar, "History list", list_path)
        page.goto(f"{live_server_url}/")

        with page.expect_response(lambda response: response.url.endswith(list_path)):
            page.get_by_role("link", name="History list").click()
        expect(page.locator("[bloomerp-component='dataview-container']")).to_be_visible()

        # 2. Follow a plain href, reproducing the mixed navigation sequence from link tiles.
        page.locator("#main-content").evaluate(
            """element => {
                const link = document.createElement('a');
                link.id = 'plain-home-link';
                link.href = '/';
                link.textContent = 'Plain home link';
                element.appendChild(link);
            }"""
        )
        page.get_by_role("link", name="Plain home link").click()
        expect(page).to_have_url(f"{live_server_url}/")

        # 3. Go back through both entries and verify the outgoing home snapshot was not the loader.
        go_page_back(page, expected_selector="[bloomerp-component='dataview-container']")
        go_page_back(page, expected_url=f"{live_server_url}/")
        expect(page.locator(".skeleton-loader")).to_have_count(0)

        # 4. Refresh the restored entry and verify a complete document is returned, not an HTMX fragment.
        page.reload(wait_until="domcontentloaded")
        expect(page.locator("html > body#bloomerpBody")).to_have_count(1)
        expect(page.locator("#main-content #htmx-addendum")).to_be_visible()
    
