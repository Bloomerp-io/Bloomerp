from django.urls import reverse
from django.contrib.contenttypes.models import ContentType
from bloomerp.tests.base import BaseBloomerpModelTestCase
from bloomerp.models import ApplicationField

class TestDataView(BaseBloomerpModelTestCase):
    def extendedSetup(self):
        return super().extendedSetup()    
        
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
        

    



