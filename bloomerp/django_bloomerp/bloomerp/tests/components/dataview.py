from django.urls import reverse
from django.contrib.contenttypes.models import ContentType
from django.contrib.auth.models import Permission
from bloomerp.tests.base import BaseBloomerpModelTestCase
from bloomerp.models import ApplicationField
from bloomerp.models import Policy, FieldPolicy, RowPolicy, RowPolicyRule
from bloomerp.models.users.user_list_view_preference import UserListViewPreference
from bloomerp.services.user_services import get_data_view_fields, get_user_list_view_preference


class TestDataView(BaseBloomerpModelTestCase):
    create_foreign_models = True

    def extendedSetup(self):
        return super().extendedSetup()    

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
        
    def test_update_field_get(self):
        """
        This test checks whether it's possible to update fields
        """
        # Login the client
        self.client.force_login(self.admin_user)
        
        # Get the customer object
        customer = self.CustomerModel.objects.first()
        
        # Create url
        url = reverse(
            viewname="components_dataview_edit_field", 
            kwargs={
                    "application_field_id" : ApplicationField.get_by_field(self.CustomerModel, "first_name").id,
                    "object_id" : str(customer.id)
                }
            )
        
        # Send GET request to the URL
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        
        # Check if the response contains an input element
        self.assertContains(response, '<input', html=False)
    
    def test_update_field_post_success(self):
        """
        This test checks whether it's possible to update fields via POST
        """
        # Login the client
        self.client.force_login(self.admin_user)
        
        # Get the customer object
        customer = self.CustomerModel.objects.first()
        
        # Get the application field for first_name
        application_field = ApplicationField.get_by_field(self.CustomerModel, "first_name")
        
        # Create url
        url = reverse(
            viewname="components_dataview_edit_field", 
            kwargs={
                    "application_field_id" : application_field.id,
                    "object_id" : str(customer.id)
                }
            )
        
        # Send POST request to the URL
        new_first_name = "UpdatedName"
        response = self.client.post(url, data={application_field.field: new_first_name})
        self.assertEqual(response.status_code, 200)
        
        # Refresh the customer object from the database
        customer.refresh_from_db()
        
        # Check if the first_name field was updated
        self.assertEqual(customer.first_name, new_first_name)
        
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
            viewname="components_data_view",
            kwargs={"content_type_id": content_type_id},
        )

        self.assertContains(response, f'hx-get="{dataview_url}?first_name=xyz"', html=False)

    def test_list_view_export_button_includes_active_filters(self):
        self.client.force_login(self.admin_user)

        content_type_id = ContentType.objects.get_for_model(self.CustomerModel).id
        url = reverse(
            viewname="components_data_view",
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
            viewname="components_data_view",
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
                "field": "__all__",
                "application_field_id": "__all__",
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
            viewname="components_data_view",
            kwargs={"content_type_id": content_type.id},
        )
        response = self.client.get(url, HTTP_HX_REQUEST="true")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "First Name", html=False)
        self.assertNotContains(response, "<th >Last Name</th>", html=False)

        data_view_fields = get_data_view_fields(preference, "table")
        self.assertEqual([field.id for field in data_view_fields.visible_fields], [first_name_field.id])

        preference.refresh_from_db()
        self.assertEqual(preference.get_visible_field_ids("table"), [first_name_field.id])

    def test_get_user_list_view_preference_returns_selected_saved_view(self):
        content_type = ContentType.objects.get_for_model(self.CustomerModel)
        first = UserListViewPreference.objects.create(
            user=self.admin_user,
            content_type=content_type,
            name="Default",
        )
        second = UserListViewPreference.objects.create(
            user=self.admin_user,
            content_type=content_type,
            name="Compact",
            selected=True,
        )

        resolved = get_user_list_view_preference(self.admin_user, content_type)

        first.refresh_from_db()
        second.refresh_from_db()

        self.assertEqual(resolved.pk, second.pk)
        self.assertFalse(first.selected)
        self.assertTrue(second.selected)
        
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
            viewname="components_data_view",
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
            viewname="components_data_view",
            kwargs={"content_type_id": content_type_id},
        ) + "?sort=first_name&direction=asc"

        response = self.client.get(url, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)

        content = response.content.decode()
        self.assertLess(content.index("Alice"), content.index("Bob"))
        self.assertLess(content.index("Bob"), content.index("Charlie"))
        self.assertContains(response, 'aria-sort="ascending"', html=False)

    def test_table_sort_links_preserve_filters_and_reset_page(self):
        self.client.force_login(self.admin_user)

        content_type_id = ContentType.objects.get_for_model(self.CustomerModel).id
        url = reverse(
            viewname="components_data_view",
            kwargs={"content_type_id": content_type_id},
        ) + "?first_name__icontains=a&q=a&page=3&sort=first_name&direction=asc"

        response = self.client.get(url, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)

        dataview_url = reverse(
            viewname="components_data_view",
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
                viewname="components_data_view",
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
                viewname="components_data_view",
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
            viewname="components_data_view",
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
            kwargs={"content_type_id": content_type.id, "type": "list"},
        )

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
            kwargs={"content_type_id": content_type.id, "type": "list"},
        )

        response = self.client.post(
            url,
            data={"action": "select", "preference_id": second.id},
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
            page_size=50,
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
            viewname="components_select_preference",
            kwargs={"content_type_id": content_type.id, "type": "list"},
        )

        response = self.client.post(
            url,
            data={"action": "create", "name": "Ops board"},
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
        self.assertEqual(created.page_size, 50)
        self.assertEqual(created.display_fields, source.display_fields)

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
            page_size=25,
        )

        url = reverse(
            viewname="components_change_data_view_preference",
            kwargs={"content_type_id": content_type.id},
        )

        response = self.client.post(
            url,
            data={"page_size": "50"},
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)

        selected.refresh_from_db()
        self.assertEqual(selected.page_size, 50)
