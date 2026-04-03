from django.urls import reverse
from django.contrib.contenttypes.models import ContentType
from django.contrib.auth.models import Permission
from bloomerp.tests.base import BaseBloomerpModelTestCase
from bloomerp.models import ApplicationField
from bloomerp.models import Policy, FieldPolicy, RowPolicy, RowPolicyRule
from bloomerp.models.users.user_list_view_preference import UserListViewPreference
from bloomerp.services.user_services import get_data_view_fields

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
        self.assertContains(response, "<th >First Name</th>", html=False)
        self.assertNotContains(response, "<th >Last Name</th>", html=False)

        data_view_fields = get_data_view_fields(preference, "table")
        self.assertEqual([field.id for field in data_view_fields.visible_fields], [first_name_field.id])

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
            viewname="components_data_view",
            kwargs={"content_type_id": content_type_id},
        ) + "?first_name=Alice"
        
        # Send GET request to the URL
        response = self.client.get(url, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        
        # Check if the response contains Alice and not Bob
        self.assertContains(response, "Alice")
        self.assertNotContains(response, "Bob")

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

    
