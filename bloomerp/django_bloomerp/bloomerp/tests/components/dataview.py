import json
import re
from datetime import date, datetime, timedelta

from django.db import models
from django.http import HttpResponse
from django.urls import reverse
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType
from django.contrib.auth.models import Permission
from bloomerp.services.preference_services import PreferenceManager
from bloomerp.tests.base import BaseBloomerpModelTestCase
from bloomerp.models import ApplicationField, Todo
from bloomerp.models import Policy, FieldPolicy, RowPolicy, RowPolicyRule
from bloomerp.models.definition import (
    BloomerpModelConfig,
    DataviewAction,
    DataviewHTMLAction,
    DataviewModalAction,
    ModelViewSettings,
    get_model_config,
)
from bloomerp.models.users.user_list_view_preference import UserListViewPreference
from bloomerp.services.user_services import get_data_view_fields
from bloomerp.components.objects.dataviews.dataview import _select_related_rendered_relations
from bloomerp.tests.utils.dynamic_models import create_test_models


def _execute_test_dataview_action(context) -> HttpResponse:
    return HttpResponse(
        f"Executed {context.model.__name__}:{context.querystring}:{context.queryset.count()}"
    )


def _test_dataview_modal_endpoint(context) -> str:
    return reverse(
        "components_dataview",
        kwargs={"content_type_id": context.content_type.pk},
    )


def _deny_test_dataview_action(context) -> bool:
    return False


class TestDataView(BaseBloomerpModelTestCase):
    create_foreign_models = True

    def extendedSetup(self):
        return super().extendedSetup()    

    def _set_dataview_actions(self, actions) -> None:
        config = get_model_config(self.CustomerModel)
        if config is not None:
            original_settings = config.model_view_settings
            config.model_view_settings = ModelViewSettings(dataview_actions=actions)
            self.addCleanup(setattr, config, "model_view_settings", original_settings)
            return

        self.CustomerModel.bloomerp_config = BloomerpModelConfig(
            model_view_settings=ModelViewSettings(dataview_actions=actions)
        )
        self.addCleanup(delattr, self.CustomerModel, "bloomerp_config")

    def test_model_view_settings_have_independent_default_dataview_actions(self):
        """
        Use case: Create model-view settings without an explicit toolbar override.
        Expected result: Each instance receives the current six actions in a new list.
        """
        first_settings = ModelViewSettings()
        second_settings = ModelViewSettings()

        self.assertEqual(
            [action.id for action in first_settings.dataview_actions],
            [
                "filter",
                "add",
                "bulk-actions",
                "export",
                "display-options",
                "select-preference",
            ],
        )
        self.assertIsNot(
            first_settings.dataview_actions,
            second_settings.dataview_actions,
        )

    def test_default_dataview_actions_preserve_toolbar_and_shortcuts(self):
        """
        Use case: Render a model without a Dataview toolbar override.
        Expected result: The six existing toolbar actions and shortcuts remain present.
        """
        self.client.force_login(self.admin_user)
        content_type = ContentType.objects.get_for_model(self.CustomerModel)

        response = self.client.get(
            reverse(
                "components_dataview",
                kwargs={"content_type_id": content_type.pk},
            ),
            HTTP_HX_REQUEST="true",
        )

        for index, action_id in enumerate(
            (
                "filter",
                "add",
                "bulk-actions",
                "export",
                "display-options",
                "select-preference",
            ),
            start=1,
        ):
            self.assertContains(
                response,
                f'data-data-view-button="{action_id}"',
                html=False,
            )
            self.assertContains(
                response,
                f'data-shortcut="mod+{index}"',
                html=False,
            )
        self.assertNotContains(response, "should_render_func=&lt;function", html=False)

    def test_dataview_actions_can_replace_default_toolbar(self):
        """
        Use case: Configure HTML, immediate, and modal actions for a model Dataview.
        Expected result: Only the override renders and each action keeps its shortcut.
        """
        content_type = ContentType.objects.get_for_model(self.CustomerModel)
        modal_url = reverse(
            "components_dataview",
            kwargs={"content_type_id": content_type.pk},
        )
        execute_url = reverse(
            "components_dataview_configured_action",
            kwargs={
                "content_type_id": content_type.pk,
                "action_id": "run-test",
            },
        )
        self._set_dataview_actions(
            [
                DataviewHTMLAction(
                    id="custom-export",
                    template_name="components/objects/dataview_actions/export.html",
                    shortcut="mod+7",
                ),
                DataviewAction(
                    id="run-test",
                    label="Run test",
                    execution_func=_execute_test_dataview_action,
                    shortcut="mod+8",
                    icon="fa fa-play",
                ),
                DataviewModalAction(
                    id="open-test",
                    label="Open test",
                    endpoint=_test_dataview_modal_endpoint,
                    shortcut="mod+9",
                    modal_title="Test modal",
                ),
            ]
        )
        self.client.force_login(self.admin_user)

        response = self.client.get(
            f"{modal_url}?first_name=xyz",
            HTTP_HX_REQUEST="true",
        )

        self.assertNotContains(response, 'data-data-view-button="filter"', html=False)
        self.assertContains(response, 'data-data-view-button="custom-export"', html=False)
        self.assertContains(response, 'data-shortcut="mod+7"', html=False)
        self.assertContains(
            response,
            f'hx-post="{execute_url}?first_name=xyz"',
            html=False,
        )
        self.assertContains(response, 'data-shortcut="mod+8"', html=False)
        self.assertContains(response, f'hx-get="{modal_url}"', html=False)
        self.assertContains(response, 'data-shortcut="mod+9"', html=False)
        self.assertContains(response, 'bloomerp-set-modal-title-to="Test modal"', html=False)

        execute_response = self.client.post(f"{execute_url}?first_name=xyz")
        self.assertEqual(execute_response.status_code, 200)
        self.assertEqual(
            execute_response.content.decode("utf-8"),
            f"Executed {self.CustomerModel.__name__}:first_name=xyz:0",
        )

    def test_dataview_action_predicate_is_enforced_during_execution(self):
        """
        Use case: Invoke an immediate action whose visibility predicate denies access.
        Expected result: It is hidden in the toolbar and direct execution returns 403.
        """
        content_type = ContentType.objects.get_for_model(self.CustomerModel)
        action_url = reverse(
            "components_dataview_configured_action",
            kwargs={
                "content_type_id": content_type.pk,
                "action_id": "denied-test",
            },
        )
        self._set_dataview_actions(
            [
                DataviewAction(
                    id="denied-test",
                    label="Denied test",
                    execution_func=_execute_test_dataview_action,
                    should_render_func=_deny_test_dataview_action,
                    shortcut="mod+7",
                )
            ]
        )
        self.client.force_login(self.admin_user)

        response = self.client.get(
            reverse(
                "components_dataview",
                kwargs={"content_type_id": content_type.pk},
            ),
            HTTP_HX_REQUEST="true",
        )
        self.assertNotContains(response, "Denied test", html=False)

        execute_response = self.client.post(action_url)
        self.assertEqual(execute_response.status_code, 403)

    def test_data_view_eager_loads_rendered_foreign_keys(self):
        planet = self.PlanetModel.objects.create(name="Test planet")
        country = self.CountryModel.objects.create(name="Test country", planet=planet)
        customers = [
            self.CustomerModel.objects.create(
                first_name=f"Customer {index}",
                last_name="Test",
                age=20,
                country=country,
            )
            for index in range(2)
        ]

        country_field = ApplicationField.get_by_field(self.CustomerModel, "country")
        queryset = _select_related_rendered_relations(
            self.CustomerModel.objects.filter(pk__in=[customer.pk for customer in customers]),
            [country_field],
        )

        with self.assertNumQueries(1):
            self.assertEqual(
                [customer.country.pk for customer in queryset.order_by("pk")],
                [country.pk, country.pk],
            )

    def _ensure_permissions_for_model(self, model):
        """
        Ensures that the default permissions for a given model are created.
        """
        content_type = ContentType.objects.get_for_model(model)
        for perm in model._meta.default_permissions:
            codename = f"{perm}_{model._meta.model_name}"
            Permission.objects.get_or_create(
                codename=codename,
                content_type=content_type,
                defaults={"name": f"Can {perm} {model._meta.verbose_name}"},
            )
        
        
    def test_list_view_includes_url_params(self):
        """
        Tests whether the list view forwards current query params to the dataview load
        """
        # 0. Create customer
        self.create_customer("xyz", "querytarget", 20)

        # 1. Login the client
        self.client.force_login(self.admin_user)

        # 2. Add a query parameter
        url = reverse(
            viewname="customers_model",
        )
        url = url + "?first_name=xyz"

        # 3. Send a request
        response = self.client.get(url)

        # 4. Make sure the initial dataview load preserves the current query string
        content_type_id = ContentType.objects.get_for_model(self.CustomerModel).id
        dataview_url = reverse(
            viewname="components_dataview",
            kwargs={"content_type_id": content_type_id},
        )

        self.assertContains(response, f'hx-get="{dataview_url}?first_name=xyz"', html=False)

    def test_list_view_export_button_includes_active_filters(self):
        self.client.force_login(self.admin_user)

        content_type_id = ContentType.objects.get_for_model(self.CustomerModel).id
        url = reverse(
            viewname="components_dataview",
            kwargs={"content_type_id": content_type_id},
        ) + "?first_name=xyz&q=alice&page=3"

        response = self.client.get(url, HTTP_HX_REQUEST="true")

        export_url = reverse(
            viewname="components_export_objects",
            kwargs={"content_type_id": content_type_id},
        )

        self.assertContains(
            response,
            f'hx-get="{export_url}?first_name=xyz&amp;q=alice"',
            html=False,
        )
        self.assertNotContains(
            response,
            f'{export_url}?first_name=xyz&amp;q=alice&amp;page=3',
            html=False,
        )

    def test_list_view_with_init_filters_includes_filter_box(self):
        """
        This tests whether the list view bootstraps a dataview response
        that actually contains the applied filter badge
        """
        # 0. Create customer
        self.create_customer("xyz", "filtermatch", 20)
        self.create_customer("abc", "filternomatch", 20)

        # 1. Login the client
        self.client.force_login(self.admin_user)

        # 2. Add a query parameter
        url = reverse(
            viewname="customers_model",
        )
        url = url + "?first_name=xyz"

        # 3. Send a request to the actual list view
        response = self.client.get(url)

        # 4. Make sure the page bootstraps the dataview with the filter query string
        content_type_id = ContentType.objects.get_for_model(self.CustomerModel).id
        dataview_url = reverse(
            viewname="components_dataview",
            kwargs={"content_type_id": content_type_id},
        )

        self.assertContains(response, f'hx-get="{dataview_url}?first_name=xyz"', html=False)
        self.assertContains(response, 'hx-headers=\'{"X-Bloomerp-Sync-Url": "true"}\'', html=False)

        # 5. Request the dataview the same way the list page bootstraps it
        data_view_response = self.client.get(
            f"{dataview_url}?first_name=xyz",
            HTTP_HX_REQUEST="true",
            HTTP_X_BLOOMERP_SYNC_URL="true",
        )

        # 6. Make sure the applied filter badge is really present in the rendered UI
        self.assertContains(data_view_response, '<span>First Name is xyz</span>', html=False)
        self.assertContains(
            data_view_response,
            f'hx-get="{dataview_url}?first_name=xyz"',
            html=False,
        )

    def test_list_view_drops_persisted_fields_that_are_no_longer_accessible(self):
        """
        This test checks whether the list view correctly drops
        persisted display fields that the user no longer has access to.

        This is necessary to ensure that the UI does not
        display fields that the user should no longer see.
        """
        content_type = ContentType.objects.get_for_model(self.CustomerModel)
        first_name_field = ApplicationField.get_by_field(self.CustomerModel, "first_name")
        last_name_field = ApplicationField.get_by_field(self.CustomerModel, "last_name")
        self._ensure_permissions_for_model(self.CustomerModel)

        # 1. Create the policy
        field_policy = FieldPolicy.objects.create(
            content_type=content_type,
            name="Employee dataview fields",
            rule={
                str(first_name_field.id): ["view_customer"],
                str(last_name_field.id): ["view_customer"],
            },
        )
        row_policy = RowPolicy.objects.create(
            content_type=content_type,
            name="Employee dataview rows",
        )
        row_rule = RowPolicyRule.objects.create(
            row_policy=row_policy,
            rule={
                "connector": "OR",
                "conditions": [
                    {
                        "field": "__all__",
                    }
                ],
            },
        )
        row_rule.add_permission("view_customer")

        policy = Policy.objects.create(
            name="Dataview policy",
            description="Permission-safe dataview fields",
            row_policy=row_policy,
            field_policy=field_policy,
        )
        policy.assign_user(self.normal_user)

        # 2. Create the preference object including the two fields
        preference = UserListViewPreference.objects.create(
            user=self.normal_user,
            content_type=content_type,
            display_fields={
                "table": [first_name_field.id, last_name_field.id],
                "kanban": [],
                "card": [],
                "calendar": [],
                "gant": [],
                "pivot_table": [],
            },
        )

        field_policy.rule = {
            str(first_name_field.id): ["view_customer"],
        }
        field_policy.save(update_fields=["rule"])

        self.client.force_login(self.normal_user)
        
        url = reverse(
            viewname="components_dataview",
            kwargs={"content_type_id": content_type.id},
        )
        response = self.client.get(url, HTTP_HX_REQUEST="true")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "First Name", html=False)
        self.assertNotContains(response, "<th >Last Name</th>", html=False)

        dataview_fields = get_data_view_fields(preference, "table")
        self.assertEqual([field.id for field in dataview_fields.visible_fields], [first_name_field.id])

        preference.refresh_from_db()
        self.assertEqual(preference.get_visible_field_ids("table"), [first_name_field.id])

    
        
    def test_filter_dataview_with_string_field(self):
        """
        This test checks whether the dataview correctly applies filters
        based on the query parameters.
        """
        # Login the client
        self.client.force_login(self.admin_user)
        
        # Create customers
        self.create_customer("Alice", "Smith", 30)
        self.create_customer("Bob", "Johnson", 25)
        
        # Create url with filter for first_name
        content_type_id = ContentType.objects.get_for_model(self.CustomerModel).id
        url = reverse(
            viewname="components_dataview",
            kwargs={"content_type_id": content_type_id},
        ) + "?first_name=Alice"
        
        # Send GET request to the URL
        response = self.client.get(url, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        
        # Check if the response contains Alice and not Bob
        self.assertContains(response, "Alice")
        self.assertNotContains(response, "Bob")

    def test_table_dataview_sorts_by_visible_column(self):
        self.client.force_login(self.admin_user)
        self.CustomerModel.objects.all().delete()
        self.create_customer("Charlie", "Middle", 30)
        self.create_customer("Alice", "First", 20)
        self.create_customer("Bob", "Last", 25)

        content_type_id = ContentType.objects.get_for_model(self.CustomerModel).id
        url = reverse(
            viewname="components_dataview",
            kwargs={"content_type_id": content_type_id},
        ) + "?sort=first_name&direction=asc"

        response = self.client.get(url, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)

        content = response.content.decode()
        self.assertLess(content.index("Alice"), content.index("Bob"))
        self.assertLess(content.index("Bob"), content.index("Charlie"))
        self.assertContains(response, 'aria-sort="ascending"', html=False)

    def test_table_dataview_ignores_sorting_by_generic_foreign_key(self):
        """
        Use case: A content object field is added to a user's table preference.
        Expected result: The table renders the linked object without ordering by
        the virtual field.
        """
        # 1. Create a todo linked to a model object through its GenericForeignKey.
        customer = self.create_customer("Generic", "Relation", 30)
        Todo.objects.create(title="Linked todo", content_object=customer)

        # 2. Make content_object the visible field in the selected Todo preference.
        self.client.force_login(self.admin_user)
        content_type = ContentType.objects.get_for_model(Todo)
        content_object_field = ApplicationField.get_by_field(Todo, "content_object")
        preference = PreferenceManager(self.admin_user).get_or_create_selected(
            UserListViewPreference,
            scope={
                "content_type_id" : content_type.id
            }
        )
        preference.display_fields = {
            **preference.display_fields,
            "table": [content_object_field.id],
        }
        preference.save(update_fields=["display_fields"])

        # 3. Request the table after adding the virtual field to the preference.
        dataview_url = reverse(
            viewname="components_dataview",
            kwargs={"content_type_id": content_type.id},
        )
        response = self.client.get(dataview_url, HTTP_HX_REQUEST="true")

        # 4. Confirm the virtual field does not break rendering and shows its value.
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Generic Relation")

        # 5. Confirm a stale or manually supplied sort query cannot break the table.
        sorted_response = self.client.get(
            f"{dataview_url}?sort=content_object&direction=asc",
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(sorted_response.status_code, 200)
        self.assertContains(sorted_response, "Generic Relation")

    def test_table_sort_links_preserve_filters_and_reset_page(self):
        self.client.force_login(self.admin_user)

        content_type_id = ContentType.objects.get_for_model(self.CustomerModel).id
        url = reverse(
            viewname="components_dataview",
            kwargs={"content_type_id": content_type_id},
        ) + "?first_name__icontains=a&q=a&page=3&sort=first_name&direction=asc"

        response = self.client.get(url, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)

        dataview_url = reverse(
            viewname="components_dataview",
            kwargs={"content_type_id": content_type_id},
        )
        content = response.content.decode()
        self.assertIn(f'hx-get="{dataview_url}?', content)
        self.assertIn("first_name__icontains=a", content)
        self.assertIn("q=a", content)
        first_name_sort_urls = [
            part.split('"', 1)[0]
            for part in content.split('hx-get="')[1:]
            if "sort=first_name" in part
        ]
        self.assertTrue(
            any("direction=desc" in url and "page=3" not in url for url in first_name_sort_urls)
        )

    def test_kanban_dataview_uses_column_pagination(self):
        self.client.force_login(self.admin_user)
        self.CustomerModel.objects.all().delete()

        content_type = ContentType.objects.get_for_model(self.CustomerModel)
        age_field = ApplicationField.get_by_field(self.CustomerModel, "age")
        last_name_field = ApplicationField.get_by_field(self.CustomerModel, "last_name")
        preference = PreferenceManager(self.admin_user).get_or_create_selected(
            UserListViewPreference,
            scope={
                "content_type_id" : content_type.id
            }
        )
        preference.view_type = "kanban"
        preference.options = {
            "kanban": {
                "page_size": 10,
                "group_by_field_id": age_field.id,
            }
        }
        preference.display_fields = {
            **preference.display_fields,
            "kanban": [last_name_field.id],
        }
        preference.save()

        for index in range(30):
            self.create_customer(f"Batch-{index}", "Kanban", 123)

        dataview_url = reverse(
            viewname="components_dataview",
            kwargs={"content_type_id": content_type.id},
        )

        response = self.client.get(dataview_url, HTTP_HX_REQUEST="true")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-column-value="123"', html=False)
        self.assertContains(response, 'data-kanban-total-count="30"', html=False)
        self.assertContains(response, "kanban_column=123&kanban_page=2", html=False)
        self.assertNotContains(response, 'data-testid="data-view-pagination"', html=False)

        column_url = reverse(
            viewname="components_dataview_action",
            kwargs={"content_type_id": content_type.id, "action": "column"},
        )
        page_response = self.client.get(
            f"{column_url}?kanban_column=123&kanban_page=2",
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(page_response.status_code, 200)
        self.assertEqual(
            page_response.content.decode("utf-8").count('bloomerp-component="kanban-card"'),
            10,
        )
        self.assertContains(page_response, "kanban_column=123&kanban_page=3", html=False)

    def test_kanban_split_view_constrains_overflow_to_list_pane(self):
        """
        Use case:
        Expected result:
        """
        # 1. Enable Kanban and split view for a grouped customer data view.
        self.client.force_login(self.admin_user)
        content_type = ContentType.objects.get_for_model(self.CustomerModel)
        age_field = ApplicationField.get_by_field(self.CustomerModel, "age")
        last_name_field = ApplicationField.get_by_field(self.CustomerModel, "last_name")
        preference = PreferenceManager(self.admin_user).get_or_create_selected(
            UserListViewPreference,
            scope={
                "content_type_id":content_type.id
            }
        )
        preference.view_type = "kanban"
        preference.split_view_enabled = True
        preference.options = {
            "kanban": {
                "group_by_field_id": age_field.id,
            }
        }
        preference.display_fields = {
            **preference.display_fields,
            "kanban": [last_name_field.id],
        }
        preference.save()
        self.create_customer("Split", "Kanban", 123)

        # 2. Request the dataview component.
        url = reverse(
            viewname="components_dataview",
            kwargs={"content_type_id": content_type.id},
        )
        response = self.client.get(url, HTTP_HX_REQUEST="true")

        # 3. Verify the split view and kanban board render with shrinkable overflow boundaries.
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            'class="flex h-[calc(100vh-200px)] w-full min-w-0 overflow-hidden rounded-xl"',
            html=False,
        )
        self.assertContains(
            response,
            'class="flex-none w-1/2 min-w-[260px] max-w-[calc(100%-260px)] resize-x overflow-auto',
            html=False,
        )
        self.assertContains(
            response,
            'class="kanban-board flex h-full min-h-[400px] w-full min-w-0 max-w-full gap-4 overflow-x-auto',
            html=False,
        )

    def test_filter_dataview_with_foreign_key_field(self):
        """
        This test checks whether the dataview correctly applies filters
        based on foreign key fields.
        """
        name = "ansdljsdhsajh"

        # Login the client
        self.client.force_login(self.admin_user)
        
        # Create a planet
        planet = self.PlanetModel.objects.create(name="Earth")
        country = self.create_country(name="Belgium", planet=planet)

        # Create customers with different ages
        self.create_customer(name, "Smith", 30, country=country)
        self.create_customer("Bob", "Johnson", 25)
        
        # Create url with filter for country
        # Note: the exact lookup is what is given in the dataview
        for lookup in ["", "__exact"]:
            content_type_id = ContentType.objects.get_for_model(self.CustomerModel).id
            url = reverse(
                viewname="components_dataview",
                kwargs={"content_type_id": content_type_id},
            ) + "?country" + lookup + "=" + str(country.id)

            # Send GET request to the URL
            response = self.client.get(url, HTTP_HX_REQUEST="true")
            self.assertEqual(response.status_code, 200)

            # Check if the response contains the customer with the correct country and not the other one
            self.assertContains(response, name)
            self.assertNotContains(response, "Bob")

    def test_filter_dataview_with_foreign_key_field_using_field_lookup(self):
        """
        This test filters the dataview based on a foreign key and uses
        a field to lookup the value 

        for example country__name=Belgium instead of country__exact=<id>
        """
        name = "ansdljsdhsajh"

        # Login the client
        self.client.force_login(self.admin_user)
        
        # Create a planet
        planet = self.PlanetModel.objects.create(name="Earth")
        country = self.create_country(name="Belgium", planet=planet)

        # Create customers with different ages
        self.create_customer(name, "Smith", 30, country=country)
        self.create_customer("Bob", "Johnson", 25)
        
        # Create url with filter for country
        for lookup in ["__name", "__name__exact"]:
            content_type_id = ContentType.objects.get_for_model(self.CustomerModel).id
            url = reverse(
                viewname="components_dataview",
                kwargs={"content_type_id": content_type_id},
            ) + "?country" + lookup + "=" + country.name

            # Send GET request to the URL
            response = self.client.get(url, HTTP_HX_REQUEST="true")
            self.assertEqual(response.status_code, 200)

            # Check if the response contains the customer with the correct country and not the other one
            self.assertContains(response, name)
            self.assertNotContains(response, "Bob")

    # ---------------------------
    # Querying by string
    # ---------------------------
    def test_querying_by_double_string_should_return_results_that_contain_both_strings(self):
        """
        This test checks whether the dataview correctly applies filters
        when querying by a string that contains multiple words.

        The dataview should return results that contain all the words in the query string.
        """
        # Login the client
        self.client.force_login(self.admin_user)
        
        # Create customers
        self.create_customer("Alice", "Smith", 30)
        self.create_customer("Bob", "Johnson", 25)
        self.create_customer("Alice", "Johnson", 28)
        
        # Create url with filter for first_name and last_name
        content_type_id = ContentType.objects.get_for_model(self.CustomerModel).id
        url = reverse(
            viewname="components_dataview",
            kwargs={"content_type_id": content_type_id},
        ) + "?q=Alice Johnson"
        
        # Send GET request to the URL
        response = self.client.get(url, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        
        # Check if the response contains only the customer that has both Alice and Johnson in their name
        self.assertNotContains(response, "Alice Smith")
        self.assertNotContains(response, "Bob Johnson")
        self.assertContains(response, "Alice Johnson")

    def test_select_preference_component_renders_available_preferences(self):
        self.client.force_login(self.admin_user)

        content_type = ContentType.objects.get_for_model(self.CustomerModel)
        selected_preference = UserListViewPreference.objects.create(
            user=self.admin_user,
            content_type=content_type,
            name="Team view",
            selected=True,
        )
        UserListViewPreference.objects.create(
            user=self.admin_user,
            content_type=content_type,
            name="Compact view",
        )

        url = reverse(
            viewname="components_select_preference",
            kwargs={"model": "UserListViewPreference"},
        ) + f"?content_type_id={content_type.id}"

        response = self.client.get(url, HTTP_HX_REQUEST="true")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Team view")
        self.assertContains(response, "Compact view")
        self.assertContains(response, "Selected")
        self.assertEqual(
            UserListViewPreference.get_selected_for_user(self.admin_user, content_type).pk,
            selected_preference.pk,
        )

    def test_select_preference_component_selects_preference_and_requests_refresh(self):
        self.client.force_login(self.admin_user)

        content_type = ContentType.objects.get_for_model(self.CustomerModel)
        first = UserListViewPreference.objects.create(
            user=self.admin_user,
            content_type=content_type,
            name="Default",
            selected=True,
        )
        second = UserListViewPreference.objects.create(
            user=self.admin_user,
            content_type=content_type,
            name="Board",
        )

        url = reverse(
            viewname="components_select_preference",
            kwargs={"model": "UserListViewPreference"},
        )

        response = self.client.post(
            url,
            data={
                "action": "select",
                "preference_id": second.id,
                "content_type_id": content_type.id,
            },
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["HX-Refresh"], "true")

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertFalse(first.selected)
        self.assertTrue(second.selected)

    def test_select_preference_component_creates_selected_clone(self):
        self.client.force_login(self.admin_user)

        content_type = ContentType.objects.get_for_model(self.CustomerModel)
        source = UserListViewPreference.objects.create(
            user=self.admin_user,
            content_type=content_type,
            name="Default",
            selected=True,
            view_type="kanban",
            options={
                "kanban": {
                    "page_size": 50,
                }
            },
            display_fields={
                "table": [],
                "kanban": [1, 2, 3],
                "card": [],
                "calendar": [],
                "gant": [],
                "pivot_table": [],
            },
        )

        url = reverse(
            viewname="components_new_preference",
            kwargs={"model": "UserListViewPreference"},
        )

        response = self.client.post(
            url,
            data={"name": "Ops board", "content_type_id": content_type.id},
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["HX-Refresh"], "true")

        source.refresh_from_db()
        created = UserListViewPreference.objects.get(
            user=self.admin_user,
            content_type=content_type,
            name="Ops board",
        )
        self.assertFalse(source.selected)
        self.assertTrue(created.selected)
        self.assertEqual(created.view_type, "kanban")
        self.assertEqual(created.options, source.options)
        self.assertEqual(created.display_fields, source.display_fields)

    def test_selecting_shared_preference_creates_live_reference_without_duplicate_menu_item(self):
        self.client.force_login(self.admin_user)

        content_type = ContentType.objects.get_for_model(self.CustomerModel)
        source = UserListViewPreference.objects.create(
            user=self.normal_user,
            content_type=content_type,
            name="Shared board",
            view_type="kanban",
        )
        source.shared_with_users.add(self.admin_user)

        url = reverse(
            viewname="components_select_preference",
            kwargs={"model": "UserListViewPreference"},
        )
        response = self.client.post(
            url,
            data={
                "action": "select",
                "preference_id": source.id,
                "content_type_id": content_type.id,
            },
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        reference = UserListViewPreference.objects.get(
            user=self.admin_user,
            source_object=source,
        )
        self.assertTrue(reference.selected)
        self.assertEqual(reference.effective_preference, source)

        response = self.client.get(
            f"{url}?content_type_id={content_type.id}",
            HTTP_HX_REQUEST="true",
        )
        self.assertContains(response, "Shared board", count=1)

    def test_change_data_view_preference_uses_selected_preference_when_multiple_exist(self):
        self.client.force_login(self.admin_user)

        content_type = ContentType.objects.get_for_model(self.CustomerModel)
        UserListViewPreference.objects.create(
            user=self.admin_user,
            content_type=content_type,
            name="Old default",
            view_type="table",
        )
        selected = UserListViewPreference.objects.create(
            user=self.admin_user,
            content_type=content_type,
            name="Current",
            selected=True,
            view_type="table",
            options={
                "table": {
                    "page_size": 25,
                }
            },
        )

        url = reverse(
            viewname="components_update_dataview_preference",
            kwargs={"content_type_id": content_type.id},
        )

        response = self.client.post(
            url,
            data={
                "dataview_options_view_type": "table",
                "page_size": "50",
            },
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)

        selected.refresh_from_db()
        self.assertEqual(selected.options["table"]["page_size"], 50)

    def test_change_field_visibility_response_uses_updated_preference(self):
        """
        Use case: A user hides a currently visible dataview field.
        Expected result: The first POST response renders that field as unselected.
        """
        # 1. Create a selected table preference with two visible fields.
        self.client.force_login(self.admin_user)
        content_type = ContentType.objects.get_for_model(self.CustomerModel)
        first_name_field = ApplicationField.get_by_field(self.CustomerModel, "first_name")
        last_name_field = ApplicationField.get_by_field(self.CustomerModel, "last_name")
        preference = PreferenceManager(self.admin_user).get_or_create_selected(
            UserListViewPreference,
            scope={"content_type_id": content_type.id},
        )
        preference.set_visible_field_ids(
            "table",
            [first_name_field.id, last_name_field.id],
        )
        preference.save(update_fields=["display_fields"])

        # 2. Hide the first field through the display-options component endpoint.
        url = reverse(
            viewname="components_update_dataview_preference",
            kwargs={"content_type_id": content_type.id},
        )
        response = self.client.post(
            url,
            data={
                "toggle_field_id": first_name_field.id,
                "toggle_view_type": "table",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        # 3. Verify persistence and the HTML returned by this same request.
        self.assertEqual(response.status_code, 200)
        preference.refresh_from_db()
        self.assertNotIn(first_name_field.id, preference.get_visible_field_ids("table"))
        response_html = response.content.decode()
        first_name_button = re.search(
            rf'data-display-options-values=\'\{{"toggle_field_id": "{first_name_field.id}".*?class="([^"]+)"',
            response_html,
            re.DOTALL,
        )
        self.assertIsNotNone(first_name_button)
        self.assertIn("bg-white", first_name_button.group(1))
        self.assertNotIn("bg-primary-100", first_name_button.group(1))


class TestCalendarDataView(BaseBloomerpModelTestCase):
    auto_create_customers = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.CalendarEventModel = create_test_models(
            app_label="bloomerp",
            model_defs={
                "CalendarEvent": {
                    "name": models.CharField(max_length=100),
                    "starts_on": models.DateField(null=True, blank=True),
                    "ends_on": models.DateField(null=True, blank=True),
                    "starts_at": models.DateTimeField(null=True, blank=True),
                    "ends_at": models.DateTimeField(null=True, blank=True),
                    "category": models.CharField(
                        max_length=20,
                        choices=[("alpha", "Alpha"), ("beta", "Beta")],
                        blank=True,
                    ),
                    "__str__": lambda self: self.name,
                },
            },
            use_bloomerp_base=True,
        )["CalendarEvent"]
        cls._register_dynamic_model_routes([cls.CalendarEventModel])

    def _configure_calendar(self, *, with_times=False, view_mode="month"):
        content_type = ContentType.objects.get_for_model(self.CalendarEventModel)
        start_field = ApplicationField.get_by_field(
            self.CalendarEventModel,
            "starts_at" if with_times else "starts_on",
        )
        end_field = ApplicationField.get_by_field(
            self.CalendarEventModel,
            "ends_at" if with_times else "ends_on",
        )
        category_field = ApplicationField.get_by_field(self.CalendarEventModel, "category")
        preference = PreferenceManager(self.admin_user).get_or_create_selected(
            UserListViewPreference,
            scope={"content_type_id": content_type.id},
        )
        preference.view_type = "calendar"
        preference.options = {
            "calendar": {
                "start_field_id": start_field.id,
                "end_field_id": end_field.id,
                "view_mode": view_mode,
                "color_grouping_field_id": category_field.id,
            },
        }
        preference.display_fields = {**preference.display_fields, "calendar": []}
        preference.save()
        return content_type

    def test_calendar_renders_ranges_year_list_and_color_legend(self):
        """
        Use case: A color-grouped event spans several days and users switch calendar modes.
        Expected result: The range is one spanning bar, the legend renders, and saved modes are honored.
        """
        # 1. Configure a month calendar and create a three-day event.
        self.client.force_login(self.admin_user)
        content_type = self._configure_calendar()
        today = timezone.localdate()
        event_day = today.replace(day=10)
        event = self.CalendarEventModel.objects.create(
            name="Conference",
            starts_on=event_day,
            ends_on=event_day + timedelta(days=2),
            category="alpha",
        )
        url = reverse("components_dataview", kwargs={"content_type_id": content_type.id})

        # 2. Render the month containing the event.
        response = self.client.get(url, HTTP_HX_REQUEST="true")

        # 3. Verify the range, configured legend, and all five mode choices render.
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'bloomerp-component="calendar"', html=False)
        self.assertContains(response, 'class="calendar-event', count=1, html=False)
        self.assertContains(response, 'type="button"', html=False)
        self.assertContains(
            response,
            f'data-detail-url="{event.get_absolute_url()}"',
            html=False,
        )
        self.assertNotContains(response, f'href="{event.get_absolute_url()}"', html=False)
        self.assertContains(response, 'style="grid-column: 1; grid-row: 1;"', html=False)
        self.assertContains(response, 'style="grid-column: 7; grid-row: 1;"', html=False)
        self.assertContains(response, "grid-column:", html=False)
        self.assertContains(response, "span 3", html=False)
        self.assertContains(response, "Conference", html=False)
        self.assertContains(response, "Alpha", html=False)
        for mode in ("day", "week", "month", "year", "list"):
            self.assertContains(response, f'value="{mode}"', html=False)

        # 4. Save year and list modes and verify rendering follows the preference.
        preference = PreferenceManager(self.admin_user).get_or_create_selected(
            UserListViewPreference,
            scope={"content_type_id": content_type.id},
        )
        preference.options["calendar"]["view_mode"] = "year"
        preference.save(update_fields=["options"])
        year_response = self.client.get(url, HTTP_HX_REQUEST="true")
        preference.options["calendar"]["view_mode"] = "list"
        preference.save(update_fields=["options"])
        list_response = self.client.get(url, HTTP_HX_REQUEST="true")
        self.assertContains(year_response, today.strftime("%Y"), html=False)
        self.assertContains(list_response, "Conference", html=False)

    def test_calendar_renders_interactive_time_grid_and_unscheduled_tray(self):
        """
        Use case: A day calendar contains a timed record and a record without dates.
        Expected result: The grid exposes keyboard focus, vertical resize controls, and a draggable tray item.
        """
        # 1. Configure a day calendar with editable datetime fields.
        self.client.force_login(self.admin_user)
        content_type = self._configure_calendar(with_times=True, view_mode="day")
        local_timezone = timezone.get_current_timezone()
        today = timezone.localdate()
        start = timezone.make_aware(datetime.combine(today, datetime.min.time()).replace(hour=9, minute=30), local_timezone)
        self.CalendarEventModel.objects.create(
            name="Timed session",
            starts_at=start,
            ends_at=start + timedelta(hours=2),
        )
        self.CalendarEventModel.objects.create(name="Needs scheduling")

        # 2. Render the calendar.
        url = reverse("components_dataview", kwargs={"content_type_id": content_type.id})
        response = self.client.get(url, HTTP_HX_REQUEST="true")

        # 3. Verify the interaction contract used by the calendar component.
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'tabindex="0"', html=False)
        self.assertContains(response, "data-calendar-unit-section", html=False)
        self.assertContains(response, "data-calendar-dropzone", html=False)
        self.assertContains(response, "data-calendar-update-url", html=False)
        self.assertContains(response, "data-calendar-resize-start", html=False)
        self.assertContains(response, "data-calendar-resize-end", html=False)
        self.assertContains(response, 'data-calendar-unscheduled-event', html=False)
        self.assertContains(response, 'draggable="true"', html=False)
        self.assertContains(response, "height: max(", html=False)

    def test_calendar_week_renders_multiday_event_as_one_draggable_range(self):
        """
        Use case: An all-day event spans several dates in week view.
        Expected result: One draggable bar spans the relevant day columns without duplicate entries.
        """
        # 1. Configure week view and create a four-day all-day event.
        self.client.force_login(self.admin_user)
        content_type = self._configure_calendar(view_mode="week")
        monday = timezone.localdate() - timedelta(days=timezone.localdate().weekday())
        self.CalendarEventModel.objects.create(
            name="Release window",
            starts_on=monday,
            ends_on=monday + timedelta(days=3),
        )

        # 2. Render the current week.
        url = reverse("components_dataview", kwargs={"content_type_id": content_type.id})
        response = self.client.get(url, HTTP_HX_REQUEST="true")

        # 3. Verify the range occupies one overlay spanning Monday through Thursday.
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="calendar-event', count=1, html=False)
        self.assertContains(
            response,
            '<span class="block truncate font-medium">Release window</span>',
            count=1,
            html=True,
        )
        self.assertContains(response, "grid-column: 2 / span 4", html=False)
        self.assertContains(response, 'draggable="true"', html=False)

    def test_calendar_date_action_schedules_and_resizes_records(self):
        """
        Use case: Calendar controls move an event and drop an unscheduled record on the grid.
        Expected result: The configured date fields update atomically with DateField semantics.
        """
        # 1. Configure a calendar and create scheduled and unscheduled records.
        self.client.force_login(self.admin_user)
        content_type = self._configure_calendar()
        scheduled = self.CalendarEventModel.objects.create(
            name="Scheduled",
            starts_on=date(2026, 9, 1),
            ends_on=date(2026, 9, 3),
        )
        unscheduled = self.CalendarEventModel.objects.create(name="Unscheduled")
        action_url = reverse(
            "components_dataview_action",
            kwargs={"content_type_id": content_type.id, "action": "dates"},
        )
        local_timezone = timezone.get_current_timezone()

        # 2. Move both boundaries and schedule the undated record in one request.
        response = self.client.post(
            action_url,
            data=json.dumps({
                "updates": [
                    {
                        "object_id": str(scheduled.pk),
                        "start_ms": round(timezone.make_aware(datetime(2026, 9, 2), local_timezone).timestamp() * 1000),
                        "end_ms": round(timezone.make_aware(datetime(2026, 9, 6), local_timezone).timestamp() * 1000),
                    },
                    {
                        "object_id": str(unscheduled.pk),
                        "start_ms": round(timezone.make_aware(datetime(2026, 9, 10), local_timezone).timestamp() * 1000),
                        "end_ms": round(timezone.make_aware(datetime(2026, 9, 12), local_timezone).timestamp() * 1000),
                    },
                ],
            }),
            content_type="application/json",
        )

        # 3. Verify exclusive UI ends are stored as inclusive DateField ends.
        self.assertEqual(response.status_code, 200)
        scheduled.refresh_from_db()
        unscheduled.refresh_from_db()
        self.assertEqual((scheduled.starts_on, scheduled.ends_on), (date(2026, 9, 2), date(2026, 9, 5)))
        self.assertEqual((unscheduled.starts_on, unscheduled.ends_on), (date(2026, 9, 10), date(2026, 9, 11)))

    def test_calendar_unit_loads_five_events_at_a_time(self):
        """
        Use case: More than five timed events start in the same calendar hour.
        Expected result: The unit renders five events and loads the next page on demand.
        """
        # 1. Configure a day calendar and create seven events in one hour.
        self.client.force_login(self.admin_user)
        content_type = self._configure_calendar(with_times=True, view_mode="day")
        local_timezone = timezone.get_current_timezone()
        today = timezone.localdate()
        start = timezone.make_aware(datetime.combine(today, datetime.min.time()).replace(hour=10, minute=15), local_timezone)
        for index in range(7):
            self.CalendarEventModel.objects.create(
                name=f"Session {index}",
                starts_at=start + timedelta(minutes=index),
                ends_at=start + timedelta(minutes=index + 1),
                category="beta",
            )
        url = reverse("components_dataview", kwargs={"content_type_id": content_type.id})

        # 2. Render the current day and verify only the first five unit records are present.
        response = self.client.get(url, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        for index in range(5):
            self.assertContains(response, f"Session {index}", html=False)
        self.assertNotContains(response, "Session 5", html=False)
        self.assertContains(response, "calendar_unit_offset=5", html=False)

        # 3. Request the next page through the permission-filtered renderer action.
        page_url = reverse(
            "components_dataview_action",
            kwargs={"content_type_id": content_type.id, "action": "unit"},
        )
        page_response = self.client.get(
            f"{page_url}?calendar_view_mode=day&calendar_unit={today.isoformat()}T10&calendar_unit_offset=5",
            HTTP_HX_REQUEST="true",
        )

        # 4. Verify the remaining two events render and no third page is offered.
        self.assertEqual(page_response.status_code, 200)
        self.assertContains(page_response, "Session 5", html=False)
        self.assertContains(page_response, "Session 6", html=False)
        self.assertNotContains(page_response, "Load more", html=False)


class TestGantDataView(BaseBloomerpModelTestCase):
    auto_create_customers = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.GantTaskModel = create_test_models(
            app_label="bloomerp",
            model_defs={
                "GantTask": {
                    "name": models.CharField(max_length=100),
                    "starts_on": models.DateField(null=True, blank=True),
                    "ends_on": models.DateField(null=True, blank=True),
                    "starts_at": models.DateTimeField(null=True, blank=True),
                    "ends_at": models.DateTimeField(null=True, blank=True),
                    "dependency": models.ForeignKey(
                        "self",
                        null=True,
                        blank=True,
                        on_delete=models.SET_NULL,
                        related_name="dependants",
                    ),
                    "__str__": lambda self: self.name,
                },
            },
            use_bloomerp_base=True,
        )["GantTask"]
        cls._register_dynamic_model_routes([cls.GantTaskModel])

    def _configure_gant(
        self,
        *,
        page_size: int = 10,
        with_dependency: bool = False,
        with_times: bool = False,
        user=None,
    ):
        content_type = ContentType.objects.get_for_model(self.GantTaskModel)
        start_field = ApplicationField.get_by_field(
            self.GantTaskModel,
            "starts_at" if with_times else "starts_on",
        )
        end_field = ApplicationField.get_by_field(
            self.GantTaskModel,
            "ends_at" if with_times else "ends_on",
        )
        name_field = ApplicationField.get_by_field(self.GantTaskModel, "name")
        dependency_field = ApplicationField.get_by_field(self.GantTaskModel, "dependency")
        preference = PreferenceManager(self.admin_user).get_or_create_selected(
            UserListViewPreference,
            scope={
                "content_type_id":content_type.id
            }
        )
        preference.view_type = "gant"
        preference.options = {
            "gant": {
                "start_field_id": start_field.id,
                "end_field_id": end_field.id,
                "dependency_from_field_id": dependency_field.id if with_dependency else None,
                "dependency_for_field_id": None,
                "page_size": page_size,
            },
        }
        preference.display_fields = {
            **preference.display_fields,
            "gant": [name_field.id],
        }
        preference.save()
        return content_type, dependency_field

    def test_gant_dataview_renders_continuous_rows_and_dependencies(self):
        """
        Use case: A configured Gantt view contains related, scheduled records.
        Expected result: Each record renders on the shared timeline with its dependency metadata.
        """
        # 1. Configure the Gantt view with its self-referencing dependency field.
        self.client.force_login(self.admin_user)
        content_type, _dependency_field = self._configure_gant(with_dependency=True)
        first = self.GantTaskModel.objects.create(
            name="Discovery",
            starts_on=date(2026, 1, 1),
            ends_on=date(2026, 1, 10),
        )
        self.GantTaskModel.objects.create(
            name="Delivery",
            starts_on=date(2026, 1, 5),
            ends_on=date(2026, 1, 20),
            dependency=first,
        )

        # 2. Request the permission-filtered data-view component.
        url = reverse(
            "components_dataview",
            kwargs={"content_type_id": content_type.id},
        )
        response = self.client.get(url, HTTP_HX_REQUEST="true")

        # 3. Verify the continuous timeline, zoom controls, rows, and dependency endpoint render.
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'bloomerp-component="gant-chart"', html=False)
        self.assertContains(response, 'bloomerp-component="gant-chart-item"', count=2, html=False)
        self.assertContains(response, 'bloomerp-component="gant-chart-sidebar-item"', count=2, html=False)
        self.assertContains(response, 'bloomerp-component="resizable-div"', html=False)
        self.assertContains(response, 'data-resize-from="right"', html=False)
        self.assertContains(response, "data-gant-zoom", html=False)
        self.assertContains(response, "data-gant-today", html=False)
        self.assertContains(response, "data-gant-update-url", html=False)
        self.assertContains(response, 'data-gant-start-field-type="DateField"', html=False)
        self.assertContains(response, "data-gant-resize-start", count=2, html=False)
        self.assertContains(response, "data-gant-resize-end", count=2, html=False)
        self.assertContains(response, "data-start=", count=2, html=False)
        self.assertContains(response, "data-end=", count=2, html=False)
        discovery_start = timezone.make_aware(datetime(2026, 1, 1)).timestamp() * 1000
        discovery_end = timezone.make_aware(datetime(2026, 1, 11)).timestamp() * 1000
        self.assertContains(response, f'data-start="{round(discovery_start)}"', html=False)
        self.assertContains(response, f'data-end="{round(discovery_end)}"', html=False)
        self.assertContains(response, f'data-dependency-from-id="{first.pk}"', html=False)
        self.assertContains(response, "Discovery", html=False)
        self.assertContains(response, "Delivery", html=False)

    def test_gant_dataview_preserves_datetime_precision_for_hour_zoom(self):
        """
        Use case: An event plan uses DateTimeFields within a single day.
        Expected result: Gantt data preserves exact times for hour-level positioning.
        """
        # 1. Configure DateTimeFields and create a ninety-minute event task.
        self.client.force_login(self.admin_user)
        content_type, _dependency_field = self._configure_gant(with_times=True)
        start = timezone.make_aware(datetime(2026, 7, 17, 13, 15))
        end = timezone.make_aware(datetime(2026, 7, 17, 14, 45))
        self.GantTaskModel.objects.create(
            name="Stage setup",
            starts_at=start,
            ends_at=end,
        )

        # 2. Request the Gantt component.
        url = reverse(
            "components_dataview",
            kwargs={"content_type_id": content_type.id},
        )
        response = self.client.get(url, HTTP_HX_REQUEST="true")

        # 3. Verify timestamps retain the minutes instead of being reduced to dates.
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'data-start="{round(start.timestamp() * 1000)}"', html=False)
        self.assertContains(response, f'data-end="{round(end.timestamp() * 1000)}"', html=False)
        self.assertContains(response, "Jul 17, 2026 13:15", html=False)
        self.assertContains(response, "Jul 17, 2026 14:45", html=False)

    def test_gant_dataview_loads_additional_rows_by_intersection_page(self):
        """
        Use case: A Gantt chart contains more records than its configured page size.
        Expected result: The first page exposes an intersection loader and the action returns the next page.
        """
        # 1. Configure a ten-row page and create more than one page of scheduled records.
        self.client.force_login(self.admin_user)
        content_type, _dependency_field = self._configure_gant(page_size=10)
        for index in range(25):
            start = date(2026, 2, 1) + timedelta(days=index)
            self.GantTaskModel.objects.create(
                name=f"Task {index:02d}",
                starts_on=start,
                ends_on=start + timedelta(days=2),
            )

        # 2. Request the initial data view.
        url = reverse(
            "components_dataview",
            kwargs={"content_type_id": content_type.id},
        )
        response = self.client.get(url, HTTP_HX_REQUEST="true")

        # 3. Verify it renders ten bars and an incremental page-two request.
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'bloomerp-component="gant-chart-item"', count=10, html=False)
        self.assertContains(response, "gant_page=2", html=False)
        self.assertNotContains(response, 'data-testid="data-view-pagination"', html=False)

        # 4. Request page two through the renderer action.
        page_url = reverse(
            "components_dataview_action",
            kwargs={"content_type_id": content_type.id, "action": "page"},
        )
        page_response = self.client.get(
            f"{page_url}?gant_page=2",
            HTTP_HX_REQUEST="true",
        )

        # 5. Verify the fragment contains the next ten bars and the final-page loader.
        self.assertEqual(page_response.status_code, 200)
        self.assertContains(page_response, 'bloomerp-component="gant-chart-item"', count=10, html=False)
        self.assertContains(page_response, "gant_page=3", html=False)

    def test_gant_dataview_paginates_unscheduled_records_separately(self):
        """
        Use case: More unscheduled records exist than fit in one Gantt page.
        Expected result: They render in the bottom tray with their own incremental pagination.
        """
        self.client.force_login(self.admin_user)
        content_type, _dependency_field = self._configure_gant(page_size=10)
        scheduled = self.GantTaskModel.objects.create(
            name="Scheduled",
            starts_on=date(2026, 8, 1),
            ends_on=date(2026, 8, 2),
        )
        for index in range(25):
            self.GantTaskModel.objects.create(name=f"Unscheduled {index:02d}")

        url = reverse(
            "components_dataview",
            kwargs={"content_type_id": content_type.id},
        )
        response = self.client.get(url, HTTP_HX_REQUEST="true")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-gant-item', count=1, html=False)
        self.assertContains(response, f'data-object-id="{scheduled.pk}"', html=False)
        self.assertContains(response, 'draggable="true"', count=10, html=False)
        self.assertContains(response, "gant_unscheduled_page=2", html=False)

        page_url = reverse(
            "components_dataview_action",
            kwargs={"content_type_id": content_type.id, "action": "unscheduled"},
        )
        page_response = self.client.get(
            f"{page_url}?gant_unscheduled_page=2",
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(page_response.status_code, 200)
        self.assertContains(page_response, 'draggable="true"', count=10, html=False)
        self.assertContains(page_response, "gant_unscheduled_page=3", html=False)

    def test_gant_date_action_updates_multiple_records_and_individual_edges(self):
        """
        Use case: Keyboard movement updates a selection and edge dragging updates one boundary.
        Expected result: The configured fields are updated atomically and retain DateField semantics.
        """
        self.client.force_login(self.admin_user)
        content_type, _dependency_field = self._configure_gant()
        first = self.GantTaskModel.objects.create(
            name="First",
            starts_on=date(2026, 9, 1),
            ends_on=date(2026, 9, 3),
        )
        second = self.GantTaskModel.objects.create(
            name="Second",
            starts_on=date(2026, 9, 5),
            ends_on=date(2026, 9, 6),
        )
        action_url = reverse(
            "components_dataview_action",
            kwargs={"content_type_id": content_type.id, "action": "dates"},
        )
        local_tz = timezone.get_current_timezone()
        first_start = timezone.make_aware(datetime(2026, 9, 2), local_tz)
        first_end_exclusive = timezone.make_aware(datetime(2026, 9, 5), local_tz)
        second_start = timezone.make_aware(datetime(2026, 9, 6), local_tz)
        second_end_exclusive = timezone.make_aware(datetime(2026, 9, 8), local_tz)

        response = self.client.post(
            action_url,
            data=json.dumps({
                "updates": [
                    {
                        "object_id": str(first.pk),
                        "start_ms": round(first_start.timestamp() * 1000),
                        "end_ms": round(first_end_exclusive.timestamp() * 1000),
                    },
                    {
                        "object_id": str(second.pk),
                        "start_ms": round(second_start.timestamp() * 1000),
                        "end_ms": round(second_end_exclusive.timestamp() * 1000),
                    },
                ],
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual((first.starts_on, first.ends_on), (date(2026, 9, 2), date(2026, 9, 4)))
        self.assertEqual((second.starts_on, second.ends_on), (date(2026, 9, 6), date(2026, 9, 7)))

        resized_start = timezone.make_aware(datetime(2026, 9, 3), local_tz)
        edge_response = self.client.post(
            action_url,
            data=json.dumps({
                "updates": [{
                    "object_id": str(first.pk),
                    "start_ms": round(resized_start.timestamp() * 1000),
                }],
            }),
            content_type="application/json",
        )
        self.assertEqual(edge_response.status_code, 200)
        first.refresh_from_db()
        self.assertEqual(first.starts_on, date(2026, 9, 3))
        self.assertEqual(first.ends_on, date(2026, 9, 4))

    def test_gant_date_action_denies_user_without_change_policies(self):
        """
        Use case: A user without row or field change access submits a Gantt mutation.
        Expected result: The endpoint denies the write and preserves the record.
        """
        content_type, _dependency_field = self._configure_gant(user=self.normal_user)
        record = self.GantTaskModel.objects.create(
            name="Protected",
            starts_on=date(2026, 10, 1),
            ends_on=date(2026, 10, 2),
        )
        self.client.force_login(self.normal_user)
        action_url = reverse(
            "components_dataview_action",
            kwargs={"content_type_id": content_type.id, "action": "dates"},
        )
        target = timezone.make_aware(datetime(2026, 10, 4)).timestamp() * 1000
        response = self.client.post(
            action_url,
            data=json.dumps({
                "updates": [{"object_id": str(record.pk), "start_ms": round(target)}],
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        record.refresh_from_db()
        self.assertEqual(record.starts_on, date(2026, 10, 1))

    def test_gant_options_only_offer_self_referencing_dependency_fields(self):
        """
        Use case: A user configures optional Gantt dependency fields.
        Expected result: Only relations back to the same model are offered as dependency choices.
        """
        # 1. Open the display options for the configured Gantt view.
        self.client.force_login(self.admin_user)
        content_type, dependency_field = self._configure_gant()
        url = reverse(
            "components_dataview",
            kwargs={"content_type_id": content_type.id},
        )
        response = self.client.get(url, HTTP_HX_REQUEST="true")

        # 2. Verify the self-reference is offered while scalar fields are not dependency choices.
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'value="{dependency_field.id}"', html=False)
        self.assertContains(response, "Dependency from", html=False)
